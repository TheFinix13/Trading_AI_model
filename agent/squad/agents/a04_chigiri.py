"""A4 -- Hyoma Chigiri v1 (`chigiri_hyoma`) -- ATR breakout speedster.

Chigiri is the speedster (roster `05-agent-roster-v0.md` section 3.4,
doctrine `06-blue-lock-doctrine.md` section 3.1 -- "speed once
committed"). His canonical weapon is range-break + ATR vol-expansion
momentum. The empirical prior (audit `2026-06-24_E001-E007_audit.md`
section 2.7) is a **negative prior at the retest layer** -- E007 found
0/12 cells alive on impulse-origin retest at Stage 1. The roster
explicitly warns:

> Chigiri's edge must therefore live in the *continuation* of the
> impulse, not in the retest of the origin zone. Up-impulse cells were
> +4 to +14 pips on EURUSD 2015-2021 vs negative H4 down-impulse cells
> -- a symmetric-long-short warning Chigiri must respect at the spec
> level.

Chigiri v1 takes the **continuation** read: M-bar range break on H4
with ATR confirmation. New primitive -- NOT a wrap of the production
zone cell. The agent has no production-repo dependency for its inner
calculation (uses pure-Python OHLC history from `prepare()`).

Signal predicate (locked Φ4.1 v1)
---------------------------------

For bar `i` on a prepared symbol, Chigiri fires iff:

1. `close[i] > max(high[i-N..i-1])` (LONG breakout)   OR
   `close[i] < min(low[i-N..i-1])`  (SHORT breakout)
   with `N = CHIGIRI_V1_BREAKOUT_LOOKBACK = 20` bars.
2. Breakout magnitude (`|close[i] - broken_level|`) ≥
   `CHIGIRI_V1_BREAKOUT_ATR_MULT × ATR_14`.
3. ATR_14[i] > median(ATR_14[i-80..i-1]) -- vol expansion regime.

Conviction (final = base + boost, cap 1.0):

* `base = CHIGIRI_V1_BASE_CONVICTION = 0.70`
* `boost = min(0.25, 0.10 × (magnitude / ATR))` -- magnitude z-score
  proxy, bounded so a single huge bar can't reach 1.0 deterministically.

The base of 0.70 sits exactly at Nagi's `NAGI_V1_CONFIDENCE_FLOOR` so a
clean breakout qualifies as a Nagi peer. The vol-expansion regime
predicate keeps Chigiri honest -- E007's negative prior was on retest,
not on continuation, but we still gate the firing on a positive vol
state to avoid whipsawing in chop.

Trade plan (intend):

* entry = close[i] (the breakout bar's close; the harness opens at the
  next bar's open per its fill model).
* stop = broken_level ∓ 0.25 × ATR  (LONG: broken_level − 0.25 ATR;
  SHORT: broken_level + 0.25 ATR).
* tp   = entry ± 1.5R (matches the squad's standard target_rr=1.5).

Symbols
-------

EURUSD + GBPUSD H4 -- per roster section 3.4 the canonical home is M15
but Φ4 v1 ran everything on H4. v1 ships H4 to align with the squad
home-TF schedule; M15 deployment is a v2 cadence change.

Symbols are intentionally EURUSD + GBPUSD (not USDCAD): Barou owns
USDCAD end-to-end and Chigiri must not contest it.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from agent.squad.ledger import ThoughtLedger
from agent.squad.provenance_pips import (
    regime_fit_from_atr,
    stamp_provenance_pips,
)
from agent.squad.workspace import (
    WorkspaceSnapshot,
)
from agent.squad.striker import BaseStriker
from agent.squad.types import (
    SCHEMA_VERSION,
    AgentProposal,
    CanonRole,
    Coordinate,
    LadderRung,
    MarketState,
    Thought,
    ThoughtRead,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked Φ4.1 v1 parameters.
# ---------------------------------------------------------------------------
CHIGIRI_V1_BREAKOUT_LOOKBACK: int = 20    # N-bar range
CHIGIRI_V1_ATR_PERIOD: int = 14
CHIGIRI_V1_ATR_VOL_LOOKBACK: int = 80     # median ATR window for vol regime
CHIGIRI_V1_BREAKOUT_ATR_MULT: float = 0.50
CHIGIRI_V1_STOP_ATR_MULT: float = 0.25
CHIGIRI_V1_TARGET_RR: float = 1.5
CHIGIRI_V1_BASE_CONVICTION: float = 0.70
CHIGIRI_V1_MAX_MAGNITUDE_BOOST: float = 0.25
CHIGIRI_V1_MAGNITUDE_BOOST_PER_ATR: float = 0.10
CHIGIRI_V1_CONV_CAP: float = 1.0

# Phase V-a (2026-07-02, NULL RESULT): regime-specialist thresholds.
# Originally designed as a rationale-flagged tier promotion (see G7
# PROTOCOL sec 11.9). Walk-forward-post-V measured only 1 tick flip
# in 992 (delta moved +0.002 in the WRONG direction), so the tier
# promotion was reverted (see intend() below). The thresholds are
# retained here because:
#   1. The ratios (mag/atr, atr/median) are stamped into rationale
#      for future re-analysis (a future Phase V-iterate can look at
#      the distribution of ratios vs shadow outcomes to design a
#      better mechanic).
#   2. Regression tests exercise the boolean specialist bit, so the
#      thresholds must remain stable for test reproducibility.
#
# - CHIGIRI_V1_REGIME_MIN_MAG_ATR: minimum breakout magnitude in
#   ATR units. Routine breakout = 0.5 ATR; specialist = >= 1.5 ATR.
# - CHIGIRI_V1_REGIME_ATR_MULT: minimum ATR / median-ATR ratio.
#   Chigiri already only fires when ATR > median (vol_expansion);
#   specialist tightens this to >= 1.5 x median.
CHIGIRI_V1_REGIME_MIN_MAG_ATR: float = 1.5
CHIGIRI_V1_REGIME_ATR_MULT: float = 1.5
CHIGIRI_V1_WARMUP_BARS: int = (
    CHIGIRI_V1_BREAKOUT_LOOKBACK + CHIGIRI_V1_ATR_VOL_LOOKBACK + 5
)

CHIGIRI_V1_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD")

CHIGIRI_V1_CANON_ROLE = CanonRole(
    canon_player="chigiri_hyoma",
    weapon="speed_atr_breakout_continuation",
    ego=0.80,
    target_hold_hours=24.0,
    narrative_voice="speed_committed_breakaway",
)


@dataclass
class _PreparedSeries:
    """Per-symbol cache of OHLC + precomputed ATR series."""

    bars: list                 # list of objects with .time, .open, .high, .low, .close
    index_by_ts: dict[datetime, int]
    atr: list[float]           # ATR_14 series (same length as bars; NaN where < period)


def _wilder_atr(bars: list, period: int) -> list[float]:
    """Wilder's ATR via EWM-equivalent recurrence.

    Mirrors `conflab/indicators.py:atr` semantics (alpha=1/period). Pure
    Python -- no pandas/numpy dependency -- to keep this agent free of
    production-repo coupling.
    """
    n = len(bars)
    out = [float("nan")] * n
    if n == 0:
        return out
    # True range series.
    tr: list[float] = [0.0] * n
    for i in range(n):
        h = float(bars[i].high)
        l = float(bars[i].low)
        if i == 0:
            tr[i] = h - l
            continue
        pc = float(bars[i - 1].close)
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    # Wilder's smoothing (alpha = 1/period, no adjust). First "settled"
    # value at index period-1.
    if n < period:
        return out
    alpha = 1.0 / float(period)
    seed = sum(tr[:period]) / float(period)
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        cur = alpha * tr[i] + (1.0 - alpha) * prev
        out[i] = cur
        prev = cur
    return out


class A4ChigiriV1(BaseStriker):
    """A4 Chigiri v1 -- ATR breakout continuation striker.

    Public surface (engine):
      * `observe(market, ledger)` -- always emits a Thought; when the
        breakout predicate fires AND vol-expansion regime is on,
        emits a Coordinate at base + magnitude_boost conviction.
      * `intend(market, my_recent_thought)` -- H4 close only on EURUSD
        / GBPUSD; emits a Proposal whose entry=close, stop = broken
        level +/- 0.25 ATR, tp at 1.5R.

    Harness API:
      * `prepare(symbol, bars)` -- pre-load OHLC bars + compute ATR.
    """

    def __init__(
        self,
        agent_id: str = "chigiri_hyoma",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or CHIGIRI_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(CHIGIRI_V1_SYMBOLS),
            playstyle="speed_momentum",
            tier=2,
        )
        self._prepared: dict[str, _PreparedSeries] = {}

    # ------------------------------------------------------------------
    # Harness API
    # ------------------------------------------------------------------

    def prepare(self, symbol: str, bars: list) -> None:
        if symbol not in self.symbols:
            log.info(
                "A4ChigiriV1.prepare(%s) ignored -- not in symbol whitelist %s",
                symbol, self.symbols,
            )
            return
        atr = _wilder_atr(bars, CHIGIRI_V1_ATR_PERIOD)
        index_by_ts = {b.time: i for i, b in enumerate(bars)}
        self._prepared[symbol] = _PreparedSeries(
            bars=list(bars), index_by_ts=index_by_ts, atr=atr,
        )
        log.info(
            "A4ChigiriV1 prepared %s: %d bars, ATR ready", symbol, len(bars),
        )

    @property
    def prepared_symbols(self) -> tuple[str, ...]:
        return tuple(self._prepared.keys())

    # ------------------------------------------------------------------
    # BlueLockStriker contract
    # ------------------------------------------------------------------

    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought:
        if market.symbol not in self.symbols:
            return self._abstain_thought(market, reason="off_symbol")

        prep = self._prepared.get(market.symbol)
        if prep is None:
            return self._abstain_thought(market, reason="unprepared")

        i = prep.index_by_ts.get(market.as_of)
        if i is None:
            return self._abstain_thought(market, reason="timestamp_miss")

        sig = self._detect_breakout(prep, i)
        if sig is None:
            return self._observation_only(market=market, reason="no_breakout")

        direction = sig["direction"]
        magnitude = float(sig["magnitude"])
        atr_at = float(sig["atr"])
        boost = min(
            CHIGIRI_V1_MAX_MAGNITUDE_BOOST,
            CHIGIRI_V1_MAGNITUDE_BOOST_PER_ATR * (magnitude / max(atr_at, 1e-9)),
        )
        final_conv = min(
            CHIGIRI_V1_CONV_CAP, CHIGIRI_V1_BASE_CONVICTION + boost,
        )
        coord = _coordinate_from_breakout(
            sig=sig, agent_id=self.agent_id, symbol=market.symbol,
            as_of=market.as_of, home_tf=self.home_tf,
            target_hold_hours=self.canon_role.target_hold_hours,
            conviction=final_conv,
        )
        # Dispersion-r2 (2026-07-14): volatility provenance for
        # bar-less borrowers (Nagi) -- see doctrine §4.1a amendment.
        stamp_provenance_pips(coord.rationale, bars=prep.bars, i=i)
        tags = [
            "canon:chigiri",
            "weapon:speed",
            "chigiri_speed_breakout",
            "breakout_continuation",
            "momentum",
            f"direction:{direction}",
            f"breakout_level:{sig['broken_level']:.5f}",
            "regime:vol_expansion",
        ]
        narrative = (
            f"[chigiri v1] {market.symbol} H4 close {market.as_of}: "
            f"{direction} breakout of "
            f"{CHIGIRI_V1_BREAKOUT_LOOKBACK}-bar range; "
            f"magnitude={magnitude:.5f} ({magnitude / atr_at:.2f} ATR); "
            f"ATR={atr_at:.5f}; conv "
            f"{CHIGIRI_V1_BASE_CONVICTION:.2f}+{boost:.2f}={final_conv:.2f}."
        )
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=narrative,
            tags=tags,
            confidence_in_thought=float(final_conv),
            expected_action=f"{direction}_on_H4_close_breakout",
            coordinate=coord,
            decision_horizon=market.as_of,
            ttl_ticks=6,
            references=[],
            read=ThoughtRead(
                signal_family="breakout",
                direction_bias=direction,  # type: ignore[arg-type]
                regime_read="vol_expansion",
                expected_stop_pips=None,   # ATR-scaled, no fixed stop pre-intend
                expected_r=None,
                driving_evidence=(
                    "chigiri_speed_breakout",
                    "breakout_continuation",
                    "momentum",
                    f"broken_level:{sig['broken_level']:.5f}",
                ),
            ),
        )

    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
        *,
        workspace: WorkspaceSnapshot | None = None,
        **_kwargs: object,
    ) -> AgentProposal | None:
        # Phase O (2026-07-01): Chigiri reads Isagi's latest thought via
        # the F21 workspace to log momentum-confluence: does the anchor's
        # zone frame agree with Chigiri's ATR-breakout direction?
        # Diagnostic-only for v1 (the breakout gate is local); chemistry
        # evidence flows into rationale for G7 C4.
        if market.timeframe != self.home_tf:
            return None
        if market.symbol not in self.symbols:
            return None
        if my_recent_thought.coordinate is None:
            return None
        if "chigiri_speed_breakout" not in my_recent_thought.tags:
            return None
        prep = self._prepared.get(market.symbol)
        if prep is None:
            return None
        i = prep.index_by_ts.get(market.as_of)
        if i is None:
            return None

        rationale = my_recent_thought.coordinate.rationale
        direction = my_recent_thought.coordinate.direction_bias
        if direction not in ("long", "short"):
            return None
        try:
            entry = float(rationale["entry"])
            stop = float(rationale["stop"])
            tp = float(rationale["take_profit"])
        except (KeyError, TypeError, ValueError):
            return None

        ladder = [LadderRung(price=float(tp), fraction=1.0)]
        horizon = market.as_of + timedelta(
            hours=float(self.canon_role.target_hold_hours),
        )
        # F21 workspace read -- Isagi momentum confluence.
        isagi_momentum_agree: bool | None = None
        isagi_frame_direction: str | None = None
        if workspace is not None:
            latest_by_agent = workspace.latest_by_agent(symbol=market.symbol)
            isagi_t = latest_by_agent.get("isagi_yoichi")
            if isagi_t is not None and isagi_t.coordinate is not None:
                isagi_frame_direction = str(isagi_t.coordinate.direction_bias)
                if isagi_frame_direction in ("long", "short"):
                    isagi_momentum_agree = (isagi_frame_direction == direction)

        # Phase V-a: regime-specialist promotion. Chigiri's breakout
        # detector already returns ``magnitude`` (pips-space distance
        # past the broken range) and ``atr`` + ``atr_median_vol``.
        # Re-run it here so we can score both specialist conditions
        # without piping extra state through my_recent_thought.
        sig_verify = self._detect_breakout(prep, i)
        regime_specialist = False
        mag_atr_ratio: float | None = None
        atr_expansion_ratio: float | None = None
        if sig_verify is not None:
            atr_at = float(sig_verify.get("atr", 0.0))
            atr_median = float(sig_verify.get("atr_median_vol", 0.0))
            magnitude = float(sig_verify.get("magnitude", 0.0))
            if atr_at > 0.0:
                mag_atr_ratio = magnitude / atr_at
            if atr_median > 0.0:
                atr_expansion_ratio = atr_at / atr_median
            if (
                mag_atr_ratio is not None
                and atr_expansion_ratio is not None
                and mag_atr_ratio >= CHIGIRI_V1_REGIME_MIN_MAG_ATR
                and atr_expansion_ratio >= CHIGIRI_V1_REGIME_ATR_MULT
            ):
                regime_specialist = True

        proposal_rationale: dict[str, Any] = {
            "wrapped": "internal:atr_breakout_continuation_v1",
            "breakout_lookback": CHIGIRI_V1_BREAKOUT_LOOKBACK,
            "atr_period": CHIGIRI_V1_ATR_PERIOD,
            "breakout_atr_mult": CHIGIRI_V1_BREAKOUT_ATR_MULT,
            "stop_atr_mult": CHIGIRI_V1_STOP_ATR_MULT,
            "target_rr": CHIGIRI_V1_TARGET_RR,
            "signal_reason": "chigiri_speed_breakout_continuation",
            "bar_index": int(i),
            "base_conviction": CHIGIRI_V1_BASE_CONVICTION,
            "final_conviction": float(my_recent_thought.confidence_in_thought),
            "isagi_frame_direction": isagi_frame_direction,
            "isagi_momentum_agree": isagi_momentum_agree,
            # Phase V-a wiring (DIAGNOSTIC ONLY -- see postmortem below):
            # report the specialist score whether or not it fires, for
            # audit + future walk-forward attribution. Kept as regression
            # guard on the ratio arithmetic; NO effect on aggregator
            # routing under the null-result configuration (see G7
            # PROTOCOL sec 11.9-postmortem 2026-07-02).
            "chigiri_regime_specialist": bool(regime_specialist),
            "chigiri_mag_atr_ratio": mag_atr_ratio,
            "chigiri_atr_expansion_ratio": atr_expansion_ratio,
            "chigiri_regime_min_mag_atr": CHIGIRI_V1_REGIME_MIN_MAG_ATR,
            "chigiri_regime_atr_mult": CHIGIRI_V1_REGIME_ATR_MULT,
            "doctrine_ref": (
                "06-blue-lock-doctrine.md sec 3.1 (speed) + G7 PROTOCOL "
                "sec 11.9 Phase V-a null result (2026-07-02) -- specialist "
                "bit stamped for audit; tier promotion reverted"
            ),
            "empirical_prior": (
                "E007 0/12 alive on impulse-origin RETEST; Chigiri v1 "
                "fires on CONTINUATION, not retest"
            ),
        }
        # Phase V-a null result (walk-forward-post-V 2026-07-02):
        # ``_effective_tier=1`` promotion was reverted because the delta
        # only moved +0.002 in the WRONG direction (target: >= -0.03
        # movement toward 0). Root cause: raw conviction gap between
        # Chigiri (~0.70--0.85) and Isagi (~0.85--1.00) exceeds the
        # TIER_BIAS penalty, so promoting the effective tier alone does
        # not tip the aggregator sort. Postmortem in PROTOCOL sec 11.9.
        stamp_provenance_pips(proposal_rationale, bars=prep.bars, i=i)
        return AgentProposal(
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            source_thought_id=my_recent_thought.thought_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            direction=direction,
            entry=float(entry),
            stop=float(stop),
            ladder=ladder,
            conviction=float(my_recent_thought.confidence_in_thought),
            regime_fit=regime_fit_from_atr(prep.bars, i),
            valid_until=horizon,
            rationale=proposal_rationale,
            agent_tier=int(self.tier),
        )

    # ------------------------------------------------------------------
    # Breakout detector (pure)
    # ------------------------------------------------------------------

    def _detect_breakout(
        self, prep: _PreparedSeries, i: int,
    ) -> dict[str, Any] | None:
        """Return a signal dict or None.

        Predicate (all conditions must hold at bar `i`):
          1. i >= warmup
          2. ATR_14[i] finite and > 0
          3. ATR_14[i] > median of ATR_14[i-vol_lookback..i-1]
          4. close[i] > max(high[i-N..i-1])  (long)  OR
             close[i] < min(low[i-N..i-1])   (short)
          5. |close[i] - broken_level| >= breakout_atr_mult * ATR_14[i]
        """
        if i < CHIGIRI_V1_WARMUP_BARS:
            return None
        bars = prep.bars
        atr_series = prep.atr
        atr_at = atr_series[i]
        if not (atr_at == atr_at) or atr_at <= 0.0:   # NaN check + sanity
            return None
        # Vol-expansion regime: current ATR above the trailing median.
        vol_window_lo = max(0, i - CHIGIRI_V1_ATR_VOL_LOOKBACK)
        atr_history = [
            atr_series[k] for k in range(vol_window_lo, i)
            if atr_series[k] == atr_series[k]
        ]
        if len(atr_history) < CHIGIRI_V1_ATR_VOL_LOOKBACK // 2:
            return None
        atr_median = statistics.median(atr_history)
        if atr_at <= atr_median:
            return None

        lookback_lo = i - CHIGIRI_V1_BREAKOUT_LOOKBACK
        recent_high = max(float(bars[k].high) for k in range(lookback_lo, i))
        recent_low = min(float(bars[k].low) for k in range(lookback_lo, i))
        close_i = float(bars[i].close)
        threshold = CHIGIRI_V1_BREAKOUT_ATR_MULT * atr_at

        if close_i - recent_high >= threshold:
            direction = "long"
            broken_level = recent_high
            magnitude = close_i - recent_high
        elif recent_low - close_i >= threshold:
            direction = "short"
            broken_level = recent_low
            magnitude = recent_low - close_i
        else:
            return None

        if direction == "long":
            stop = broken_level - CHIGIRI_V1_STOP_ATR_MULT * atr_at
            risk = close_i - stop
            tp = close_i + CHIGIRI_V1_TARGET_RR * risk
        else:
            stop = broken_level + CHIGIRI_V1_STOP_ATR_MULT * atr_at
            risk = stop - close_i
            tp = close_i - CHIGIRI_V1_TARGET_RR * risk
        if risk <= 0:
            return None
        return {
            "direction": direction,
            "broken_level": float(broken_level),
            "magnitude": float(magnitude),
            "atr": float(atr_at),
            "atr_median_vol": float(atr_median),
            "close": float(close_i),
            "entry": float(close_i),
            "stop": float(stop),
            "take_profit": float(tp),
            "risk_price": float(risk),
            "recent_high": float(recent_high),
            "recent_low": float(recent_low),
            "bar_index": int(i),
        }

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _observation_only(
        self, *, market: MarketState, reason: str,
    ) -> Thought:
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[chigiri v1] {market.symbol} {market.timeframe} @ "
                f"{market.as_of} -- no breakout ({reason}); standing by."
            ),
            tags=[
                "canon:chigiri",
                "weapon:speed",
                "chigiri_observation_clean",
                f"chigiri_reason:{reason}",
            ],
            confidence_in_thought=0.0,
            expected_action="wait",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=1,
            references=[],
        )

    def _abstain_thought(self, market: MarketState, *, reason: str) -> Thought:
        tags = [
            "canon:chigiri",
            "weapon:speed",
            "chigiri_abstain",
            f"abstain_reason:{reason}",
        ]
        if reason == "off_symbol":
            tags.append("chigiri_abstain_symbol")
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[chigiri v1] {market.symbol} {market.timeframe} @ "
                f"{market.as_of} -- abstain ({reason})."
            ),
            tags=tags,
            confidence_in_thought=0.0,
            expected_action="wait",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=1,
            references=[],
        )


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------

def _coordinate_from_breakout(
    *,
    sig: dict[str, Any],
    agent_id: str,
    symbol: str,
    as_of: datetime,
    home_tf: str,
    target_hold_hours: float,
    conviction: float,
) -> Coordinate:
    direction = sig["direction"]
    risk = float(sig["risk_price"])
    band_half = max(risk, 0.0001)
    entry = float(sig["entry"])
    return Coordinate(
        agent_id=agent_id,
        symbol=symbol,
        price_lo=float(entry) - band_half,
        price_hi=float(entry) + band_half,
        time_start=as_of,
        time_end=as_of + timedelta(hours=float(target_hold_hours)),
        vol_band=(1.2, float("inf")),
        regime_predicate="chigiri_speed_breakout_continuation",
        expected_strength=float(conviction),
        direction_bias=direction,
        rationale={
            "entry": float(sig["entry"]),
            "stop": float(sig["stop"]),
            "take_profit": float(sig["take_profit"]),
            "broken_level": float(sig["broken_level"]),
            "magnitude": float(sig["magnitude"]),
            "atr": float(sig["atr"]),
            "atr_median_vol": float(sig["atr_median_vol"]),
            "signal_reason": "chigiri_speed_breakout_continuation",
            "home_tf": home_tf,
            "conviction_final": float(conviction),
        },
    )


# Backwards-compatible alias for roster loaders.
ChigiriHyoma = A4ChigiriV1
