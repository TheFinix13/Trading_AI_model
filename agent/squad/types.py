"""Typed objects shared by every squad agent and kernel stage.

Ported v1 (unvalidated port) from the research repo:
``finance-research-experiments/programs/M001_multi_agent_ensemble/
sim/core/types.py`` @ commit e084c5b (2026-07-14). Deliberate,
user-authorized reimplementation of validated v1 mechanics -- research
code itself is never imported into this repo.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

SCHEMA_VERSION = 1

Symbol = str
SquadTimeframe = Literal["M1", "M5", "M15", "H1", "H4", "D1"]
SquadDirection = Literal["long", "short", "flat", "either"]


def _iso(ts: datetime | str) -> str:
    if isinstance(ts, str):
        return ts
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


@dataclass(frozen=True)
class Coordinate:
    """Forward-looking claim of where + when an A+ setup will materialise."""

    agent_id: str
    symbol: Symbol
    price_lo: float
    price_hi: float
    time_start: datetime
    time_end: datetime
    vol_band: tuple[float, float]
    regime_predicate: str
    expected_strength: float
    direction_bias: SquadDirection
    rationale: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "symbol": self.symbol,
            "price_lo": float(self.price_lo),
            "price_hi": float(self.price_hi),
            "time_start": _iso(self.time_start),
            "time_end": _iso(self.time_end),
            "vol_band": [float(self.vol_band[0]), float(self.vol_band[1])],
            "regime_predicate": self.regime_predicate,
            "expected_strength": float(self.expected_strength),
            "direction_bias": self.direction_bias,
            "rationale": self.rationale,
        }


# F22a canonical signal families (one per agent).
SignalFamily = Literal[
    "metavision",         # A1 Isagi
    "pattern_rebel",      # A2 Bachira
    "precision",          # A3 Rin
    "breakout",           # A4 Chigiri
    "adaptive_copy",      # A5 Reo
    "confluence",         # A6 Nagi
    "solo_king",          # A7 Barou
    "risk_watch",         # A10 Kunigami (Sentinel R5 side channel only)
    "unknown",
]


@dataclass(frozen=True)
class ThoughtRead:
    """F22a -- structured semantic content of a Thought."""

    signal_family: SignalFamily
    direction_bias: SquadDirection
    regime_read: str = "unknown"
    expected_stop_pips: float | None = None
    expected_r: float | None = None
    driving_evidence: tuple[str, ...] = ()

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "signal_family": self.signal_family,
            "direction_bias": self.direction_bias,
            "regime_read": self.regime_read,
            "expected_stop_pips": (
                float(self.expected_stop_pips)
                if self.expected_stop_pips is not None
                else None
            ),
            "expected_r": (
                float(self.expected_r) if self.expected_r is not None else None
            ),
            "driving_evidence": list(self.driving_evidence),
        }


@dataclass(frozen=True)
class Thought:
    """One agent's per-tick narrative + optional coordinate."""

    schema_version: int
    agent_id: str
    tick_id: int
    timestamp: datetime
    symbol: Symbol
    narrative: str
    tags: list[str]
    confidence_in_thought: float
    expected_action: str | None
    coordinate: Coordinate | None
    decision_horizon: datetime
    ttl_ticks: int
    references: list[str]
    thought_id: str = ""
    read: ThoughtRead | None = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence_in_thought <= 1.0):
            raise ValueError(
                f"confidence_in_thought out of bounds: {self.confidence_in_thought}"
            )
        if self.ttl_ticks < 0:
            raise ValueError(f"ttl_ticks negative: {self.ttl_ticks}")
        if not self.thought_id:
            object.__setattr__(
                self,
                "thought_id",
                f"{self.agent_id}:{self.tick_id}:{self.symbol}",
            )

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "thought_id": self.thought_id,
            "agent_id": self.agent_id,
            "tick_id": int(self.tick_id),
            "timestamp": _iso(self.timestamp),
            "symbol": self.symbol,
            "narrative": self.narrative,
            "tags": list(self.tags),
            "confidence_in_thought": float(self.confidence_in_thought),
            "expected_action": self.expected_action,
            "coordinate": (
                self.coordinate.to_jsonable() if self.coordinate else None
            ),
            "decision_horizon": _iso(self.decision_horizon),
            "ttl_ticks": int(self.ttl_ticks),
            "references": list(self.references),
            "read": self.read.to_jsonable() if self.read is not None else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_jsonable(), sort_keys=True)


