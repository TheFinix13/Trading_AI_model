"""A3 -- Itoshi Rin v1 (`itoshi_rin`) -- cold-precision technician.

Rin is the cold technician (roster `05-agent-roster-v0.md` section 3.3,
doctrine `06-blue-lock-doctrine.md` section 3.1 -- "technical
perfection"). His canonical weapon is multi-TF Fibonacci / harmonic
confluence: he refuses to fire unless the geometry is perfect. Per the
empirical prior (`audits/2026-06-24_E001-E007_audit.md` section 2.6),
standalone Fib tags did NOT survive OOS on EURUSD or replicate on
GBPUSD -- so Rin's edge cannot come from raw Fib detection alone. v1
therefore deploys a **conservative precision filter** on top of the
same production `zone_d1_against` cell Isagi v1 wraps:

* `htf_align="D1"`, `htf_align_mode="against"` (same gate as Isagi v1)
* `target_rr=2.5` (higher R:R floor than Isagi's 1.5; Fib-style)
* stop-distance floor of `RIN_V1_MIN_STOP_PIPS=20` pips -- the
  "structural cleanliness" requirement (no firing on tight-chop zones
  whose stop is too close)

Rin's signal stream is therefore a **strict subset of Isagi's**: every
Rin trade is a trade Isagi would also take, but Isagi takes many trades
Rin filters out. Same tags inherited from the production cell
(`zone_d1_against`, `htf_against`, `htf_align:D1`, `htf_align_mode:against`,
`signal_reason:zone_*`); same direction bias on the same bar.

This is exactly what Nagi's F11/F13 chemical-reaction predicate needs.
Rin + Isagi pair naturally:

* shared tags: `zone_d1_against`, `htf_against`, plus the meta tags --
  far more than the 2-shared-tags floor;
* overlapping coordinate price bands -- same zone touch;
* matching direction bias -- same trade direction by construction.

The remaining barrier is the `NAGI_V1_CONFIDENCE_FLOOR=0.7` floor. The
production cell emits 0.65 base conviction. Rin v1 applies a
`RIN_V1_PRECISION_LIFT=+0.15` lift on signals that pass the strict
precision gate -- final conviction lands at 0.80, comfortably above
the Nagi floor.

Φ4.1 design notes
-----------------

* **Cold precision, not raw Fib.** Roster section 3.3 names Fibonacci /
  harmonic as the canonical weapon but the empirical prior says
  standalone Fib tags fail OOS. v1 keeps the Fib *spirit* (high R:R,
  geometric cleanliness) while leaning on the production cell's
  zone primitive for actual entry timing. v2 wires the conflab Fib
  detectors as the structural-cleanliness predicate.
* **Subset-of-Isagi behaviour by design.** This is the principled-form
  of "I take only the perfect setups". Rin's F17 ΔInfo arm is
  trivially Tier-3-equivalent for v1 (he reads no peers); the squad
  gate still measures it for the audit trail.

Cross-repo import is bracketed by
the production-repo bootstrap (now a no-op in this trading-repo port); same contract as
Isagi / Bachira / Barou.
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
    IntentDecision,
    MarketState,
    Thought,
    ThoughtRead,
    YieldReason,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked Φ4.1 v1 parameters.
# ---------------------------------------------------------------------------
RIN_V1_PARAMS: dict[str, Any] = {
    "name": "A3_rin_v1_precision_zone_d1_against",
    "htf_align": "D1",
    "htf_align_mode": "against",
    "htf_lookback": 10,
    "htf_min_move_pips": 60.0,
    "target_rr": 2.5,            # Rin demands higher R:R than Isagi
}

RIN_V1_SYMBOLS: tuple[str, ...] = ("EURUSD",)
RIN_V1_MIN_STOP_PIPS: float = 20.0     # structural cleanliness floor
RIN_V1_PRECISION_LIFT: float = 0.15    # +0.15 max lift to base conviction
RIN_V1_PRECISION_LIFT_MIN: float = 0.05  # taper floor for wider stops
RIN_V1_PRECISION_DECAY_PIPS: float = 40.0  # stop_pips beyond floor before lift decays fully
RIN_V1_CONV_CAP: float = 1.0
RIN_V1_PIP_SIZE: float = 0.0001        # USD-quoted majors

# Phase T-evolve (Rin v1.1, 2026-07-01 evening) -- peer-yield-and-lift.
# Blue-Lock canon: Rin evolves by scoring goals Isagi *can't*, not by
# out-precising Isagi on the same shot. Doctrine amendment §11.8.
#
# Mechanic:
#   - Compute Isagi's metavision confluence from peer thoughts on the
#     same symbol (same math as `isagi_metavision_lift`).
#   - If Isagi has metavision support (>=1 peer agrees, 0 disagree) ->
#     Rin YIELDS (`intend()` returns None). She recognises the shot
#     belongs to Isagi's line and steps off it.
#   - Otherwise (peers disagree, or all quiet) -> Rin applies an
#     additional `RIN_V1_LONE_READ_LIFT` bonus on top of her precision
#     lift, giving her final conviction 0.90 (0.65 base + 0.15 precision
#     + 0.10 lone-read). She now decisively wins the aggregator on the
#     ticks Isagi runs on base conviction only.
#
# This is the peer-disagreement / regime-specialist evolution the user
# requested. Rin no longer competes with Isagi on the same signal; she
# specialises in the anti-metavision regime.
RIN_V1_LONE_READ_LIFT: float = 0.10


def _rin_precision_lift(stop_pips: float) -> float:
    """Phase P (2026-07-01) -- variable precision lift as a function of
    stop tightness.

    stop_pips == RIN_V1_MIN_STOP_PIPS (perfect precision at the floor)
        -> lift = RIN_V1_PRECISION_LIFT (0.15)
    stop_pips == RIN_V1_MIN_STOP_PIPS + RIN_V1_PRECISION_DECAY_PIPS
        -> lift = RIN_V1_PRECISION_LIFT_MIN (0.05)
    Beyond that -> stays at the floor (Rin still fires but with
    minimally lifted conviction).

    This gives Rin's per-trade conviction real variance (0.70 -> 0.80)
    so G7 C5 dispersion is measurable instead of saturating at Kelly's
    MIN_LOT clamp.
    """
    if stop_pips <= RIN_V1_MIN_STOP_PIPS:
        return RIN_V1_PRECISION_LIFT
    delta = stop_pips - RIN_V1_MIN_STOP_PIPS
    if delta >= RIN_V1_PRECISION_DECAY_PIPS:
        return RIN_V1_PRECISION_LIFT_MIN
    span = RIN_V1_PRECISION_LIFT - RIN_V1_PRECISION_LIFT_MIN
    return RIN_V1_PRECISION_LIFT - span * (delta / RIN_V1_PRECISION_DECAY_PIPS)

RIN_V1_CANON_ROLE = CanonRole(
    canon_player="itoshi_rin",
    weapon="precision_geometry_strict_rr_zone",
    ego=0.40,
    target_hold_hours=32.0,
    narrative_voice="cold_geometric_perfection",
)


@dataclass
class _PreparedSeries:
    """Per-symbol cache populated by `prepare()`."""

    bars: list
    ctx: Any
    index_by_ts: dict[datetime, int]


class A3RinV1(BaseStriker):
    """A3 Rin v1 -- precision-filtered zone_d1_against striker.

    Public surface (engine):
      * `observe(market, ledger)` -- always emits a Thought. When the
        production cell fires AND the stop-distance floor is met, the
        Thought carries a Coordinate at base_conv + RIN_V1_PRECISION_LIFT
        and the `rin_precision_lift_applied` tag. When the cell fires
        but the floor is NOT met, the Thought carries the Coordinate
        at base_conv only (no lift, no qualification as a Nagi peer).
      * `intend(market, my_recent_thought)` -- H4 close on EURUSD only.

    Harness API (same shape as Isagi / Bachira / Barou):
      * `prepare(symbol, bars)` -- pre-load production Bar list + ctx.
      * `inner_signal_at(symbol, i)` -- direct passthrough for
        proof-of-equivalence tests.
    """

    def __init__(
        self,
        agent_id: str = "itoshi_rin",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
        *,
        production_cfg: Any | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or RIN_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(RIN_V1_SYMBOLS),
            playstyle="analytical_precision",
            tier=2,
        )
        # production alphas live in this repo; no PYTHONPATH bootstrap needed
        from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha  # noqa: E402
        from agent.config import load_config  # noqa: E402

        self._cfg = production_cfg if production_cfg is not None else load_config()
        self._inner = SupplyDemandAlpha(cfg=self._cfg, **RIN_V1_PARAMS)
        self._prepared: dict[str, _PreparedSeries] = {}

    # ------------------------------------------------------------------
    # Harness API
    # ------------------------------------------------------------------

    def prepare(self, symbol: str, bars: list) -> None:
        if symbol not in self.symbols:
            log.info(
                "A3RinV1.prepare(%s) ignored -- not in symbol whitelist %s",
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
            "A3RinV1 prepared %s: %d bars, %d zones, %d swings",
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
        stop_pips = (
            abs(float(sig.entry) - float(sig.stop)) / RIN_V1_PIP_SIZE
        )
        precision_passed = stop_pips >= RIN_V1_MIN_STOP_PIPS

        if not precision_passed:
            # Inner signal fired but the structural-cleanliness floor
            # rejected it. Rin emits an observation-only Thought (the
            # Fib-perfectionist refuses to even glance at a sloppy
            # zone). intend() will return None for these.
            return self._observation_only(
                market=market,
                reason=f"stop_pips_{stop_pips:.1f}_below_floor",
                direction=direction,
                base_conv=base_conv,
            )

        # Phase P (2026-07-01): variable precision lift as a function of
        # stop tightness -- gives per-trade conviction real variance so
        # G7 C5 dispersion is measurable, not Kelly-saturated at MIN_LOT.
        precision_lift = _rin_precision_lift(stop_pips)
        final_conv = min(
            RIN_V1_CONV_CAP, base_conv + precision_lift,
        )
        meta = getattr(sig, "meta", {}) or {}
        meta_tags = _meta_to_tags(meta)
        coord = _coordinate_from_signal(
            sig=sig, agent_id=self.agent_id, symbol=market.symbol,
            as_of=market.as_of, home_tf=self.home_tf,
            target_hold_hours=self.canon_role.target_hold_hours,
            conviction=final_conv, stop_pips=stop_pips,
        )
        # Dispersion-r2 (2026-07-14): volatility provenance for
        # bar-less borrowers (Nagi) -- see doctrine §4.1a amendment.
        stamp_provenance_pips(coord.rationale, bars=prep.bars, i=i)
        tags = [
            "canon:rin",
            "weapon:precision_geometry",
            "zone_setup_h4",
            "zone_d1_against",
            "htf_against",
            "rin_precision",
            "rin_precision_lift_applied",
            f"signal_reason:{sig.reason}",
            f"direction:{direction}",
        ] + meta_tags
        narrative = (
            f"[rin v1] {market.symbol} H4 close {market.as_of}: "
            f"precision-zone {direction} fade against D1 bias; "
            f"entry={sig.entry:.5f} stop={sig.stop:.5f} "
            f"(stop_pips={stop_pips:.1f}); base_conv {base_conv:.2f} "
            f"+ precision {precision_lift:.2f} = {final_conv:.2f}."
        )
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
                signal_family="precision",
                direction_bias=direction,  # type: ignore[arg-type]
                regime_read=str(meta.get("htf_bias") or "unknown"),
                expected_stop_pips=float(stop_pips),
                expected_r=r_expected,
                driving_evidence=(
                    "rin_precision",
                    "rin_precision_lift_applied",
                    "zone_d1_against",
                    "htf_against",
                    f"signal_reason:{sig.reason}",
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
    ) -> IntentDecision:
        # Phase O (2026-07-01): Rin reads Isagi's latest thought via
        # the F21 workspace to log whether her precision-fire aligns with
        # or contradicts the anchor's D1-against frame. Diagnostic-only
        # for v1; the decision itself is still gated by Rin's local
        # precision floor (stop_pips >= 20). Chemistry evidence flows
        # into the rationale for G7 C4.
        if market.timeframe != self.home_tf:
            return None
        if market.symbol not in self.symbols:
            return None
        if "rin_precision_lift_applied" not in my_recent_thought.tags:
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
        conviction = float(my_recent_thought.confidence_in_thought)
        ladder = [LadderRung(price=float(sig.take_profit), fraction=1.0)]
        horizon = market.as_of + timedelta(
            hours=float(self.canon_role.target_hold_hours),
        )
        meta = getattr(sig, "meta", {}) or {}
        stop_pips = (
            abs(float(sig.entry) - float(sig.stop)) / RIN_V1_PIP_SIZE
        )

        # F21 workspace read -- alignment with the tier-1 anchor plus
        # Phase T-evolve peer-metavision scan.
        isagi_frame_aligned: bool | None = None
        isagi_frame_direction: str | None = None
        peer_agree = 0
        peer_disagree = 0
        peer_seen = 0
        peer_ids_agree: list[str] = []
        if workspace is not None:
            latest_by_agent = workspace.latest_by_agent(symbol=market.symbol)
            isagi_t = latest_by_agent.get("isagi_yoichi")
            if isagi_t is not None and isagi_t.coordinate is not None:
                isagi_frame_direction = str(isagi_t.coordinate.direction_bias)
                if isagi_frame_direction in ("long", "short"):
                    isagi_frame_aligned = (isagi_frame_direction == direction)
            # Compute the same metavision confluence Isagi will see when
            # HE runs `intend()` later this tick -- both agents read the
            # same snapshot, so Rin can predict whether Isagi's
            # metavision lift will apply. Rin scans peers OTHER than
            # herself.
            peer_thoughts = workspace.peer_thoughts(agent_id=self.agent_id)
            for peer_t in peer_thoughts:
                if peer_t.symbol != market.symbol:
                    continue
                if peer_t.coordinate is None:
                    continue
                peer_dir = str(peer_t.coordinate.direction_bias)
                if peer_dir not in ("long", "short"):
                    continue
                peer_seen += 1
                if peer_dir == direction:
                    peer_agree += 1
                    peer_ids_agree.append(peer_t.agent_id)
                else:
                    peer_disagree += 1

        # Phase T-evolve yield rule: Isagi's metavision fires when peers
        # agree with him. If peers agree with Rin's direction AND none
        # disagree, Isagi (who runs `intend()` on the same snapshot)
        # will also see peer_agree>=1 & peer_disagree==0 and lift his
        # own conviction by 0.05..0.10. On the aggregator tie-break
        # Isagi wins (tier-1 anchor bias). Rin therefore steps off the
        # shot -- she recognises it belongs to Isagi's line.
        isagi_would_lift = (peer_agree >= 1 and peer_disagree == 0)
        if isagi_would_lift:
            log.debug(
                "[rin v1.1] yield to isagi metavision @ tick=%d %s (%s): "
                "peer_agree=%d peer_disagree=%d peer_seen=%d",
                market.tick_id, market.symbol, direction,
                peer_agree, peer_disagree, peer_seen,
            )
            # F22c: emit a structured yield record so post-hoc audits can
            # score "did Rin's inference match reality?" on this tick.
            return YieldReason(
                agent_id=self.agent_id,
                tick_id=int(market.tick_id),
                symbol=market.symbol,
                reason="isagi_would_lift_metavision",
                peer_ids_read=tuple(peer_ids_agree),
                evidence={
                    "direction": direction,
                    "peer_agree_count": int(peer_agree),
                    "peer_disagree_count": int(peer_disagree),
                    "peer_seen_count": int(peer_seen),
                    "isagi_frame_direction": isagi_frame_direction,
                    "isagi_frame_aligned": isagi_frame_aligned,
                    "signal_reason": sig.reason,
                    "stop_pips": float(stop_pips),
                    "would_have_final_conviction": float(min(
                        RIN_V1_CONV_CAP, conviction + RIN_V1_LONE_READ_LIFT,
                    )),
                },
                doctrine_ref="06-blue-lock-doctrine.md sec 4.1c + F22c",
            )

        # Phase T-evolve lone-read lift: peers disagree or are quiet,
        # so Isagi's metavision will NOT fire. Rin recognises this is
        # a shot only her precision reads and lifts her conviction by
        # `RIN_V1_LONE_READ_LIFT` on top of the precision lift already
        # in `my_recent_thought.confidence_in_thought`. Cap at 1.0.
        lone_read_active = True
        final_conviction = min(
            RIN_V1_CONV_CAP, conviction + RIN_V1_LONE_READ_LIFT,
        )

        rationale: dict[str, Any] = {
            "wrapped": "agent.alphas.concepts.zone_alpha.SupplyDemandAlpha",
            "params": dict(RIN_V1_PARAMS),
            "signal_reason": sig.reason,
            "htf_bias": meta.get("htf_bias"),
            "htf_align": meta.get("htf_align"),
            "htf_align_mode": meta.get("htf_align_mode"),
            "stop_pips": float(stop_pips),
            "min_stop_pips": float(RIN_V1_MIN_STOP_PIPS),
            "bar_index": int(i),
            "precision_lift_applied": True,
            "base_conviction": float(sig.conviction),
            "precision_conviction": float(conviction),
            "lone_read_lift_applied": lone_read_active,
            "lone_read_lift": float(RIN_V1_LONE_READ_LIFT),
            "final_conviction": float(final_conviction),
            "peer_agree_count": int(peer_agree),
            "peer_disagree_count": int(peer_disagree),
            "peer_seen_count": int(peer_seen),
            "isagi_frame_direction": isagi_frame_direction,
            "isagi_frame_aligned": isagi_frame_aligned,
            "isagi_would_lift_metavision": bool(isagi_would_lift),
            "doctrine_ref": (
                "06-blue-lock-doctrine.md sec 3.1 (precision) + "
                "sec 4.1c Phase T-evolve (peer-yield-and-lift)"
            ),
            "empirical_prior": (
                "E006 Fib tags +0.12..+0.15 ATR EURUSD only, not OOS-stable; "
                "Rin v1 stays on zone primitive with precision filter"
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
            conviction=float(final_conviction),
            regime_fit=regime_fit_from_atr(prep.bars, i),
            valid_until=horizon,
            rationale=rationale,
            agent_tier=int(self.tier),
        )

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _observation_only(
        self,
        *,
        market: MarketState,
        reason: str,
        direction: str,
        base_conv: float,
    ) -> Thought:
        tags = [
            "canon:rin",
            "weapon:precision_geometry",
            "rin_precision_rejected",
            f"rin_reject_reason:{reason}",
        ]
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[rin v1] {market.symbol} H4 close {market.as_of}: "
                f"inner zone signal fired ({direction}, base_conv "
                f"{base_conv:.2f}) but precision filter rejected "
                f"({reason}); observation-only."
            ),
            tags=tags,
            confidence_in_thought=0.0,
            expected_action="wait",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=1,
            references=[],
        )

    def _abstain_thought(self, market: MarketState, *, reason: str) -> Thought:
        tags = [
            "canon:rin",
            "weapon:precision_geometry",
            "rin_abstain",
            f"abstain_reason:{reason}",
        ]
        if reason == "off_symbol":
            tags.append("rin_abstain_symbol")
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[rin v1] {market.symbol} {market.timeframe} @ "
                f"{market.as_of} -- abstain ({reason}); EURUSD-only "
                "precision specialist."
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

def _meta_to_tags(meta: dict[str, Any]) -> list[str]:
    """Translate `AlphaSignal.meta` into tag strings (parallels Isagi)."""
    out: list[str] = []
    bias = meta.get("htf_bias")
    if bias:
        out.append(f"htf_bias:{bias}")
    if meta.get("htf_align"):
        out.append(f"htf_align:{meta['htf_align']}")
    if meta.get("htf_align_mode"):
        out.append(f"htf_align_mode:{meta['htf_align_mode']}")
    lb = meta.get("htf_lookback")
    if lb is not None:
        out.append(f"htf_lookback:{int(lb)}")
    mp = meta.get("htf_min_move_pips")
    if mp is not None:
        out.append(f"htf_min_move_pips:{float(mp):.1f}")
    return out


def _coordinate_from_signal(
    *,
    sig,
    agent_id: str,
    symbol: str,
    as_of: datetime,
    home_tf: str,
    target_hold_hours: float,
    conviction: float,
    stop_pips: float,
) -> Coordinate:
    """Build a `Coordinate` from a production AlphaSignal.

    Same shape as Isagi v1's helper, plus the stop-pips rationale field
    so the audit trail proves the precision gate fired.
    """
    direction = sig.direction.value
    stop_dist = abs(float(sig.entry) - float(sig.stop))
    band_half = max(stop_dist, 0.0001)
    return Coordinate(
        agent_id=agent_id,
        symbol=symbol,
        price_lo=float(sig.entry) - band_half,
        price_hi=float(sig.entry) + band_half,
        time_start=as_of,
        time_end=as_of + timedelta(hours=float(target_hold_hours)),
        vol_band=(0.5, 2.0),
        regime_predicate="rin_precision_zone_d1_against",
        expected_strength=float(conviction),
        direction_bias=direction,
        rationale={
            "entry": float(sig.entry),
            "stop": float(sig.stop),
            "take_profit": float(sig.take_profit),
            "signal_reason": sig.reason,
            "home_tf": home_tf,
            "stop_pips": float(stop_pips),
            "conviction_base": float(sig.conviction),
            "conviction_final": float(conviction),
        },
    )


# Backwards-compatible alias for roster loaders.
ItoshiRin = A3RinV1
