"""A6 -- Seishiro Nagi v1 (`nagi_seishiro`) -- confluence-only striker.

Nagi v1 is the canonical chemical-reaction agent (doctrine
`06-blue-lock-doctrine.md` section 3.3 + roster `05-agent-roster-v0.md`
section 3.6). His weapon -- the "perfect trap" -- is the lowest-
frequency, highest-conviction-floor weapon in the squad: he emits a
Proposal only when peer Thoughts in the prior ticks overlap on tags
AND on coordinate.

Doctrine + roster constraints encoded here
------------------------------------------

* **Information tier** -- structurally Tier-2 by design (roster section
  3.6). Nagi without ledger access has no edge; his trigger IS the
  ledger. F17 measures the design empirically; in v1 we ship Tier-2
  full-ledger and run the F17 isolated arm in `run_phi4_squad_gate`.
* **Home TF** -- H4 for Phi4 v1 (matches Isagi v1 wrapper cadence so
  the chemical reaction has same-TF peers). Roster section 3.6 declares
  "multi-TF native" for the canonical agent; v1 ships single-TF.
* **Symbols** -- EURUSD, GBPUSD, USDCAD (matches the squad's tradable
  set; Barou's USDCAD-only restriction creates the only window where a
  2-distinct-peer confluence on USDCAD is even possible in the Phi4
  MVP).
* **One-bar lag** -- doctrine section 3.8 forbids same-tick reads
  between writer and reader agents. At tick T, Nagi sees only Thoughts
  with `tick_id < T` (enforced by `ThoughtLedger._apply_guards`). The
  confluence trigger is therefore evaluated against the PRIOR bar's
  peer Thoughts. This is the architecturally honest choice -- do not
  work around it. If the one-bar lag kills Nagi's signal frequency it
  is REPORTED, not fixed.

Trigger predicate (F11 + F13)
-----------------------------

For each pair (i, j) of distinct OTHER strikers' Thoughts in the read
window where BOTH:

1. `confidence_in_thought > 0.7` (high-conviction floor),
2. carry a `Coordinate` (not observation-only),
3. share the same `direction_bias`,
4. share at least 2 tags (the F13 tag-overlap predicate),
5. price bands intersect (the F13 binary coordinate-overlap predicate
   -- `Coordinate.price_lo`/`price_hi` boxes have non-empty
   intersection),

we declare a chemical reaction. Conviction lift via independent-OR
(F11):

    c_combined = 1 - prod_i (1 - c_i)

(For v1 we treat ego_i = 1.0 for every peer; the principled-form ego
in doctrine 3.1.b is a Phi4+ wiring.)

If multiple pairs trigger, the highest-combined-conviction pair wins
(deterministic tiebreaker on `agent_id` sort then `tick_id`).

When the trigger fires, `observe` returns a Thought tagged
`nagi_confluence` carrying the lifted conviction and a Coordinate that
is the intersection of the two source price bands. `intend` (at H4
close) then mirrors the leader's direction/entry/stop/tp from the
leader's coordinate rationale -- so Nagi's order is a continuation of
the same trade idea the leader proposed, but credited as a chemical-
reaction firing on the ledger (the F12 `beauty_bonus` will apply once
the F11 layer is fully wired into the trade scorer in a later phase).

Empirical prior (audit `2026-06-24_E001-E007_audit.md` section 2.6,
4.3): H1 `equal_highs_pool` lifts every M15 setup by +0.10..+0.46 ATR
(exploratory, displacement-null). This is the canon evidence for the
late-fusion frame -- context primitive amplifies setup primitive --
that Nagi v1 instantiates with `equal_highs_pool` standing in for any
peer-coordinate overlap on the H4 timeframe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from agent.squad.ledger import ThoughtLedger
from agent.squad.provenance_pips import (
    regime_fit_from_atr_pips,
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

# ---------------------------------------------------------------------------
# Locked Phi4 v1 parameters.
# ---------------------------------------------------------------------------
NAGI_V1_CONFIDENCE_FLOOR: float = 0.7        # peers below this don't count
NAGI_V1_MIN_SHARED_TAGS: int = 2             # F13 tag-overlap predicate
NAGI_V1_MIN_DISTINCT_PEERS: int = 2          # >= 2 OTHER strikers
NAGI_V1_REGIME_FIT: float = 0.5              # placeholder; Phi5 wires F18
NAGI_V1_VALID_HOURS: float = 24.0            # proposal staleness window
NAGI_V1_TTL_TICKS: int = 6                   # confluence Thought stays
                                              # visible for ~ 1 day at H4
NAGI_V1_OBS_TTL_TICKS: int = 1               # observation-only TTL

NAGI_V1_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")

NAGI_V1_CANON_ROLE = CanonRole(
    canon_player="nagi_seishiro",
    weapon="perfect_trap_chemical_reaction_v1",
    ego=0.45,
    target_hold_hours=24.0,
    narrative_voice="confluence_only_perfect_trap",
)


# ---------------------------------------------------------------------------
# Helper containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Pair:
    """One detected (a, b) chemical-reaction pair."""

    a: Thought
    b: Thought
    shared_tags: frozenset[str]
    combined_conviction: float


def _coordinates_overlap(c_a: Coordinate, c_b: Coordinate) -> bool:
    """F13 binary coordinate-overlap predicate.

    Two coordinates overlap iff they cover the same symbol, share a
    compatible direction bias, and their price bands have non-empty
    intersection. (Time windows overlap by construction within the
    `ttl_ticks` read window.)
    """
    if c_a.symbol != c_b.symbol:
        return False
    if c_a.direction_bias not in ("long", "short", "either"):
        return False
    if c_b.direction_bias not in ("long", "short", "either"):
        return False
    if c_a.direction_bias != "either" and c_b.direction_bias != "either":
        if c_a.direction_bias != c_b.direction_bias:
            return False
    return not (c_a.price_hi < c_b.price_lo or c_b.price_hi < c_a.price_lo)


def _find_best_pair(thoughts: list[Thought]) -> Optional[_Pair]:
    """Pick the highest-combined-conviction (i, j) pair satisfying every
    F11/F13 predicate. Deterministic on tied combined-conviction by
    sorting on `(agent_id, tick_id)` of the participants.
    """
    # Index by (agent_id, tick_id) for deterministic ordering.
    sorted_thoughts = sorted(
        thoughts, key=lambda t: (t.agent_id, t.tick_id, t.thought_id),
    )
    best: Optional[_Pair] = None
    for i, a in enumerate(sorted_thoughts):
        for b in sorted_thoughts[i + 1:]:
            if a.agent_id == b.agent_id:
                continue  # need distinct peers
            if a.coordinate is None or b.coordinate is None:
                continue
            if a.confidence_in_thought < NAGI_V1_CONFIDENCE_FLOOR:
                continue
            if b.confidence_in_thought < NAGI_V1_CONFIDENCE_FLOOR:
                continue
            shared = frozenset(a.tags) & frozenset(b.tags)
            if len(shared) < NAGI_V1_MIN_SHARED_TAGS:
                continue
            if not _coordinates_overlap(a.coordinate, b.coordinate):
                continue
            c_a = float(a.confidence_in_thought)
            c_b = float(b.confidence_in_thought)
            combined = 1.0 - (1.0 - c_a) * (1.0 - c_b)
            pair = _Pair(
                a=a, b=b, shared_tags=shared,
                combined_conviction=float(combined),
            )
            if best is None or pair.combined_conviction > best.combined_conviction:
                best = pair
    return best


def _intersect_price_band(
    c_a: Coordinate, c_b: Coordinate,
) -> tuple[float, float]:
    lo = max(c_a.price_lo, c_b.price_lo)
    hi = min(c_a.price_hi, c_b.price_hi)
    if not (lo <= hi):
        # Degenerate -- caller filters out non-overlapping pairs first.
        lo, hi = min(lo, hi), max(lo, hi)
    return float(lo), float(hi)


def _leader_thought(pair: _Pair) -> Thought:
    """Pick the higher-conviction member of `pair` as the leader.

    Tiebreaker: lexicographic on (agent_id, tick_id, thought_id) -- the
    same deterministic order used by `_find_best_pair`.
    """
    a, b = pair.a, pair.b
    if a.confidence_in_thought > b.confidence_in_thought:
        return a
    if a.confidence_in_thought < b.confidence_in_thought:
        return b
    # Tied -- deterministic.
    key_a = (a.agent_id, a.tick_id, a.thought_id)
    key_b = (b.agent_id, b.tick_id, b.thought_id)
    return a if key_a <= key_b else b


class A6NagiV1(BaseStriker):
    """A6 Nagi v1 -- confluence-only chemical-reaction striker.

    `observe(market, ledger)` reads PRIOR-tick peer Thoughts (ledger
    guards enforce `tick_id < current_tick`), looks for a high-
    conviction overlapping pair on `market.symbol`, and emits either a
    confluence-firing Thought (with conviction, coordinate, and the
    `nagi_confluence` tag) or an observation-only Thought.

    `intend(market, my_recent_thought)` fires at H4 close iff the
    current Thought is a confluence-firing one. The Proposal mirrors
    the LEADER peer's entry/stop/tp (from the leader's coordinate
    rationale) under the F11 lifted conviction.
    """

    def __init__(
        self,
        agent_id: str = "nagi_seishiro",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or NAGI_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(NAGI_V1_SYMBOLS),
            playstyle="confluence_only",
            tier=2,
        )

    # ------------------------------------------------------------------
    # observe
    # ------------------------------------------------------------------

    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought:
        peers = ledger.read(
            as_of=market.as_of,
            current_tick=market.tick_id,
            symbol=market.symbol,
        )
        # Exclude Nagi's own prior thoughts -- confluence requires OTHERS.
        peer_thoughts = [t for t in peers if t.agent_id != self.agent_id]
        pair = _find_best_pair(peer_thoughts)

        if pair is None:
            return self._observation_thought(
                market=market,
                n_peers_seen=len(peer_thoughts),
            )

        return self._firing_thought(market=market, pair=pair)

    # ------------------------------------------------------------------
    # intend
    # ------------------------------------------------------------------

    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
        *,
        workspace: WorkspaceSnapshot | None = None,
        **_kwargs: object,
    ) -> AgentProposal | None:
        # Phase O (2026-07-01): Nagi's confluence predicate is fed by
        # ledger reads via ``observe`` (F11 union predicate). The F21
        # workspace read here is a diagnostic mirror -- counts peer
        # thoughts visible at the tick barrier so G7 C4 records Nagi's
        # workspace engagement. Redundant with ledger for the decision,
        # but truthful for the chemistry metric.
        if market.timeframe != self.home_tf:
            return None
        if my_recent_thought.coordinate is None:
            return None
        if "nagi_confluence" not in my_recent_thought.tags:
            return None
        if my_recent_thought.confidence_in_thought < NAGI_V1_CONFIDENCE_FLOOR:
            return None

        leader = my_recent_thought.coordinate.rationale.get("leader", {})
        direction = my_recent_thought.coordinate.direction_bias
        if direction not in ("long", "short"):
            return None  # Nagi v1 does not trade "either".

        # Leader rationale carries the concrete entry/stop/tp from the
        # source peer (e.g. Isagi's zone-touch trade plan). Borrow it
        # verbatim -- Nagi's value-add is the lift, not a new price
        # plan.
        try:
            entry = float(leader["entry"])
            stop = float(leader["stop"])
            tp = float(leader["take_profit"])
        except (KeyError, TypeError, ValueError):
            return None

        ladder = [LadderRung(price=float(tp), fraction=1.0)]
        valid_until = market.as_of + timedelta(hours=NAGI_V1_VALID_HOURS)

        # Dispersion-r2 (2026-07-14, doctrine §4.1a amendment +
        # experiments/dispersion_primitives_r2/PROTOCOL.md §2.3): Nagi
        # has no bar access by design, so he BORROWS the leader's
        # stamped volatility provenance the same way he borrows the
        # trade plan. G7 §11.13 measured C5/C6 CV = 0.000 because
        # atr_pips was never stamped (evaluator constant fallback) and
        # regime_fit was the 0.5 placeholder.
        def _num(v: Any) -> float | None:
            return float(v) if isinstance(v, (int, float)) else None

        borrowed_atr_pips = _num(leader.get("atr_pips"))
        borrowed_h1_swing_pips = _num(leader.get("h1_swing_pips"))
        regime_fit = regime_fit_from_atr_pips(borrowed_atr_pips)

        # F21 workspace read -- confluence diagnostic mirror of the
        # ledger predicate. Counts peer directional agreement at the
        # tick barrier.
        workspace_peer_count = 0
        workspace_peers_agree = 0
        if workspace is not None:
            peers = workspace.peer_thoughts(agent_id=self.agent_id)
            workspace_peer_count = len(peers)
            for peer_t in peers:
                if peer_t.coordinate is None:
                    continue
                peer_dir = str(peer_t.coordinate.direction_bias)
                if peer_dir == direction:
                    workspace_peers_agree += 1

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
            regime_fit=regime_fit,
            valid_until=valid_until,
            rationale={
                "wrapped": "nagi_confluence_v1",
                "leader_agent_id": leader.get("agent_id"),
                "leader_thought_id": leader.get("thought_id"),
                # Dispersion-r2: borrowed provenance flows into the
                # trade record's source_atr_pips / source_h1_swing_pips
                # via _annotate_trade_record (F20 inputs).
                "atr_pips": borrowed_atr_pips,
                "h1_swing_pips": borrowed_h1_swing_pips,
                "regime_fit_source": "leader_atr_pips_phase_s_map",
                "combined_conviction": float(
                    my_recent_thought.confidence_in_thought
                ),
                "shared_tags": list(
                    my_recent_thought.coordinate.rationale.get("shared_tags", [])
                ),
                "one_bar_lag_intentional": True,
                "workspace_peer_count": int(workspace_peer_count),
                "workspace_peers_agree": int(workspace_peers_agree),
                "doctrine_ref": "06-blue-lock-doctrine.md sec 3.3 + sec 3.8",
            },
            agent_tier=int(self.tier),
        )

    # ------------------------------------------------------------------
    # private builders
    # ------------------------------------------------------------------

    def _observation_thought(
        self,
        *,
        market: MarketState,
        n_peers_seen: int,
    ) -> Thought:
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=(
                f"[nagi v1] {market.symbol} {market.timeframe} @ "
                f"{market.as_of} -- {n_peers_seen} peer thoughts in "
                "window; no high-conviction tag+coord overlap; waiting."
            ),
            tags=[
                "confluence_seeker",
                "canon:nagi",
                "weapon:perfect_trap",
            ],
            confidence_in_thought=0.0,
            expected_action="wait",
            coordinate=None,
            decision_horizon=market.as_of,
            ttl_ticks=NAGI_V1_OBS_TTL_TICKS,
            references=[],
        )

    def _firing_thought(self, *, market: MarketState, pair: _Pair) -> Thought:
        leader = _leader_thought(pair)
        other = pair.b if leader is pair.a else pair.a
        assert leader.coordinate is not None and other.coordinate is not None
        lo, hi = _intersect_price_band(leader.coordinate, other.coordinate)
        # Leader's rationale carries the explicit entry/stop/tp (Isagi
        # writes these). Nagi rebroadcasts so `intend` can read them
        # from `my_recent_thought` alone.
        leader_rationale: dict[str, Any] = dict(leader.coordinate.rationale)
        leader_rationale.update({
            "agent_id": leader.agent_id,
            "thought_id": leader.thought_id,
            "conviction": float(leader.confidence_in_thought),
        })
        coord = Coordinate(
            agent_id=self.agent_id,
            symbol=market.symbol,
            price_lo=float(lo),
            price_hi=float(hi),
            time_start=market.as_of,
            time_end=market.as_of + timedelta(hours=NAGI_V1_VALID_HOURS),
            vol_band=leader.coordinate.vol_band,
            regime_predicate="chemical_reaction_v1",
            expected_strength=float(pair.combined_conviction),
            direction_bias=leader.coordinate.direction_bias,
            rationale={
                "leader": leader_rationale,
                "other_agent_id": other.agent_id,
                "other_thought_id": other.thought_id,
                "shared_tags": sorted(pair.shared_tags),
                "combined_conviction": float(pair.combined_conviction),
                "f11_formula": "1 - prod(1 - c_i)",
            },
        )
        narrative = (
            f"[nagi v1] {market.symbol} {market.timeframe} @ "
            f"{market.as_of} -- chemical reaction: "
            f"{leader.agent_id} + {other.agent_id} overlap on "
            f"{len(pair.shared_tags)} tags & coordinate; combined "
            f"conviction {pair.combined_conviction:.2f} (F11 OR)."
        )
        # Tag union: own tags + shared peer tags + a confluence marker.
        tags = sorted({
            "nagi_confluence",
            "canon:nagi",
            "weapon:perfect_trap",
            "f11_chemical_reaction",
            *pair.shared_tags,
            f"leader:{leader.agent_id}",
            f"peer:{other.agent_id}",
        })
        leader_read = leader.read
        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative=narrative,
            tags=tags,
            confidence_in_thought=float(pair.combined_conviction),
            expected_action=(
                f"{coord.direction_bias}_on_chemical_reaction"
                if coord.direction_bias in ("long", "short")
                else "wait"
            ),
            coordinate=coord,
            decision_horizon=market.as_of,
            ttl_ticks=NAGI_V1_TTL_TICKS,
            references=[leader.thought_id, other.thought_id],
            read=ThoughtRead(
                signal_family="confluence",
                direction_bias=coord.direction_bias,  # type: ignore[arg-type]
                regime_read=(
                    leader_read.regime_read
                    if leader_read is not None else "chemical_reaction"
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
                    "nagi_confluence",
                    "f11_chemical_reaction",
                    f"leader:{leader.agent_id}",
                    f"peer:{other.agent_id}",
                    *tuple(sorted(pair.shared_tags))[:3],
                ),
            ),
        )


# Backwards-compatible alias for v0.2 callers (tests, roster loaders).
NagiSeishiro = A6NagiV1