@dataclass(frozen=True)
class YieldReason:
    """F22c -- audit-trail record for a striker who looked and chose not to fire."""

    agent_id: str
    tick_id: int
    symbol: Symbol
    reason: str
    peer_ids_read: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)
    doctrine_ref: str = ""

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tick_id": int(self.tick_id),
            "symbol": self.symbol,
            "reason": self.reason,
            "peer_ids_read": list(self.peer_ids_read),
            "evidence": dict(self.evidence),
            "doctrine_ref": self.doctrine_ref,
        }


@dataclass(frozen=True)
class LadderRung:
    """One partial-exit rung on a proposal's ladder."""

    price: float
    fraction: float


@dataclass(frozen=True)
class AgentProposal:
    """A per-home-TF-close intent to trade."""

    agent_id: str
    tick_id: int
    source_thought_id: str
    timestamp: datetime
    symbol: Symbol
    direction: SquadDirection
    entry: float
    stop: float
    ladder: list[LadderRung]
    conviction: float
    regime_fit: float
    valid_until: datetime
    rationale: dict[str, Any] = field(default_factory=dict)
    agent_tier: int = 2

    def __post_init__(self) -> None:
        if self.direction not in ("long", "short", "flat"):
            raise ValueError(f"invalid direction: {self.direction}")
        if not (0.0 <= self.conviction <= 1.0):
            raise ValueError(f"conviction out of bounds: {self.conviction}")
        if not (0.0 <= self.regime_fit <= 1.0):
            raise ValueError(f"regime_fit out of bounds: {self.regime_fit}")
        if self.agent_tier not in (1, 2, 3):
            raise ValueError(f"agent_tier must be 1/2/3, got {self.agent_tier}")
        if self.direction in ("long", "short"):
            total = sum(r.fraction for r in self.ladder)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(
                    f"ladder fractions sum to {total:.6f}, must sum to 1.0"
                )
            if self.stop <= 0:
                raise ValueError(f"stop must be positive: {self.stop}")

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tick_id": int(self.tick_id),
            "source_thought_id": self.source_thought_id,
            "timestamp": _iso(self.timestamp),
            "symbol": self.symbol,
            "direction": self.direction,
            "entry": float(self.entry),
            "stop": float(self.stop),
            "ladder": [
                {"price": float(r.price), "fraction": float(r.fraction)}
                for r in self.ladder
            ],
            "conviction": float(self.conviction),
            "regime_fit": float(self.regime_fit),
            "valid_until": _iso(self.valid_until),
            "rationale": self.rationale,
            "agent_tier": int(self.agent_tier),
        }


@dataclass(frozen=True)
class OrderIntent:
    """Aggregator output: a concrete order for downstream (Sentinel path)."""

    intent_id: str
    tick_id: int
    timestamp: datetime
    symbol: Symbol
    direction: SquadDirection
    entry: float
    stop: float
    size: float
    ladder: list[LadderRung]
    contributing_thought_ids: list[str]
    contributing_proposal_ids: list[str]
    rationale: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "tick_id": int(self.tick_id),
            "timestamp": _iso(self.timestamp),
            "symbol": self.symbol,
            "direction": self.direction,
            "entry": float(self.entry),
            "stop": float(self.stop),
            "size": float(self.size),
            "ladder": [
                {"price": float(r.price), "fraction": float(r.fraction)}
                for r in self.ladder
            ],
            "contributing_thought_ids": list(self.contributing_thought_ids),
            "contributing_proposal_ids": list(self.contributing_proposal_ids),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class MarketState:
    """A single bar slice fed to every agent on every tick."""

    tick_id: int
    symbol: Symbol
    timeframe: SquadTimeframe
    as_of: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bid_low: float | None = None
    ask_high: float | None = None
    features: dict[str, float] = field(default_factory=dict)
    history: dict[str, list[float]] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self) | {"as_of": _iso(self.as_of)}


@dataclass(frozen=True)
class CanonRole:
    """Fixed identity layer per agent (doctrine section 3.10)."""

    canon_player: str
    weapon: str
    ego: float
    target_hold_hours: float
    narrative_voice: str


# F22c: agent intend() return type union.
IntentDecision = AgentProposal | YieldReason | None
