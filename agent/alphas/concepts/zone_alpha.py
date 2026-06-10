"""Supply/Demand zone alpha — v3.2, flagship.

The v2 grid showed S/D zones are the only single-concept alpha with real
statistical signal:
  * v2 ``zone/H4/all``               n=1041, exp +6.20, PF 1.25, p=0.008
  * v2 ``zone/H4/london_ny_overlap`` n= 221, exp +11.05, PF 1.51, p=0.006

A short-lived v3 experiment switched to ``detect_qualified_zones`` and added
a quality gate; that destroyed the edge (1041 → 596 trades, +6.20 → -3.42 exp)
because the qualified detector produces a different zone universe. v3.1
reverted the source.

A second v3.1 experiment added a re-count of revisits/fill-pct at signal time
(``_causal_depletion``); this was algorithmically O(N²) on H1 (62k bars × ~5k
zones = ~5 minutes per cell) AND redundant with the first-touch gate (which
already enforces revisits=0 at entry). v3.2 drops the depletion math.

What v3.2 actually changes vs v2:

1. **Tighter stop** option — defaults preserve v2 (``stop_atr_mult=0.5``)
   but the knob is now exposed.
2. **Structural TP** option — when ``target_via_structure=True`` targets
   the nearest opposite recent swing (causal). Default OFF to preserve the
   v2 RR=1.5 behaviour.

Causality contract: ``fresh_zones(at_index=i)`` already honours
``mitigated_bar_index < i``. The first-touch scan reads bars
``[created+5, i)`` strictly in the past.
"""
from __future__ import annotations

from typing import Optional

from agent.alphas.base import Alpha, AlphaContext, AlphaSignal
from agent.alphas.concepts._htf import HTFBias, htf_bias_at
from agent.config import Config
from agent.detectors.zones import fresh_zones
from agent.types import Bar, Direction, Zone


def _has_touched_before(
    zone: Zone, bars: list[Bar], up_to_index: int,
) -> bool:
    """True if any bar in ``[created+5, up_to_index)`` already touched the
    zone. The +5 skips the impulse departure. Used as a "drop unless this is
    the first touch" guard at the call site."""
    start = zone.created_bar_index + 5
    for j in range(start, up_to_index):
        b = bars[j]
        if b.low <= zone.top and b.high >= zone.bottom:
            return True
    return False


def _structural_tp(
    bars: list[Bar], swings, at_index: int, direction: Direction,
    *, lookahead: int = 200,
) -> Optional[float]:
    """Most recent opposite-side swing within the past ``lookahead`` bars."""
    if not swings:
        return None
    price = bars[at_index].close
    earliest = at_index - lookahead
    candidates = []
    for s in swings:
        if s.bar_index >= at_index or s.bar_index < earliest:
            continue
        if direction == Direction.LONG and s.is_high and s.price > price:
            candidates.append(s)
        elif direction == Direction.SHORT and (not s.is_high) and s.price < price:
            candidates.append(s)
    if not candidates:
        return None
    if direction == Direction.LONG:
        return min(candidates, key=lambda s: s.price).price
    return max(candidates, key=lambda s: s.price).price


class SupplyDemandAlpha(Alpha):
    name = "zone"
    description = "v2 zone source + causal depletion + optional structural TP"

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        name: str = "zone",
        max_age_bars: int = 500,
        stop_atr_mult: float = 0.5,
        target_rr: float = 1.5,
        target_via_structure: bool = False,
        structural_lookback: int = 200,
        min_structural_rr: float = 1.0,
        htf_align: str | None = None,
        htf_align_mode: str = "with",  # "with" or "against"
        htf_lookback: int = 5,
        htf_min_move_pips: float = 30.0,
    ) -> None:
        """
        ``htf_align`` is the alignment-filter switch:
          * ``None`` (default) — no HTF filter, v3.2 behaviour.
          * a TF string ("D1", "H4", …) — gate fires when ``htf_bias_at``
            on that TF agrees with ``htf_align_mode``:

              - ``"with"``     — require bias to match zone direction
              - ``"against"``  — require bias to OPPOSE zone direction
                (counter-trend fade — the actual edge profile for zones)

            NEUTRAL bias blocks both modes ("no read = no trade").
        """
        self.name = name
        self.cfg = cfg
        self.max_age_bars = max_age_bars
        self.stop_atr_mult = stop_atr_mult
        self.target_rr = target_rr
        self.target_via_structure = target_via_structure
        self.structural_lookback = structural_lookback
        self.min_structural_rr = min_structural_rr
        if htf_align_mode not in {"with", "against"}:
            raise ValueError(f"htf_align_mode must be 'with' or 'against', got {htf_align_mode!r}")
        self.htf_align = htf_align
        self.htf_align_mode = htf_align_mode
        self.htf_lookback = htf_lookback
        self.htf_min_move_pips = htf_min_move_pips

    def signal(self, actx: AlphaContext, i: int) -> Optional[AlphaSignal]:
        bars = actx.bars
        bar = bars[i]
        atr = actx.ctx.atr_by_index.get(i, 0.0)
        if atr <= 0:
            return None

        fresh = fresh_zones(actx.ctx.zones, i, max_age_bars=self.max_age_bars)
        if not fresh:
            return None

        bias: HTFBias | None = None
        if self.htf_align is not None:
            bias = htf_bias_at(
                bars, i, htf=self.htf_align,
                htf_lookback=self.htf_lookback,
                min_move_pips=self.htf_min_move_pips,
            )

        for zone in reversed(fresh):
            if not (bar.low <= zone.top and bar.high >= zone.bottom):
                continue
            if _has_touched_before(zone, bars, i):
                continue
            if bias is not None:
                ok = (bias.matches(zone.direction) if self.htf_align_mode == "with"
                      else bias.opposes(zone.direction))
                if not ok:
                    continue

            atr_buf = self.stop_atr_mult * atr

            if zone.direction == Direction.LONG:
                entry = max(bar.close, zone.bottom)
                stop = zone.bottom - atr_buf
                if not (stop < entry):
                    continue
                risk = entry - stop

                tp = None
                if self.target_via_structure:
                    structural = _structural_tp(
                        bars, actx.ctx.swings, i, Direction.LONG,
                        lookahead=self.structural_lookback,
                    )
                    if structural is not None and (structural - entry) >= self.min_structural_rr * risk:
                        tp = structural
                if tp is None:
                    tp = entry + self.target_rr * risk

                return AlphaSignal(
                    direction=Direction.LONG, entry=entry, stop=stop,
                    take_profit=tp, reason="zone_demand",
                    conviction=0.65,
                )
            else:
                entry = min(bar.close, zone.top)
                stop = zone.top + atr_buf
                if not (stop > entry):
                    continue
                risk = stop - entry

                tp = None
                if self.target_via_structure:
                    structural = _structural_tp(
                        bars, actx.ctx.swings, i, Direction.SHORT,
                        lookahead=self.structural_lookback,
                    )
                    if structural is not None and (entry - structural) >= self.min_structural_rr * risk:
                        tp = structural
                if tp is None:
                    tp = entry - self.target_rr * risk

                return AlphaSignal(
                    direction=Direction.SHORT, entry=entry, stop=stop,
                    take_profit=tp, reason="zone_supply",
                    conviction=0.65,
                )
        return None
