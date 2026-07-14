"""A1 — Yoichi Isagi v1 (`isagi_yoichi`) — Phi3 production wrapper.

A1 Isagi v1 is the BlueLockStriker (`06-blue-lock-doctrine.md` section 4.1)
wrapper around the production `zone_d1_against / H4 / all` cell that
clears E004's walk-forward gate (+11.34 median pips/trade, 7/7 OOS;
`docs/findings/2026-06-09_walk_forward_validation.md`).

Canon role and parameters are locked (roster 05 section 3.1 + the E004
walk-forward configuration):

* `htf_align="D1"`, `htf_align_mode="against"`, `htf_lookback=10`,
  `htf_min_move_pips=60`, `target_rr=1.5`.
* Symbols whitelist: EURUSD / GBPUSD / USDCAD.
* Home TF for `intend`: H4 (the legacy detector cadence Isagi v1
  inherits; Isagi v2 will move to H1).
* Information tier: TBD pending Phi3 ΔInfo measurement (F17). The
  wrapper does not depend on any peer Thoughts -- the Tier-3
  `RedactedLedger` produces byte-identical proposals to `FullLedger`
  in v1 (regression-tested in `tests/test_a01_isagi_wrap.py`).

Implementation notes
--------------------
The production `SupplyDemandAlpha.signal(actx, i)` operates on
`(bars: list[Bar], ctx: PrecomputedContext)` indexed by the current bar
position. The M001 engine drives the wrapper via `MarketState` snapshots
keyed by `as_of` timestamps. The wrapper bridges the two by:

1. `prepare(symbol, bars)` -- called once per symbol *before* the replay
   loop. Stores the full bar series and the precomputed detector context,
   plus a `timestamp -> index` map. The harness in
   `sim/scoring/run_isagi_phi3_gate.py` calls this on the dev window.
2. `observe(market, ledger)` -- emits a Thought every tick. If the
   wrapper has prepared bars for this symbol *and* the current timestamp
   exists in the index map, the thought carries a `bar_index` rationale
   tag and a non-zero conviction if the underlying signal fires.
3. `intend(market, my_recent_thought)` -- called at H4 close; returns an
   AgentProposal iff the wrapped `SupplyDemandAlpha.signal` returns a
   non-None signal at the current index.

If `prepare()` was never called for the active symbol, both methods
degrade safely: `observe` emits an observation-only Thought tagged
`unprepared`, and `intend` returns None. This keeps the engine
smoke-test path green even without real bars in scope.

Cross-repo import is bracketed by
the production-repo bootstrap (now a no-op in this trading-repo port); the contract is
documented in `sim/README.md` under "Running Phi3 gate".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from agent.squad.ledger import ThoughtLedger
from agent.squad.provenance_pips import (
    expected_r_from_prices,
    isagi_metavision_lift,
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

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked E004 deployment parameters (`docs/findings/2026-06-09_*.md`).
# Edits require an amendment commit on `09-experiment-architecture.md`.
# ---------------------------------------------------------------------------
ISAGI_V1_PARAMS: dict[str, Any] = {
    "name": "A1_isagi_v1_zone_d1_against",
    "htf_align": "D1",
    "htf_align_mode": "against",
    "htf_lookback": 10,
    "htf_min_move_pips": 60.0,
    "target_rr": 1.5,
}

# Default symbol whitelist per roster 05 section 3.1.
ISAGI_V1_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")

# Default canon role per doctrine 06 section 3.10 + roster 05 section 3.1.
ISAGI_V1_CANON_ROLE = CanonRole(
    canon_player="isagi_yoichi",
    weapon="metavision_seed_zone_d1_against",
    ego=0.60,
    target_hold_hours=24.0,  # H4 zone fades typically resolve in ~6 H4 bars.
    narrative_voice="field_general_metavision",
)


@dataclass
class _PreparedSeries:
    """Per-symbol cache populated by `prepare()`."""

    bars: list  # production Bar list
    ctx: Any   # PrecomputedContext from agent.rules.engine.precompute
    index_by_ts: dict[datetime, int]


class A1IsagiV1(BaseStriker):
    """A1 Isagi v1 -- BlueLockStriker wrapper around production zone_d1_against.

    Public surface (called from the engine):

    * `observe(market, ledger) -> Thought` -- always emits a Thought.
    * `intend(market, my_recent_thought) -> AgentProposal | None` -- only at
      H4 close; only fires when the production signal fires at the current
      `(symbol, as_of)` and the wrapper has been `prepare()`'d on that
      symbol.

    Harness-only surface:

    * `prepare(symbol, bars)` -- pre-load bars + precomputed context.
    * `inner_signal_at(symbol, i)` -- direct access to the underlying
      `SupplyDemandAlpha.signal(actx, i)` for the proof-of-equivalence
      test in `tests/test_a01_isagi_wrap.py`.
    """

    def __init__(
        self,
        agent_id: str = "isagi_yoichi",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
        *,
        production_cfg: Any | None = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or ISAGI_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(ISAGI_V1_SYMBOLS),
            playstyle="conservative_metavision",
            tier=1,
        )
        # production alphas live in this repo; no PYTHONPATH bootstrap needed
        from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha  # noqa: E402
        from agent.config import load_config  # noqa: E402

        self._cfg = production_cfg if production_cfg is not None else load_config()
        self._inner = SupplyDemandAlpha(cfg=self._cfg, **ISAGI_V1_PARAMS)
        self._prepared: dict[str, _PreparedSeries] = {}

    # ------------------------------------------------------------------
    # Harness API
    # ------------------------------------------------------------------

    def prepare(self, symbol: str, bars: list) -> None:
        """Pre-load bars + precompute detector context for `symbol`.

        Idempotent on `(symbol, len(bars))`. The harness calls this once
        per symbol before the replay loop. Bars must be production
        `agent.types.Bar` objects (see `agent.data.loader.df_to_bars`).
        """
        # production alphas live in this repo; no PYTHONPATH bootstrap needed
        from agent.rules.engine import precompute  # noqa: E402

        ctx = precompute(list(bars), self._cfg)
        index_by_ts = {b.time: i for i, b in enumerate(bars)}
        self._prepared[symbol] = _PreparedSeries(
            bars=list(bars), ctx=ctx, index_by_ts=index_by_ts,
        )
        log.info(
            "A1IsagiV1 prepared %s: %d bars, %d zones, %d swings",
            symbol, len(bars), len(ctx.zones), len(ctx.swings),
        )

    def inner_signal_at(self, symbol: str, i: int):
        """Direct passthrough to the wrapped `SupplyDemandAlpha.signal`.

        Used by `tests/test_a01_isagi_wrap.py` to assert byte-equivalent
        signals between the wrapper and the raw production alpha.
        """
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
        prep = self._prepared.get(market.symbol)
        tags = ["zone_d1_against", "htf_against", "canon:isagi", "weapon:metavision_seed"]

        if prep is None:
            return Thought(
                schema_version=SCHEMA_VERSION,
                agent_id=self.agent_id,
                tick_id=market.tick_id,
                timestamp=market.as_of,
                symbol=market.symbol,
                narrative=(
                    f"[isagi v1] {market.symbol} {market.timeframe} @ {market.as_of} "
                    f"-- wrapper not prepared for this symbol; observation-only."
                ),
                tags=tags + ["unprepared"],
                confidence_in_thought=0.0,
                expected_action="wait",
                coordinate=None,
                decision_horizon=market.as_of,
                ttl_ticks=1,
                references=[],
            )

        i = prep.index_by_ts.get(market.as_of)
        if i is None:
            return Thought(
                schema_version=SCHEMA_VERSION,
                agent_id=self.agent_id,
                tick_id=market.tick_id,
                timestamp=market.as_of,
                symbol=market.symbol,
                narrative=(
                    f"[isagi v1] {market.symbol} {market.timeframe} @ {market.as_of} "
                    "-- timestamp not in prepared bar index; observation-only."
                ),
                tags=tags + ["timestamp_miss"],
                confidence_in_thought=0.0,
                expected_action="wait",
                coordinate=None,
                decision_horizon=market.as_of,
                ttl_ticks=1,
                references=[],
            )

        sig = self.inner_signal_at(market.symbol, i)
        if sig is None:
            return Thought(
                schema_version=SCHEMA_VERSION,
                agent_id=self.agent_id,
                tick_id=market.tick_id,
                timestamp=market.as_of,
                symbol=market.symbol,
                narrative=(
                    f"[isagi v1] {market.symbol} H4 close {market.as_of}: "
                    "no zone-touch + D1-counter alignment; waiting."
                ),
                tags=tags,
                confidence_in_thought=0.0,
                expected_action="wait",
                coordinate=None,
                decision_horizon=market.as_of,
                ttl_ticks=1,
                references=[],
            )

        meta_tags = _meta_to_tags(getattr(sig, "meta", {}) or {})
        coord = _coordinate_from_signal(
            sig=sig,
            agent_id=self.agent_id,
            symbol=market.symbol,
            as_of=market.as_of,
            home_tf=self.home_tf,
            target_hold_hours=self.canon_role.target_hold_hours,
        )
        # Dispersion-r2 (2026-07-14, doctrine §4.1a amendment): stamp
        # volatility provenance into the workspace coordinate so
        # bar-less borrowers (Nagi) can feed real F20 inputs.
        stamp_provenance_pips(coord.rationale, bars=prep.bars, i=i)
        direction = sig.direction.value  # "long" | "short"
        stop_pips = stop_pips_from_prices(market.symbol, sig.entry, sig.stop)
        r_expected = expected_r_from_prices(sig.entry, sig.stop, sig.take_profit)
        sig_meta = getattr(sig, "meta", {}) or {}
        regime_read = str(sig_meta.get("htf_bias") or "unknown")
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[isagi v1] {market.symbol} H4 close {market.as_of}: "
                f"zone-touch {direction} fade against D1 bias; "
                f"entry={sig.entry:.5f} stop={sig.stop:.5f} tp={sig.take_profit:.5f}."
            ),
            tags=tags + meta_tags + [f"signal_reason:{sig.reason}"],
            confidence_in_thought=float(sig.conviction),
            expected_action=f"{direction}_on_H4_close",
            coordinate=coord,
            decision_horizon=market.as_of,
            ttl_ticks=6,  # zone is fresh until next ~6 H4 bars (~1 trading day)
            references=[],
            read=ThoughtRead(
                signal_family="metavision",
                direction_bias=direction,  # type: ignore[arg-type]
                regime_read=regime_read,
                expected_stop_pips=stop_pips,
                expected_r=r_expected,
                driving_evidence=(
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
    ) -> AgentProposal | None:
        # Phase O (2026-07-01): Isagi's metavision reads all peer thoughts
        # via the F21 workspace. Even though he is the tier-1 anchor and
        # the aggregator gives him tie-break priority (Phase N), the
        # doctrine is "Isagi sees the WHOLE field" -- he consumes peer
        # thoughts diagnostically (logged in rationale) even when his
        # decision does not depend on them for v1.
        if market.timeframe != self.home_tf:
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

        # Conviction-in-thought matches conviction-in-proposal directly: the
        # production alpha emits 0.65 conviction on zone touches by default.
        # No M001-specific scaling -- this is the *wrapper validation*.
        direction = sig.direction.value
        ladder = [LadderRung(price=float(sig.take_profit), fraction=1.0)]
        # Risk: stop distance in price space.  Used to set `valid_until` to
        # the agent's target_hold_hours horizon -- if the trade isn't taken
        # within that window the proposal stales.
        horizon = market.as_of + timedelta(
            hours=float(self.canon_role.target_hold_hours),
        )

        # F21 workspace read -- metavision peer scan.
        peer_view_count = 0
        peer_directions_agree = 0
        peer_directions_disagree = 0
        if workspace is not None:
            peers = workspace.peer_thoughts(agent_id=self.agent_id)
            peer_view_count = len(peers)
            for peer_t in peers:
                if peer_t.coordinate is None:
                    continue
                peer_dir = str(peer_t.coordinate.direction_bias)
                if peer_dir == sig.direction.value:
                    peer_directions_agree += 1
                elif peer_dir in ("long", "short"):
                    peer_directions_disagree += 1

        # Phase S (2026-07-01, doctrine amendment "F19 variance"):
        # Isagi's metavision now produces variable conviction based on
        # peer alignment. The base 0.65 from SupplyDemandAlpha is a
        # weapon-agnostic zone conviction; the metavision lift is the
        # tier-1 anchor's real signal.
        metavision_lift = isagi_metavision_lift(
            peer_directions_agree=peer_directions_agree,
            peer_directions_disagree=peer_directions_disagree,
        )
        final_conviction = max(
            0.0, min(1.0, float(sig.conviction) + metavision_lift),
        )
        # Phase S: regime_fit is now a per-bar function of ATR, not the
        # constant 0.5 placeholder. Playstyle_lot_intent sees real
        # variance -> C5 dispersion emerges from real inputs, not
        # sub-tick noise.
        regime_fit_dyn = regime_fit_from_atr(prep.bars, i)

        meta = getattr(sig, "meta", {}) or {}
        rationale: dict[str, Any] = {
            "wrapped": "agent.alphas.concepts.zone_alpha.SupplyDemandAlpha",
            "params": dict(ISAGI_V1_PARAMS),
            "signal_reason": sig.reason,
            "htf_bias": meta.get("htf_bias"),
            "htf_align": meta.get("htf_align"),
            "htf_align_mode": meta.get("htf_align_mode"),
            "htf_lookback": meta.get("htf_lookback"),
            "htf_min_move_pips": meta.get("htf_min_move_pips"),
            "bar_index": int(i),
            "metavision_peer_view_count": int(peer_view_count),
            "metavision_peers_agree": int(peer_directions_agree),
            "metavision_peers_disagree": int(peer_directions_disagree),
            "metavision_conviction_lift": float(metavision_lift),
            "base_conviction": float(sig.conviction),
            "final_conviction": float(final_conviction),
            "regime_fit_source": "atr_pips",
        }
        # F20 provenance: real per-bar ATR + swing range so G7 C6
        # dispersion is measured on live inputs, not fallback constants.
        stamp_provenance_pips(rationale, bars=prep.bars, i=i)
        return AgentProposal(
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            source_thought_id=my_recent_thought.thought_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            direction=direction,  # "long" | "short"
            entry=float(sig.entry),
            stop=float(sig.stop),
            ladder=ladder,
            conviction=final_conviction,
            regime_fit=regime_fit_dyn,
            valid_until=horizon,
            rationale=rationale,
            agent_tier=int(self.tier),
        )


# ---------------------------------------------------------------------------
# Helpers (pure, no I/O)
# ---------------------------------------------------------------------------

def _meta_to_tags(meta: dict[str, Any]) -> list[str]:
    """Translate `AlphaSignal.meta` HTF context into Thought tag strings.

    Doctrine 06 section 3.8: `Thought.tags` carry semantic labels the
    aggregator + dashboard read. Encoding the production gate inputs into
    tag strings lets the F14 / F17 harnesses filter by HTF context without
    a separate column.
    """
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
) -> Coordinate:
    """Build a `Coordinate` from a production AlphaSignal.

    The price band is centred on the signal entry +/- the stop distance
    (so the box is the agent's risk envelope). Time window runs from
    `as_of` to `as_of + target_hold_hours`. Vol band is the wide default
    `(0.5, 2.0)` that doctrine 06 section 3.2 suggests until F18 wires in
    a measured prior. Regime predicate carries the literal HTF-against
    rule key so the chemical-reaction overlap detector (F13) can match
    Coordinates by predicate text. `expected_strength` mirrors signal
    conviction (one-to-one with the production prior).
    """
    direction = sig.direction.value
    stop_dist = abs(float(sig.entry) - float(sig.stop))
    band_half = max(stop_dist, 0.0001)  # at least 1 pip wide for valid Coordinate
    return Coordinate(
        agent_id=agent_id,
        symbol=symbol,
        price_lo=float(sig.entry) - band_half,
        price_hi=float(sig.entry) + band_half,
        time_start=as_of,
        time_end=as_of + timedelta(hours=float(target_hold_hours)),
        vol_band=(0.5, 2.0),
        regime_predicate="D1_trend_against",
        expected_strength=float(sig.conviction),
        direction_bias=direction,
        rationale={
            "entry": float(sig.entry),
            "stop": float(sig.stop),
            "take_profit": float(sig.take_profit),
            "signal_reason": sig.reason,
            "home_tf": home_tf,
        },
    )


# Backwards-compatible alias for v0.2 callers (tests, roster loaders).
# The legacy class name `IsagiYoichi` is retained so existing test fixtures
# (e.g. `tests/test_determinism.py`) keep working without modification.
IsagiYoichi = A1IsagiV1
