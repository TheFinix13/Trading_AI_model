"""A5 -- Reo Mikage v1 (`reo_mikage`) -- chameleon pass-master.

Reo is the chameleon (roster `05-agent-roster-v0.md` section 3.5,
doctrine `06-blue-lock-doctrine.md` section 3.1 -- "adaptive
copying"). His canonical weapon is regime-conditional dynamic copying:
he mimics the trailing-K-week TQS leader. The v1 implementation ships
a simpler instance of that pattern -- a **per-tick mirror** -- because
the trailing-K-week leader-tracker depends on the harness ledger
infrastructure that lands in Φ5+.

What Reo v1 does (deliberately scoped)
--------------------------------------

Reo reads the prior-tick ledger for high-conviction peer Thoughts on
the current market symbol. If exactly one peer Thought qualifies (or
multiple, in which case Reo picks the highest-conviction one,
deterministic on `(agent_id, tick_id)`), Reo emits a "mirror" Thought:

* coordinate = leader.coordinate with a HUMILITY MARGIN
  (price band widened by 20 %, time end pulled in by 25 %);
* conviction = min(1.0, leader.confidence_in_thought + REO_LIFT)
  where `REO_LIFT = 0.10`;
* tags = `["canon:reo", "weapon:chameleon", "reo_mirror",
           f"mirroring:{leader.agent_id}",
           "reo_humility_margin"]` + leader's tags
  (so Reo automatically shares the 2-tags-overlap floor with the
  leader, AND with any agent that already shared tags with the leader);
* direction = leader.direction (no flip; Reo defers, never disagrees).

`intend()` ALWAYS RETURNS None. Reo never trades in v1 -- he is the
chemical-reaction-only voice. His value to the squad is **structural**:
on every tick where some peer fires at conviction >= REO_OBSERVE_FLOOR,
Reo emits a SECOND high-conviction Thought with the same coordinate and
shared tags. That is exactly what Nagi's F11/F13 chemical-reaction
predicate needs.

Why this is the Φ4.1 predicate-starvation test
----------------------------------------------

The Φ4 gate FAILed at 0.98x Isagi-alone TQS, and Nagi fired 0
confluence thoughts because the 2-distinct-peer floor was structurally
unreachable. Two readings of that failure compete:

1. **Predicate starvation**: not enough tradable peers per symbol per
   tick. Solved by adding more strikers (A2 Bachira, A3 Rin, A4
   Chigiri).
2. **Conviction floor too tight**: even with more peers, the
   production cell's 0.65 base conviction is below Nagi's 0.7 floor,
   so peer firings don't qualify.

Reo v1 isolates reading #1. By construction Reo's mirror lifts ANY
peer Thought with conviction >= 0.6 to a Nagi-qualifying 0.7+, so if
even ONE other peer fires at any tick Reo will be a second qualified
peer for Nagi. If Nagi STILL doesn't fire with Reo in the mix, the
problem is not predicate starvation -- it's a deeper issue (coordinate
non-overlap, tag mismatch, or one-bar lag).

Cleanly: Reo is the **falsifier** for the "predicate starvation
hypothesis". If Φ4.1 shows Nagi firing > 0 thoughts, the hypothesis is
confirmed; if it shows 0 thoughts even with Reo, we report that
honestly and look elsewhere.

Information tier
----------------

**Structural Tier 2 by design.** Reo's weapon IS reading the ledger;
he cannot exist as Tier-3. F17 ΔInfo is still measured for the audit
trail (an isolated Reo with `RedactedLedger(self_only)` will produce 0
mirror Thoughts -- the F17 isolated arm reveals the design via the
trade count, not via the TQS distribution).

The roster section 3.5 defeat-trigger language ("v1 ΔInfo <= 0 -> Reo
is cut") applies; v1 is a starvation-test ship, not a proven
edge contributor.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from agent.squad.ledger import ThoughtLedger
from agent.squad.striker import BaseStriker
from agent.squad.types import (
    SCHEMA_VERSION,
    AgentProposal,
    CanonRole,
    Coordinate,
    MarketState,
    Thought,
    ThoughtRead,
)


# ---------------------------------------------------------------------------
# Locked Φ4.1 v1 parameters.
# ---------------------------------------------------------------------------
REO_V1_OBSERVE_FLOOR: float = 0.60          # peers below this not mirrored
REO_V1_LIFT: float = 0.10                   # add to leader.confidence
REO_V1_CONV_CAP: float = 1.0
REO_V1_BAND_WIDEN_FRAC: float = 0.20        # humility: 20% wider band
REO_V1_TIME_SHORTEN_FRAC: float = 0.25      # humility: 25% shorter window
REO_V1_TTL_TICKS: int = 6
REO_V1_OBS_TTL_TICKS: int = 1

REO_V1_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")

REO_V1_CANON_ROLE = CanonRole(
    canon_player="reo_mikage",
    weapon="chameleon_per_tick_mirror_v1",
    ego=0.30,
    target_hold_hours=0.0,   # never trades
    narrative_voice="adaptive_mirror_pass_master",
)


class A5ReoV1(BaseStriker):
    """A5 Reo v1 -- per-tick chameleon mirror.

    Public surface (engine):
      * `observe(market, ledger)` -- reads prior-tick peer Thoughts on
        `market.symbol`; mirrors the highest-conviction qualifying one
        (conviction >= REO_V1_OBSERVE_FLOOR, has Coordinate, not Reo
        itself). Emits an observation-only Thought when no qualifying
        leader exists.
      * `intend(market, my_recent_thought)` -- ALWAYS returns None.

    No `prepare()` needed -- Reo has no inner alpha to seed.
    """

    def __init__(
        self,
        agent_id: str = "reo_mikage",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or REO_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(REO_V1_SYMBOLS),
            playstyle="copier_hrp",
            tier=2,
        )

    # ------------------------------------------------------------------
    # BlueLockStriker contract
    # ------------------------------------------------------------------

    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought:
        peers = ledger.read(
            as_of=market.as_of,
            current_tick=market.tick_id,
            symbol=market.symbol,
        )
        # Filter: not Reo, has a Coordinate, conviction floor met,
        # direction is a real long/short (not "flat" / "either").
        qualified = [
            t for t in peers
            if t.agent_id != self.agent_id
            and t.coordinate is not None
            and t.confidence_in_thought >= REO_V1_OBSERVE_FLOOR
            and t.coordinate.direction_bias in ("long", "short")
        ]
        if not qualified:
            return self._observation_only(market=market, n_peers=len(peers))

        leader = _pick_leader(qualified)
        return self._mirror_thought(market=market, leader=leader)

    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
        **_kwargs: object,
    ) -> AgentProposal | None:
        # Reo v1 never proposes. Roster section 3.5 + the Φ4.1 design
        # note: Reo's value is to feed Nagi's chemical-reaction
        # predicate without contributing trades. Lifts the predicate
        # frequency without contesting the squad's risk budget.
        # ``_kwargs`` absorbs the F21 ``workspace`` kwarg.
        return None

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _mirror_thought(
        self, *, market: MarketState, leader: Thought,
    ) -> Thought:
        assert leader.coordinate is not None
        lc = leader.coordinate
        mirrored_band = _widen_band(
            lo=float(lc.price_lo), hi=float(lc.price_hi),
            widen_frac=REO_V1_BAND_WIDEN_FRAC,
        )
        # Time window humility: pull the end 25% closer to the start.
        time_total_sec = (lc.time_end - lc.time_start).total_seconds()
        shortened_sec = max(
            0.0, time_total_sec * (1.0 - REO_V1_TIME_SHORTEN_FRAC),
        )
        mirrored_time_end = lc.time_start + timedelta(seconds=shortened_sec)
        final_conv = min(
            REO_V1_CONV_CAP,
            float(leader.confidence_in_thought) + REO_V1_LIFT,
        )
        # Tag set: union of leader tags + Reo's marker tags. The leader
        # tags carry through verbatim so any agent that paired with the
        # leader (e.g. Isagi via `zone_d1_against`) also pairs with
        # Reo's mirror.
        reo_tags = [
            "canon:reo",
            "weapon:chameleon",
            "reo_mirror",
            f"mirroring:{leader.agent_id}",
            "reo_humility_margin",
            f"reo_lift:{REO_V1_LIFT:.2f}",
        ]
        merged_tags = sorted(set(reo_tags) | set(leader.tags))
        mirror_coord = Coordinate(
            agent_id=self.agent_id,
            symbol=market.symbol,
            price_lo=float(mirrored_band[0]),
            price_hi=float(mirrored_band[1]),
            time_start=lc.time_start,
            time_end=mirrored_time_end,
            vol_band=lc.vol_band,
            regime_predicate=f"reo_mirror_of:{leader.agent_id}",
            expected_strength=float(final_conv),
            direction_bias=lc.direction_bias,
            rationale={
                "mirrored_agent_id": leader.agent_id,
                "mirrored_thought_id": leader.thought_id,
                "leader_base_conviction": float(leader.confidence_in_thought),
                "reo_lift": REO_V1_LIFT,
                "final_conviction": float(final_conv),
                "humility_band_widen_frac": REO_V1_BAND_WIDEN_FRAC,
                "humility_time_shorten_frac": REO_V1_TIME_SHORTEN_FRAC,
                # Preserve the leader's entry/stop/tp so downstream
                # chemical-reaction agents (Nagi) can introspect Reo's
                # provenance and copy the original trade plan.
                "leader_rationale": dict(lc.rationale),
            },
        )
        narrative = (
            f"[reo v1] {market.symbol} {market.timeframe} @ "
            f"{market.as_of} -- mirroring {leader.agent_id} "
            f"({lc.direction_bias}, base_conv "
            f"{leader.confidence_in_thought:.2f}); humility margin: "
            f"band x{1.0 + REO_V1_BAND_WIDEN_FRAC:.2f}, time "
            f"x{1.0 - REO_V1_TIME_SHORTEN_FRAC:.2f}; mirror conv "
            f"{final_conv:.2f}."
        )
        # Reo copies the leader's direction; carry the leader's `read`
        # forward if it has one, otherwise synthesise from the coordinate.
        leader_read = leader.read
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=narrative,
            tags=merged_tags,
            confidence_in_thought=float(final_conv),
            expected_action=f"mirror_{lc.direction_bias}",
            coordinate=mirror_coord,
            decision_horizon=market.as_of,
            ttl_ticks=REO_V1_TTL_TICKS,
            references=[leader.thought_id],
            read=ThoughtRead(
                signal_family="adaptive_copy",
                direction_bias=lc.direction_bias,  # type: ignore[arg-type]
                regime_read=(
                    leader_read.regime_read
                    if leader_read is not None else "mirror"
                ),
                expected_stop_pips=(
                    leader_read.expected_stop_pips
                    if leader_read is not None else None
                ),
                expected_r=(
                    leader_read.expected_r
                    if leader_read is not None else None
                ),
                driving_evidence=(
                    "reo_mirror",
                    f"mirroring:{leader.agent_id}",
                    *(leader_read.driving_evidence if leader_read is not None else ()),
                ),
            ),
        )

    def _observation_only(
        self, *, market: MarketState, n_peers: int,
    ) -> Thought:
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[reo v1] {market.symbol} {market.timeframe} @ "
                f"{market.as_of} -- {n_peers} peer thoughts visible; "
                "no qualifying leader (conviction or coordinate gate)."
            ),
            tags=[
                "canon:reo",
                "weapon:chameleon",
                "reo_observation_clean",
            ],
            confidence_in_thought=0.0,
            expected_action="wait",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=REO_V1_OBS_TTL_TICKS,
            references=[],
        )


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------

def _pick_leader(qualified: list[Thought]) -> Thought:
    """Deterministic leader selection.

    Highest `confidence_in_thought` wins; ties broken on
    `(tick_id desc, agent_id asc, thought_id asc)` so the most recent
    high-conviction Thought is preferred, and a hard string ordering
    fully resolves any ties.
    """
    return max(
        qualified,
        key=lambda t: (
            float(t.confidence_in_thought),
            int(t.tick_id),
            -1,  # placeholder so the next two strings are tiebreakers
        ),
    ) if False else _max_with_string_tiebreak(qualified)


def _max_with_string_tiebreak(qualified: list[Thought]) -> Thought:
    """`max` with multi-key deterministic tiebreak.

    Sort key chosen so:
      1. higher conviction wins
      2. then more recent tick_id
      3. then lexicographically lowest agent_id
      4. then lexicographically lowest thought_id
    """
    return sorted(
        qualified,
        key=lambda t: (
            -float(t.confidence_in_thought),
            -int(t.tick_id),
            str(t.agent_id),
            str(t.thought_id),
        ),
    )[0]


def _widen_band(*, lo: float, hi: float, widen_frac: float) -> tuple[float, float]:
    """Symmetric humility band widening around the midpoint."""
    mid = 0.5 * (lo + hi)
    half = 0.5 * (hi - lo)
    new_half = half * (1.0 + float(widen_frac))
    return mid - new_half, mid + new_half


# Backwards-compatible alias for roster loaders.
ReoMikage = A5ReoV1
