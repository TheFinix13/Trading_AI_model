"""A7 -- Shoei Barou v1 (`barou_shoei`) -- USDCAD baseline-zone specialist.

Barou v1 wraps the SAME production `SupplyDemandAlpha` cell that
Isagi v1 wraps, but **with the D1-trend gate disabled**
(`htf_align=None`). Symbol whitelist is locked to **USDCAD only** per
roster section 3.7. The empirical justification is the **E005 cross-
pair side-note** (audit `2026-06-24_E001-E007_audit.md` section 4.3):

> Baseline `zone` (without the D1-trend gate) is *stronger* than
> `zone_d1_against` on **USDCAD/AUDUSD/NZDUSD** -- the **inverse** of
> the EURUSD pattern. On USDCAD the baseline `zone` delivers +4.63
> pips/trade with 10/11 positive years (Sharpe 1.16, p=0.028) where
> `zone_d1_against` only manages the same direction's structural-fade
> behaviour. This asymmetry IS Barou's whole thesis.

This is **not** a re-tune of Isagi -- it is a parallel deployment of
the SAME production cell at DIFFERENT parameters on a DIFFERENT
symbol. The lab repo NEVER recreates production code (doctrine sec 7,
architecture sec 7); we import the production class and instantiate
it with `htf_align=None`.

Devour mechanic (doctrine sec 3.4 + roster sec 3.7)
---------------------------------------------------

Barou is canonically the King -- the one striker who refuses to defer.
Operationally, when **Isagi has a high-conviction (>=0.7) signal on
USDCAD that DISAGREES directionally** with Barou's, Barou's conviction
gets a `devour_lift` of `+0.10` (capped at 1.0). The mechanic encodes
the canon "I will eat your read and prove mine" -- Barou's edge is
strongest exactly where Isagi's `htf_align=against` gate disagrees
with the baseline zone direction (the audit's "inverse asymmetry").

The lift is applied to BOTH the Thought and Proposal conviction. The
narrative + tags carry the `barou_devour_candidate` marker so the F12
TQS beauty bonus + the F17 ΔInfo arm can attribute the lifted-trade
slice cleanly.

This is a **Tier-2** behaviour by design (Barou reads Isagi's
Thoughts). Roster section 3.7's prior framing of Barou as "Tier-3 by
design / refuses to participate in chemical reactions" describes the
*default* state when Isagi is silent; the devour lift is the
*explicit* reaction to Isagi disagreement. F17 measures the design.

Symbols
-------

USDCAD only. EURUSD / GBPUSD ticks produce observation-only Thoughts
with the `barou_abstain_symbol` tag; `intend` returns None.

Cross-repo import is bracketed by
the production-repo bootstrap (now a no-op in this trading-repo port); the contract is
documented in `sim/README.md`.
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

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked Phi4 v1 parameters -- baseline zone without D1 gate, USDCAD only.
# ---------------------------------------------------------------------------
BAROU_V1_PARAMS: dict[str, Any] = {
    "name": "A7_barou_v1_baseline_zone_usdcad",
    "htf_align": None,        # ** the only difference from Isagi v1 **
    "target_rr": 1.5,         # same RR as Isagi; rigid for parity
}

# ---------------------------------------------------------------------------
# Phase Y (2026-07-14) -- Barou v1.3 weapon differentiation.
# Pre-registration: ``experiments/phase_y_barou_weapon/PROTOCOL.md``
# (committed before any result). Phase W-barou v1.2 HALT established
# that the v1 weapon is a literal duplicate of Bachira's cell; v1.3
# changes all three geometry legs so no Barou trade can duplicate a
# Bachira trade:
#
# - D1 WITH-trend gate (roster sec 3.7 canon "USDCAD-locked H4 trend
#   continuation"); gate params copied verbatim from Isagi's locked
#   E001-derived cell with only the mode flipped -- zero re-tuning.
# - Structural TP (production ``target_via_structure`` mode, shipped
#   defaults) -- the solo king finishes the full move.
# - ``stop_atr_mult = 1.0`` (2x the production default 0.5, a
#   qualitative doubling) -- wide invalidation, room for the strike.
#
# Empirical basis (banked only): E005 side-note -- on USDCAD baseline
# zone beats zone_d1_against, i.e. the with-trend complement subset
# contributed positively. E001's with-trend negative was on EURUSD;
# Barou stays USDCAD-locked precisely because of that prior.
# ---------------------------------------------------------------------------
BAROU_V13_PARAMS: dict[str, Any] = {
    "name": "A7_barou_v13_king_trend_continuation_usdcad",
    "htf_align": "D1",
    "htf_align_mode": "with",
    "htf_lookback": 10,          # verbatim from ISAGI_V1_PARAMS
    "htf_min_move_pips": 60.0,   # verbatim from ISAGI_V1_PARAMS
    "target_rr": 1.5,            # fallback when no structural target
    "target_via_structure": True,
    "structural_lookback": 200,  # production default
    "min_structural_rr": 1.0,    # production default
    "stop_atr_mult": 1.0,
}

BAROU_V1_SYMBOLS: tuple[str, ...] = ("USDCAD",)

BAROU_V1_DEVOUR_LIFT: float = 0.20           # +0.20 to conviction
BAROU_V1_DEVOUR_OBS_FLOOR: float = 0.5       # Isagi conviction threshold
BAROU_V1_CONV_CAP: float = 1.0
# 2026-07-01 Phase N bump: devour lift raised 0.10 -> 0.20 and the
# Isagi-disagreement floor lowered 0.7 -> 0.5 after the G7 walk-forward
# baseline confirmed Barou = 0 trades across all 7 windows (crowded out
# on USDCAD by Bachira). The stronger lift now gives Barou a decisive
# override when the devour condition fires (final conviction 0.85 >
# Bachira max 0.75), matching the "solo king finishes what Isagi
# couldn't" story-beat. See reviews/g7_v1_checkpoint_verdict_walk-
# forward-baseline.md.

# ---------------------------------------------------------------------------
# Phase W-barou v1.1 (2026-07-03) -- lone-conviction claim mechanic.
# See ``experiments/phase_w_barou/PROTOCOL.md`` H1.
# ---------------------------------------------------------------------------
BAROU_V1_1_LONE_CONVICTION_LIFT: float = 0.10  # mirrors Rin's LONE_READ_LIFT
BAROU_V1_1_CONV_CAP: float = BAROU_V1_CONV_CAP  # explicit alias for readability
BAROU_BACHIRA_AGENT_ID: str = "bachira_meguru"  # who we read for H1 gate

# H1 fires when Bachira did NOT publish a same-direction thought on
# Barou's symbol at the tick barrier -- i.e. Barou's read is genuinely
# solo (or a counter-conviction opportunity vs Bachira's opposite read).
# When Bachira DID publish same-direction, H1 skips -- existing devour
# mechanic still applies. See PROTOCOL sec 3 for the decision table.

# ---------------------------------------------------------------------------
# Phase W-barou v1.2 (2026-07-06) -- H2 continuation-entry mechanic.
# See ``experiments/phase_w_barou/PROTOCOL_v1.2.md`` sec 3. OFF by
# default: only ``A7BarouV1(continuation_entry_enabled=True)`` activates
# the branch, so every sealed cache stays byte-identical.
# ---------------------------------------------------------------------------
BAROU_V1_2_CONTINUATION_MIN_STOP_PIPS: float = 6.6
# ^ measured post-V panel minimum stop (Phi5 PROTOCOL sec 11.4 D
#   distribution, n=5604) -- the anchored stop can never be tighter than
#   anything the squad has ever traded.
_PIP: float = 0.0001


def continuation_anchor_geometry(
    *,
    entry: float,
    own_stop: float,
    own_tp: float,
    bachira_stop: float,
    direction: str,
    target_rr: float,
) -> tuple[float, float, str, bool]:
    """Pure H2 geometry (PROTOCOL_v1.2.md sec 3).

    Returns ``(final_stop, final_tp, stop_source, fired)``. The anchored
    stop distance is ``max(floor, min(own_dist, candidate_dist))`` and
    only applies when strictly tighter than Barou's own stop; TP is
    re-derived from the final stop distance at ``target_rr`` so RR is
    preserved, not gamed. Fall-through keeps Barou's own geometry
    untouched.
    """
    sign = 1.0 if direction == "long" else -1.0
    own_dist = abs(entry - own_stop)
    candidate_dist = sign * (entry - bachira_stop)
    if candidate_dist <= 0.0:
        return own_stop, own_tp, "invalid_anchor", False
    new_dist = max(
        BAROU_V1_2_CONTINUATION_MIN_STOP_PIPS * _PIP,
        min(own_dist, candidate_dist),
    )
    if new_dist >= own_dist:
        return own_stop, own_tp, "own", False
    return (
        entry - sign * new_dist,
        entry + sign * target_rr * new_dist,
        "bachira_anchor",
        True,
    )

BAROU_V1_CANON_ROLE = CanonRole(
    canon_player="barou_shoei",
    weapon="lone_wolf_baseline_zone_usdcad",
    ego=1.00,
    target_hold_hours=32.0,
    narrative_voice="king_dominant_solo_finishing",
)

BAROU_ISAGI_AGENT_ID: str = "isagi_yoichi"   # who we read for devour lift


@dataclass
class _PreparedSeries:
    """Per-symbol cache populated by `prepare()`."""

    bars: list                 # production Bar list
    ctx: Any                   # PrecomputedContext from agent.rules.engine
    index_by_ts: dict[datetime, int]


class A7BarouV1(BaseStriker):
    """A7 Barou v1 -- USDCAD baseline-zone specialist with devour lift.

    Public surface (engine):
      * `observe(market, ledger)` -- always emits a Thought; conviction is
        zero on EURUSD/GBPUSD (off-symbol abstention) and on no-signal
        ticks. On a USDCAD signal tick, applies the optional devour lift
        from prior-tick Isagi thoughts.
      * `intend(market, my_recent_thought)` -- USDCAD H4 close only.

    Harness API (kept identical to A1IsagiV1 for symmetry):
      * `prepare(symbol, bars)` -- pre-load USDCAD bars + ctx.
      * `inner_signal_at(symbol, i)` -- direct passthrough to
        `SupplyDemandAlpha.signal` for proof-of-equivalence tests.
    """

    def __init__(
        self,
        agent_id: str = "barou_shoei",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
        *,
        production_cfg: Any | None = None,
        isagi_agent_id: str = BAROU_ISAGI_AGENT_ID,
        continuation_entry_enabled: bool = False,
        weapon_v13: bool = True,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or BAROU_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(BAROU_V1_SYMBOLS),
            playstyle="solo_king",
            tier=2,
        )
        # production alphas live in this repo; no PYTHONPATH bootstrap needed
        from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha  # noqa: E402
        from agent.config import load_config  # noqa: E402

        self._cfg = production_cfg if production_cfg is not None else load_config()
        # Phase Y (2026-07-14): v1.3 weapon is the default; the legacy
        # v1 weapon stays available behind ``weapon_v13=False`` for
        # cache-reproduction tests only.
        self._weapon_v13 = bool(weapon_v13)
        self._weapon_params: dict[str, Any] = dict(
            BAROU_V13_PARAMS if self._weapon_v13 else BAROU_V1_PARAMS
        )
        self._inner = SupplyDemandAlpha(cfg=self._cfg, **self._weapon_params)
        self._prepared: dict[str, _PreparedSeries] = {}
        self._isagi_agent_id = isagi_agent_id
        # Phase W-barou v1.2 H2 gate (PROTOCOL_v1.2.md sec 3).
        self._continuation_entry_enabled = bool(continuation_entry_enabled)

    # ------------------------------------------------------------------
    # Harness API
    # ------------------------------------------------------------------

    def prepare(self, symbol: str, bars: list) -> None:
        """Pre-load bars + precompute detector context for `symbol`.

        Barou only operates on USDCAD; passing any other symbol logs a
        warning and is a no-op (mirrors the harness contract -- never
        raises just because the caller is being inclusive).
        """
        if symbol not in self.symbols:
            log.info(
                "A7BarouV1.prepare(%s) ignored -- not in symbol whitelist %s",
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
            "A7BarouV1 prepared %s: %d bars, %d zones, %d swings",
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
        # Off-symbol abstention: roster section 3.7 -- "ignores all other
        # instruments". Emit observation-only with a clear tag.
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

        direction = sig.direction.value  # "long" | "short"
        base_conv = float(sig.conviction)
        devour_info = self._maybe_apply_devour(market, ledger, direction)
        final_conv = min(
            BAROU_V1_CONV_CAP,
            base_conv + (BAROU_V1_DEVOUR_LIFT if devour_info["fired"] else 0.0),
        )

        coord = _coordinate_from_signal(
            sig=sig,
            agent_id=self.agent_id,
            symbol=market.symbol,
            as_of=market.as_of,
            home_tf=self.home_tf,
            target_hold_hours=self.canon_role.target_hold_hours,
            conviction=final_conv,
        )
        # Dispersion-r2 (2026-07-14): volatility provenance for
        # bar-less borrowers (Nagi) -- see doctrine §4.1a amendment.
        stamp_provenance_pips(coord.rationale, bars=prep.bars, i=i)
        tags = [
            "barou_usdcad_baseline_zone",
            "canon:barou",
            "weapon:lone_wolf_baseline_zone",
            f"signal_reason:{sig.reason}",
        ]
        if final_conv >= 0.7:
            tags.append("barou_devour_candidate")
        if devour_info["fired"]:
            tags.append("barou_devour_applied")
            tags.append(f"devour_against:{devour_info['isagi_direction']}")

        weapon_desc = (
            "king trend-continuation (D1 WITH gate, structural TP)"
            if self._weapon_v13 else "baseline-zone fade (NO D1 gate)"
        )
        narrative = (
            f"[barou {'v1.3' if self._weapon_v13 else 'v1'}] USDCAD H4 "
            f"close {market.as_of}: {weapon_desc} "
            f"{direction}. entry={sig.entry:.5f} "
            f"stop={sig.stop:.5f} tp={sig.take_profit:.5f}; "
            f"conv {base_conv:.2f}"
            + (
                f" + devour {BAROU_V1_DEVOUR_LIFT:.2f} = {final_conv:.2f}"
                if devour_info["fired"]
                else f" (no devour; isagi {devour_info['reason']})"
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
            expected_action=f"{direction}_on_H4_close_USDCAD",
            coordinate=coord,
            decision_horizon=market.as_of,
            ttl_ticks=6,
            references=list(devour_info["references"]),
            read=ThoughtRead(
                signal_family="solo_king",
                direction_bias=direction,  # type: ignore[arg-type]
                regime_read=(
                    "devour_active" if devour_info["fired"] else "baseline_zone"
                ),
                expected_stop_pips=stop_pips,
                expected_r=r_expected,
                driving_evidence=(
                    "barou_usdcad_baseline_zone",
                    f"signal_reason:{sig.reason}",
                    *(
                        ("barou_devour_applied",)
                        if devour_info["fired"] else ()
                    ),
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
        # Phase O (2026-07-01): Barou's devour lift is computed in
        # ``observe`` via the ledger (F19/F20 aware). The F21 workspace
        # read here confirms Isagi's latest USDCAD direction at the tick
        # barrier for provenance -- feeds "workspace_isagi_direction"
        # into rationale so G7 C4 records Barou's workspace engagement.
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
        # Use the conviction from the observed Thought (so the devour
        # lift carries through to the Proposal as well).
        conviction = float(my_recent_thought.confidence_in_thought)
        horizon = market.as_of + timedelta(
            hours=float(self.canon_role.target_hold_hours),
        )
        # Phase W-barou v1.2 H2 defaults -- own geometry unless the
        # continuation-entry branch anchors a tighter stop below.
        own_stop_dist = abs(float(sig.entry) - float(sig.stop))
        final_stop = float(sig.stop)
        final_tp = float(sig.take_profit)
        continuation_entry = False
        v12_stop_source = "own"
        # F21 workspace read -- confirm Isagi's live USDCAD direction
        # AND read Bachira's same-symbol thought for Phase W-barou H1.
        workspace_isagi_direction: str | None = None
        workspace_isagi_disagrees: bool | None = None
        # Phase W-barou v1.1 (2026-07-03): H1 lone-conviction claim.
        # See experiments/phase_w_barou/PROTOCOL.md sec 3.
        bachira_read_present: bool = False
        bachira_same_direction: bool = False
        bachira_direction: str | None = None
        lone_conviction_active: bool = False
        lone_conviction_lift_applied: float = 0.0
        yield_reason: str = "workspace_unavailable"
        workspace_snapshot_ok: bool = workspace is not None
        if workspace is not None:
            latest_by_agent = workspace.latest_by_agent(symbol=market.symbol)
            isagi_t = latest_by_agent.get(BAROU_ISAGI_AGENT_ID)
            if isagi_t is not None and isagi_t.coordinate is not None:
                workspace_isagi_direction = str(isagi_t.coordinate.direction_bias)
                if workspace_isagi_direction in ("long", "short"):
                    workspace_isagi_disagrees = (
                        workspace_isagi_direction != direction
                    )
            # H1 gate: read Bachira's latest same-symbol thought.
            bachira_t = latest_by_agent.get(BAROU_BACHIRA_AGENT_ID)
            if bachira_t is not None and bachira_t.coordinate is not None:
                bachira_direction = str(bachira_t.coordinate.direction_bias)
                if bachira_direction in ("long", "short"):
                    bachira_read_present = True
                    bachira_same_direction = (bachira_direction == direction)
            # H1 decision table:
            #   bachira_read_present=False        -> H1 fires (genuine solo)
            #   bachira_same_direction=False      -> H1 fires (counter-conviction)
            #   bachira_same_direction=True       -> H1 skips (default devour path)
            if not bachira_read_present:
                lone_conviction_active = True
                yield_reason = "peer_did_not_read_this_setup"
            elif not bachira_same_direction:
                lone_conviction_active = True
                yield_reason = "peer_did_not_read_this_setup"
            else:
                yield_reason = "peer_claimed_slot_no_lift"
                # Phase W-barou v1.2 H2 (PROTOCOL_v1.2.md sec 3):
                # continuation entry on the exact branch H1 skips. Anchor
                # Barou's invalidation to Bachira's published structural
                # stop when it is tighter; entry stays Barou's own read;
                # TP re-derived so RR 1.5 is preserved. No conviction
                # change (V-b / v1.1 precedent: conviction lifts are dead
                # ends).
                if (
                    self._continuation_entry_enabled
                    and bachira_t is not None
                    and bachira_t.coordinate is not None
                ):
                    _b_stop = (
                        bachira_t.coordinate.rationale or {}
                    ).get("stop")
                    if isinstance(_b_stop, (int, float)):
                        (
                            final_stop,
                            final_tp,
                            v12_stop_source,
                            continuation_entry,
                        ) = continuation_anchor_geometry(
                            entry=float(sig.entry),
                            own_stop=float(sig.stop),
                            own_tp=float(sig.take_profit),
                            bachira_stop=float(_b_stop),
                            direction=direction,
                            target_rr=float(self._weapon_params["target_rr"]),
                        )
            if lone_conviction_active:
                lone_conviction_lift_applied = BAROU_V1_1_LONE_CONVICTION_LIFT
                conviction = min(
                    BAROU_V1_1_CONV_CAP,
                    conviction + BAROU_V1_1_LONE_CONVICTION_LIFT,
                )
                log.debug(
                    "[barou v1.1] H1 lone-conviction claim @ tick=%d %s "
                    "(%s): bachira_read=%s bachira_dir=%s conviction "
                    "+%.2f -> %.2f",
                    market.tick_id, market.symbol, direction,
                    bachira_read_present, bachira_direction,
                    BAROU_V1_1_LONE_CONVICTION_LIFT, conviction,
                )
        ladder = [LadderRung(price=float(final_tp), fraction=1.0)]
        meta = getattr(sig, "meta", {}) or {}
        devour_applied = "barou_devour_applied" in my_recent_thought.tags
        rationale: dict[str, Any] = {
            "wrapped": "agent.alphas.concepts.zone_alpha.SupplyDemandAlpha",
            "params": dict(self._weapon_params),
            "weapon": "barou_v13" if self._weapon_v13 else "barou_v1",
            "signal_reason": sig.reason,
            "htf_align": meta.get("htf_align"),
            "bar_index": int(i),
            "devour_applied": devour_applied,
            "base_conviction": float(sig.conviction),
            "final_conviction": conviction,
            "workspace_isagi_direction": workspace_isagi_direction,
            "workspace_isagi_disagrees": workspace_isagi_disagrees,
            # Phase V-b (2026-07-02, NULL RESULT): the specialist bit is
            # stamped for audit but no longer promotes ``_effective_tier``.
            # Walk-forward-post-V showed ZERO tick flips vs post-F22 --
            # the tier promotion doesn't tip the aggregator on USDCAD
            # because Isagi's conviction gap absorbs the TIER_BIAS margin.
            # See G7 PROTOCOL sec 11.9-postmortem 2026-07-02.
            "barou_solo_king_specialist": bool(devour_applied),
            # Phase W-barou v1.1 (2026-07-03): H1 lone-conviction claim.
            # See experiments/phase_w_barou/PROTOCOL.md sec 4.
            "barou_lone_conviction_claim": bool(lone_conviction_active),
            "barou_lone_conviction_lift_applied": float(
                lone_conviction_lift_applied
            ),
            "barou_v1_1_bachira_read_present": bool(bachira_read_present),
            "barou_v1_1_bachira_same_direction": bool(
                bachira_same_direction
            ),
            "barou_v1_1_bachira_direction": bachira_direction,
            "barou_workspace_snapshot_ok": bool(workspace_snapshot_ok),
            # Phase W-barou v1.2 (2026-07-06): H2 continuation-entry.
            # See experiments/phase_w_barou/PROTOCOL_v1.2.md sec 3.
            "barou_continuation_entry": bool(continuation_entry),
            "barou_v1_2_enabled": bool(self._continuation_entry_enabled),
            "barou_v1_2_stop_source": v12_stop_source,
            "barou_v1_2_stop_pips_own": float(own_stop_dist / _PIP),
            "barou_v1_2_stop_pips_final": float(
                abs(float(sig.entry) - final_stop) / _PIP
            ),
            "_yield_reason": yield_reason,
            "doctrine_ref": (
                "06-blue-lock-doctrine.md sec 3.4 (devour) + G7 PROTOCOL "
                "sec 11.9 Phase V-b null result (2026-07-02) + Phase "
                "W-barou v1.1 PROTOCOL (2026-07-03)"
            ),
            "empirical_prior": "E005 USDCAD baseline-zone +4.63 pips/trade",
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
            stop=float(final_stop),
            ladder=ladder,
            conviction=float(conviction),
            regime_fit=regime_fit_from_atr(prep.bars, i),
            valid_until=horizon,
            rationale=rationale,
            agent_tier=int(self.tier),
        )

    # ------------------------------------------------------------------
    # Devour mechanic
    # ------------------------------------------------------------------

    def _maybe_apply_devour(
        self,
        market: MarketState,
        ledger: ThoughtLedger,
        barou_direction: str,
    ) -> dict[str, Any]:
        """Return a dict describing the devour decision.

        Schema:
          fired (bool)               -- True iff lift applies
          isagi_direction (str|None) -- direction Isagi signalled
          isagi_conviction (float)   -- Isagi's strongest conviction
          references (list[str])     -- thought_ids of Isagi thoughts
          reason (str)               -- audit string for the narrative
        """
        peers = ledger.read(
            as_of=market.as_of,
            current_tick=market.tick_id,
            symbol=market.symbol,
        )
        isagi_thoughts = [
            t for t in peers
            if t.agent_id == self._isagi_agent_id
            and t.confidence_in_thought >= BAROU_V1_DEVOUR_OBS_FLOOR
            and t.coordinate is not None
        ]
        if not isagi_thoughts:
            return {
                "fired": False,
                "isagi_direction": None,
                "isagi_conviction": 0.0,
                "references": [],
                "reason": "silent_or_low_conviction",
            }
        # Take the most recent (highest tick_id), tiebreak on conviction.
        isagi_thoughts.sort(
            key=lambda t: (t.tick_id, t.confidence_in_thought),
            reverse=True,
        )
        latest = isagi_thoughts[0]
        isagi_dir = latest.coordinate.direction_bias
        # Devour fires only when Isagi disagrees directionally (the audit
        # asymmetry: EURUSD htf_against works, USDCAD baseline works).
        if isagi_dir in ("long", "short") and isagi_dir != barou_direction:
            return {
                "fired": True,
                "isagi_direction": isagi_dir,
                "isagi_conviction": float(latest.confidence_in_thought),
                "references": [latest.thought_id],
                "reason": "isagi_disagrees_devour_lift_applied",
            }
        return {
            "fired": False,
            "isagi_direction": isagi_dir,
            "isagi_conviction": float(latest.confidence_in_thought),
            "references": [latest.thought_id],
            "reason": (
                "isagi_agrees" if isagi_dir == barou_direction
                else f"isagi_direction_{isagi_dir!s}"
            ),
        }

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _abstain_thought(self, market: MarketState, *, reason: str) -> Thought:
        tags = [
            "canon:barou",
            "weapon:lone_wolf_baseline_zone",
            "barou_abstain",
            f"abstain_reason:{reason}",
        ]
        if reason == "off_symbol":
            tags.append("barou_abstain_symbol")
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[barou v1] {market.symbol} {market.timeframe} @ "
                f"{market.as_of} -- abstain ({reason}); USDCAD-only "
                "specialist."
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

    Mirrors the helper in `a01_isagi.py` -- price band = signal entry
    +/- stop distance, time window = target hold hours, regime
    predicate = literal "USDCAD_baseline_zone". The rationale carries
    the explicit entry/stop/tp so downstream agents (Nagi) can borrow
    them via coordinate.rationale.
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
        regime_predicate="USDCAD_baseline_zone_no_d1_gate",
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


# Backwards-compatible alias for v0.2 callers (tests, roster loaders).
BarouShoei = A7BarouV1
