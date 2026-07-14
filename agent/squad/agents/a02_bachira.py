"""A2 -- Meguru Bachira v1 (`bachira_meguru`) -- rebel baseline-zone striker.

Bachira v1 is the **rebel** of the squad (roster `05-agent-roster-v0.md`
section 3.2, doctrine `06-blue-lock-doctrine.md` section 3.1 -- the
"monstrous dribble" character). Where Isagi v1 only fires a zone touch
when D1 is COUNTER to the trade direction (`htf_align_mode="against"`),
Bachira v1 takes the SAME baseline zone primitive (`SupplyDemandAlpha`)
but **rebels against Isagi's D1 gate**: he fires on every baseline zone
touch on EURUSD / GBPUSD / USDCAD, with no D1-trend gate at all
(`htf_align=None`).

This is the production-grade "rebel duo" alternate read of the same
chart: Isagi sees the zone as a fade against the higher TF; Bachira
sees it as a fade *period* (whatever the higher TF says). Same primitive,
different gating -- like Barou's USDCAD specialisation, but extended to
EURUSD + GBPUSD so Bachira can play alongside Isagi on Isagi's home
ground.

Φ4.1 deliberate design choices
------------------------------

* **Symbol overlap with Isagi.** Bachira shares EURUSD + GBPUSD + USDCAD
  with Isagi by design. The Φ4 squad gate FAILED partly because Nagi's
  chemical-reaction predicate needs **≥ 2 distinct tradable peers on
  the same symbol at the same tick** -- and the Φ4 MVP only had Isagi
  trading EURUSD. Bachira gives Nagi a second EURUSD peer.
* **Rebel conviction lift.** Production `SupplyDemandAlpha` emits a
  base conviction of 0.65 on a zone touch. That is BELOW Nagi's
  `NAGI_V1_CONFIDENCE_FLOOR=0.7` -- so Isagi alone can never qualify as
  a Nagi peer. Bachira applies a fixed +0.10 *rebel lift* (mirrors the
  Barou +0.10 devour pattern) when the baseline zone fires WITH a
  recent (within 3-bar) opposite-direction swing -- the "I'll dribble
  through your defence" trigger. Final conviction lands at 0.75, just
  above the floor.
* **Tag overlap with Isagi.** Bachira's tag set includes the explicit
  marker `zone_setup_h4` plus a `bachira_rebel` direction tag and the
  inherited `signal_reason:zone_*` tag from the production alpha. When
  Bachira fires LONG on the same EURUSD bar where Isagi fires LONG,
  the (Isagi, Bachira) pair gives Nagi at least one shared zone tag
  plus the direction-match needed to clear the F11/F13 predicate.

Empirical prior (`audits/2026-06-24_E001-E007_audit.md` sections 2.1,
2.6, 4.3): standalone pattern detectors were KILLED in E001 / E006.
Bachira's edge **must** come from pattern × HTF combination, not from
patterns alone. The v1 implementation here uses the production baseline
zone as the "pattern" primitive and the recent-opposite-swing check as
a coarse stand-in for the canonical pattern-strength × HTF-alignment
score; a v2 wiring would plug `conflab/detectors_chartpatterns.py`
proper.

Cross-repo import is bracketed by
the production-repo bootstrap (now a no-op in this trading-repo port); same contract as
A1 Isagi v1 and A7 Barou v1.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from agent.squad.ledger import ThoughtLedger
from agent.squad.provenance_pips import (
    expected_r_from_prices,
    regime_fit_from_atr,
    stamp_provenance_pips,
    stop_pips_from_prices,
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

# F21 peer-confluence chemistry (doctrine section 4.1a). Bachira reads
# Isagi's Thoughts at tick T-1 on the same symbol; if Isagi's most-recent
# Thought carries a real fired zone signal (non-null coordinate) with
# matching direction, Bachira's rebel lift stacks an additional +0.05
# conviction. Flagship "Isagi -> Bachira TF chemistry" example --
# Isagi identifies zone confluence, Bachira on the same TF confirms
# with extra weight.
#
# Isagi v1 emits ``expected_action`` in ``{"long_on_H4_close",
# "short_on_H4_close"}`` ONLY when a real zone signal fires (waiting
# Thoughts emit ``"wait"``). Bachira's own signal ``direction`` is
# ``"long"``/``"short"``; the peer-match is a string-prefix check.
BACHIRA_PEER_CONFLUENCE_LIFT = 0.05
BACHIRA_PEER_PARTNER_ID = "isagi_yoichi"

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked Φ4.1 v1 parameters.
# ---------------------------------------------------------------------------
BACHIRA_V1_PARAMS: dict[str, Any] = {
    "name": "A2_bachira_v1_rebel_baseline_zone",
    "htf_align": None,        # the rebellion: no D1 gate
    "target_rr": 1.5,
}

BACHIRA_V1_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")

BACHIRA_V1_REBEL_LIFT: float = 0.10        # +0.10 to base conviction
BACHIRA_V1_REBEL_LOOKBACK: int = 3         # bars back for opposite swing
BACHIRA_V1_CONV_CAP: float = 1.0

BACHIRA_V1_CANON_ROLE = CanonRole(
    canon_player="bachira_meguru",
    weapon="monstrous_dribble_rebel_baseline_zone",
    ego=0.85,
    target_hold_hours=24.0,
    narrative_voice="rebel_dribble_pattern_geometry",
)


@dataclass
class _PreparedSeries:
    """Per-symbol cache populated by `prepare()`."""

    bars: list
    ctx: Any
    index_by_ts: dict[datetime, int]


class A2BachiraV1(BaseStriker):
    """A2 Bachira v1 -- rebel baseline-zone striker on the major triad.

    Public surface (engine):
      * `observe(market, ledger)` -- always emits a Thought; conviction
        rises by +0.10 when the recent-bar window contains an opposite-
        direction swing relative to Bachira's signal direction (the
        "dribble through" trigger).
      * `intend(market, my_recent_thought)` -- H4 close only, on any of
        Bachira's whitelist symbols.

    Harness API (kept identical to A7 Barou v1):
      * `prepare(symbol, bars)` -- pre-load production Bar list + ctx.
      * `inner_signal_at(symbol, i)` -- direct passthrough to
        `SupplyDemandAlpha.signal` for proof-of-equivalence tests.
    """

    def __init__(
        self,
        agent_id: str = "bachira_meguru",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
        *,
        production_cfg: Any | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or BACHIRA_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(BACHIRA_V1_SYMBOLS),
            playstyle="rebel_tight",
            tier=2,
        )
        # production alphas live in this repo; no PYTHONPATH bootstrap needed
        from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha  # noqa: E402
        from agent.config import load_config  # noqa: E402

        self._cfg = production_cfg if production_cfg is not None else load_config()
        self._inner = SupplyDemandAlpha(cfg=self._cfg, **BACHIRA_V1_PARAMS)
        self._prepared: dict[str, _PreparedSeries] = {}

    # ------------------------------------------------------------------
    # Harness API
    # ------------------------------------------------------------------

    def prepare(self, symbol: str, bars: list) -> None:
        if symbol not in self.symbols:
            log.info(
                "A2BachiraV1.prepare(%s) ignored -- not in symbol whitelist %s",
                symbol, self.symbols,
            )
            return
        # production alphas live in this repo; no PYTHONPATH bootstrap needed
        from agent.rules.engine import precompute  # noqa: E402

        ctx = precompute(list(bars), self._cfg)
        index_by_ts = {b.time: i for i, b in enumerate(bars)}
        self._prepared[symbol] = _PreparedSeries(
            bars=list(bars), ctx=ctx, index_by_ts=index_by_ts,
        )
        log.info(
            "A2BachiraV1 prepared %s: %d bars, %d zones, %d swings",
            symbol, len(bars), len(ctx.zones), len(ctx.swings),
        )

    def inner_signal_at(self, symbol: str, i: int):
        prep = self._prepared.get(symbol)
        if prep is None:
            return None
        from agent.alphas.base import AlphaContext  # noqa: E402
        actx = AlphaContext(bars=prep.bars, ctx=prep.ctx, cfg=self._cfg)
        return self._inner.signal(actx, i)

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

        sig = self.inner_signal_at(market.symbol, i)
        if sig is None:
            return self._abstain_thought(market, reason="no_zone_touch")

        direction = sig.direction.value
        base_conv = float(sig.conviction)
        rebel_fired = self._has_opposite_recent_swing(
            bars=prep.bars, i=i, direction=direction,
        )
        final_conv = min(
            BACHIRA_V1_CONV_CAP,
            base_conv + (BACHIRA_V1_REBEL_LIFT if rebel_fired else 0.0),
        )

        coord = _coordinate_from_signal(
            sig=sig, agent_id=self.agent_id, symbol=market.symbol,
            as_of=market.as_of, home_tf=self.home_tf,
            target_hold_hours=self.canon_role.target_hold_hours,
            conviction=final_conv,
        )
        # Dispersion-r2 (2026-07-14): volatility provenance for
        # bar-less borrowers (Nagi) -- see doctrine §4.1a amendment.
        stamp_provenance_pips(coord.rationale, bars=prep.bars, i=i)
        tags = [
            "canon:bachira",
            "weapon:rebel_dribble",
            "zone_setup_h4",
            "bachira_rebel_baseline_zone",
            f"signal_reason:{sig.reason}",
            f"direction:{direction}",
        ]
        if rebel_fired:
            tags.append("bachira_rebel_lift_applied")
        narrative = (
            f"[bachira v1] {market.symbol} H4 close {market.as_of}: "
            f"baseline-zone {direction} fade (NO D1 gate). "
            f"entry={sig.entry:.5f} stop={sig.stop:.5f} tp={sig.take_profit:.5f}; "
            f"conv {base_conv:.2f}"
            + (
                f" + rebel {BACHIRA_V1_REBEL_LIFT:.2f} = {final_conv:.2f}"
                if rebel_fired
                else " (no rebel lift; clean direction in recent swing)"
            )
        )
        stop_pips = stop_pips_from_prices(market.symbol, sig.entry, sig.stop)
        r_expected = expected_r_from_prices(sig.entry, sig.stop, sig.take_profit)
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=narrative,
            tags=tags,
            confidence_in_thought=float(final_conv),
            expected_action=f"{direction}_on_H4_close",
            coordinate=coord,
            decision_horizon=market.as_of,
            ttl_ticks=6,
            references=[],
            read=ThoughtRead(
                signal_family="pattern_rebel",
                direction_bias=direction,  # type: ignore[arg-type]
                regime_read="rebel_lift" if rebel_fired else "baseline_zone",
                expected_stop_pips=stop_pips,
                expected_r=r_expected,
                driving_evidence=(
                    "bachira_rebel_baseline_zone",
                    f"signal_reason:{sig.reason}",
                    *(("bachira_rebel_lift_applied",) if rebel_fired else ()),
                ),
            ),
        )

    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
        *,
        workspace: WorkspaceSnapshot | None = None,
    ) -> AgentProposal | None:
        if market.timeframe != self.home_tf:
            return None
        if market.symbol not in self.symbols:
            return None
        prep = self._prepared.get(market.symbol)
        if prep is None:
            return None
        i = prep.index_by_ts.get(market.as_of)
        if i is None:
            return None
        sig = self.inner_signal_at(market.symbol, i)
        if sig is None:
            return None

        direction = sig.direction.value
        # Base conviction from the observed Thought (already carries the
        # rebel lift). The F21 peer-confluence-with-Isagi bonus stacks
        # on top of it for the flagship "Isagi -> Bachira TF chemistry"
        # pattern -- Isagi identifies zone touch, Bachira confirms with
        # extra weight.
        base_conviction = float(my_recent_thought.confidence_in_thought)
        peer_confluence = self._detect_isagi_peer_confluence(
            workspace=workspace,
            symbol=market.symbol,
            direction=direction,
        )
        peer_lift = BACHIRA_PEER_CONFLUENCE_LIFT if peer_confluence else 0.0
        conviction = min(1.0, base_conviction + peer_lift)

        ladder = [LadderRung(price=float(sig.take_profit), fraction=1.0)]
        horizon = market.as_of + timedelta(
            hours=float(self.canon_role.target_hold_hours),
        )
        meta = getattr(sig, "meta", {}) or {}
        rationale: dict[str, Any] = {
            "wrapped": "agent.alphas.concepts.zone_alpha.SupplyDemandAlpha",
            "params": dict(BACHIRA_V1_PARAMS),
            "signal_reason": sig.reason,
            "htf_align": meta.get("htf_align"),  # None for Bachira
            "bar_index": int(i),
            "rebel_lift_applied": (
                "bachira_rebel_lift_applied" in my_recent_thought.tags
            ),
            "base_conviction": float(sig.conviction),
            "final_conviction": conviction,
            "peer_confluence_isagi": bool(peer_confluence),
            "peer_confluence_lift": peer_lift,
            "doctrine_ref": "06-blue-lock-doctrine.md sec 3.1 + 4.1a (F21)",
            "empirical_prior": (
                "E001/E006: standalone patterns killed -- Bachira's "
                "edge must come from pattern x HTF combination"
            ),
        }
        stamp_provenance_pips(rationale, bars=prep.bars, i=i)
        return AgentProposal(
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            source_thought_id=my_recent_thought.thought_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            direction=direction,
            entry=float(sig.entry),
            stop=float(sig.stop),
            ladder=ladder,
            conviction=float(conviction),
            regime_fit=regime_fit_from_atr(prep.bars, i),
            valid_until=horizon,
            rationale=rationale,
            agent_tier=int(self.tier),
        )

    # ------------------------------------------------------------------
    # F21 -- peer-confluence chemistry with Isagi
    # ------------------------------------------------------------------

    def _detect_isagi_peer_confluence(
        self,
        *,
        workspace: WorkspaceSnapshot | None,
        symbol: str,
        direction: str,
    ) -> bool:
        """Return True when Isagi's most-recent Thought on this symbol
        carries a fired zone signal (non-null coordinate) with matching
        directional bias.

        The workspace snapshot already filters same-tick reads (doctrine
        3.8 look-ahead guard). If Isagi is waiting (coordinate is None)
        or on a different symbol, or directions disagree, no confluence.
        """
        if workspace is None:
            return False
        latest = workspace.latest_by_agent(symbol=symbol)  # type: ignore[arg-type]
        peer = latest.get(BACHIRA_PEER_PARTNER_ID)
        if peer is None or peer.coordinate is None:
            return False
        return str(peer.coordinate.direction_bias) == direction

    # ------------------------------------------------------------------
    # Rebel-lift predicate
    # ------------------------------------------------------------------

    def _has_opposite_recent_swing(
        self, *, bars: list, i: int, direction: str,
    ) -> bool:
        """Stand-in for the canonical "dribble through defence" pattern.

        Bachira's canonical weapon (`detectors_chartpatterns.py`) lives
        in `conflab/`; wiring it in is a v2 deliverable. For v1 we use a
        cheap, deterministic proxy: did the previous K bars contain a
        body-close in the OPPOSITE direction from this signal? If yes,
        Bachira is "dribbling through" a defender (i.e. fading a recent
        contrarian move), and the rebel lift applies.
        """
        if i < BACHIRA_V1_REBEL_LOOKBACK or direction not in ("long", "short"):
            return False
        opposite = "short" if direction == "long" else "long"
        for k in range(i - BACHIRA_V1_REBEL_LOOKBACK, i):
            if k < 0 or k >= len(bars):
                continue
            bar = bars[k]
            body_dir = "long" if bar.close > bar.open else (
                "short" if bar.close < bar.open else "flat"
            )
            if body_dir == opposite:
                return True
        return False

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _abstain_thought(self, market: MarketState, *, reason: str) -> Thought:
        tags = [
            "canon:bachira",
            "weapon:rebel_dribble",
            "bachira_abstain",
            f"abstain_reason:{reason}",
        ]
        if reason == "off_symbol":
            tags.append("bachira_abstain_symbol")
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[bachira v1] {market.symbol} {market.timeframe} @ "
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

def _coordinate_from_signal(
    *,
    sig,
    agent_id: str,
    symbol: str,
    as_of: datetime,
    home_tf: str,
    target_hold_hours: float,
    conviction: float,
) -> Coordinate:
    """Build a `Coordinate` from a production AlphaSignal.

    Same structure as A7 Barou's helper: price band centred on signal
    entry +/- stop distance, time window = target hold hours, regime
    predicate = literal `bachira_rebel_baseline_zone`. The rationale
    carries entry/stop/tp so a downstream chemical-reaction agent
    (Nagi) can borrow them via `coordinate.rationale`.
    """
    direction = sig.direction.value
    stop_dist = abs(float(sig.entry) - float(sig.stop))
    band_half = max(stop_dist, 0.0001)  # at least 1 pip wide
    return Coordinate(
        agent_id=agent_id,
        symbol=symbol,
        price_lo=float(sig.entry) - band_half,
        price_hi=float(sig.entry) + band_half,
        time_start=as_of,
        time_end=as_of + timedelta(hours=float(target_hold_hours)),
        vol_band=(0.5, 2.0),
        regime_predicate="bachira_rebel_baseline_zone",
        expected_strength=float(conviction),
        direction_bias=direction,
        rationale={
            "entry": float(sig.entry),
            "stop": float(sig.stop),
            "take_profit": float(sig.take_profit),
            "signal_reason": sig.reason,
            "home_tf": home_tf,
            "conviction_base": float(sig.conviction),
            "conviction_final": float(conviction),
        },
    )


# Backwards-compatible alias for roster loaders.
BachiraMeguru = A2BachiraV1
