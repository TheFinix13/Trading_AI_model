"""A10 -- Rensuke Kunigami v1 (`kunigami_rensuke`) -- anti-tilt observer.

Kunigami v1 is the anti-tilt risk auxiliary defined in doctrine
section 4.2 (the distinction vs the Sentinel) and roster section 3.10.
He NEVER opens a trade -- `intend()` always returns None. His value is
the *signal* he emits via Thoughts that the Sentinel R5 dampener
(`sim/core/sentinel.py:check_r5_loss_streak`) reads + the F12 TQS
slicer + the dashboard.

Two warning triggers (both observation-emitted Thoughts):

1. **Loss-streak warning** (`kunigami_loss_streak_warning`).
   3+ of the last `WINDOW=5` *closed trades* across all strikers were
   `(pnl_pips <= 0)` AND were taken from a high-conviction proposal
   (`source_proposal.conviction >= 0.7`). The harness pushes closed-
   trade outcomes into Kunigami via `record_closed_trade(...)`.

2. **Overconfidence warning** (`kunigami_overconfidence_warning`).
   Average `confidence_in_thought` across non-Kunigami peer Thoughts
   in the LAST `WINDOW_TICKS=50` ticks (read from the ledger) exceeds
   `0.85`. Detects squad-wide "everything is a great trade" tilt.

Sentinel R5 wiring
------------------

The Sentinel reads Kunigami's warning Thoughts on each tick via
`SentinelContext.kunigami_warning_active` (added in Phi4). When a
`kunigami_loss_streak_warning` is the agent's most recent Thought,
Sentinel R5 applies the 50% risk-scale for the next
`LOSS_STREAK_DURATION_HOURS = 24` hours (matches the
`sim/core/sentinel.py` defaults). The two compounding multipliers
(Sentinel R5 + Kunigami's signal) collapse into one application -- the
Sentinel layer is the authority on whether risk is dampened.

Information tier
----------------

Tier-1 by design (roster section 3.10 status "structural Tier 2").
Kunigami reads the LEDGER AGGREGATE (squad-wide confidence + per-
striker closed-trade outcomes), not individual peer Thoughts during
decision -- consistent with the doctrine that anti-tilt agents need
aggregate state to function. F17 still measured in the squad gate
harness.

Home TF
-------

`H4` for Phi4 v1 (matches the squad's H4 tick cadence). The roster's
canon "daily state, not market state" is a Phi5+ wiring -- v1 ticks
at every H4 bar so the warnings can update on the same cadence as
the Sentinel reads them.

Symbols
-------

EURUSD, GBPUSD, USDCAD (his warnings apply globally across all
symbols; he emits one warning Thought per tick per symbol that the
engine drives him on).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from agent.squad.ledger import ThoughtLedger
from agent.squad.striker import BaseStriker
from agent.squad.types import (
    SCHEMA_VERSION,
    AgentProposal,
    CanonRole,
    MarketState,
    Thought,
    ThoughtRead,
)


# ---------------------------------------------------------------------------
# Locked Phi4 v1 parameters.
# ---------------------------------------------------------------------------
KUNIGAMI_V1_LOSS_STREAK_WINDOW: int = 5      # last 5 closed trades
KUNIGAMI_V1_LOSS_STREAK_TRIGGER: int = 3     # 3+ losses out of last 5
KUNIGAMI_V1_HIGH_CONVICTION_FLOOR: float = 0.7
KUNIGAMI_V1_OVERCONF_WINDOW_TICKS: int = 50  # squad confidence sample
KUNIGAMI_V1_OVERCONF_THRESHOLD: float = 0.85
KUNIGAMI_V1_DURATION_HOURS: int = 24         # how long a warning stays "on"
                                              # for the Sentinel's R5 wiring
KUNIGAMI_V1_TTL_TICKS: int = 6               # ~ 1 trading day at H4

KUNIGAMI_V1_SYMBOLS: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDCAD")

KUNIGAMI_V1_CANON_ROLE = CanonRole(
    canon_player="kunigami_rensuke",
    weapon="anti_tilt_recovery_discipline",
    ego=0.00,
    target_hold_hours=0.0,    # auxiliary -- never holds a position
    narrative_voice="dampens_after_losses",
)


@dataclass(frozen=True)
class ClosedTradeRecord:
    """Minimal closed-trade outcome the harness pushes to Kunigami.

    The harness already has this information per-trade (entry_time,
    exit_time, pnl_pips, source proposal conviction). The contract here
    is tight by design: Kunigami does NOT depend on the production
    Trade dataclass; he depends on a tiny tuple that any executor can
    provide.
    """

    agent_id: str
    exit_time: datetime
    pnl_pips: float
    source_conviction: float


class A10KunigamiV1(BaseStriker):
    """A10 Kunigami v1 -- anti-tilt observer.

    External harness API:
      * `record_closed_trade(rec: ClosedTradeRecord)` -- push a closed
        trade outcome into Kunigami's rolling window. Mutates internal
        state ONLY; deterministic given input order.
      * `most_recent_warning_tag(...)` -- read accessor for the
        Sentinel R5 wiring (lookup is O(1)).

    BlueLockStriker contract:
      * `observe()` -- always emits a Thought. Tags carry the active
        warnings (zero, one, or both). `confidence_in_thought` carries
        a soft "tilt score" in [0, 1] -- the harness can journal this
        for the dashboard's R5 panel.
      * `intend()` -- ALWAYS returns None. Kunigami never trades.
    """

    def __init__(
        self,
        agent_id: str = "kunigami_rensuke",
        canon_role: Optional[CanonRole] = None,
        home_tf: str = "H4",
        symbols: Optional[list[str]] = None,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            canon_role=canon_role or KUNIGAMI_V1_CANON_ROLE,
            home_tf=home_tf,
            symbols=list(symbols) if symbols is not None else list(KUNIGAMI_V1_SYMBOLS),
            playstyle="defensive",
            tier=2,
        )
        # Bounded deque so memory is O(1) regardless of run length.
        self._recent_trades: deque[ClosedTradeRecord] = deque(
            maxlen=KUNIGAMI_V1_LOSS_STREAK_WINDOW,
        )
        self._last_warning_at: Optional[datetime] = None
        self._last_warning_tags: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # Harness API
    # ------------------------------------------------------------------

    def record_closed_trade(self, rec: ClosedTradeRecord) -> None:
        """Push a closed-trade outcome into the rolling window.

        Called by the harness whenever a trade exits. Deterministic --
        the deque's append order IS the trade-close order in replay.
        """
        self._recent_trades.append(rec)

    def reset_recent_trades(self) -> None:
        """Drop the rolling window. Used in tests + window boundaries."""
        self._recent_trades.clear()
        self._last_warning_at = None
        self._last_warning_tags = ()

    def warning_active_at(self, as_of: datetime) -> bool:
        """Return True iff Kunigami's most-recent warning is still 'on'.

        The Sentinel R5 wiring polls this on every tick to decide
        whether to apply the loss-streak dampener.
        """
        if self._last_warning_at is None:
            return False
        if not self._last_warning_tags:
            return False
        if "kunigami_loss_streak_warning" not in self._last_warning_tags:
            return False
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        wt = self._last_warning_at
        if wt.tzinfo is None:
            wt = wt.replace(tzinfo=timezone.utc)
        return (as_of - wt) <= timedelta(hours=KUNIGAMI_V1_DURATION_HOURS)

    @property
    def n_recent_trades(self) -> int:
        return len(self._recent_trades)

    # ------------------------------------------------------------------
    # BlueLockStriker contract
    # ------------------------------------------------------------------

    def observe(self, market: MarketState, ledger: ThoughtLedger) -> Thought:
        loss_streak_fired, n_losses = self._evaluate_loss_streak()
        overconf_fired, mean_conf, n_seen = self._evaluate_overconfidence(
            market, ledger,
        )

        tags = [
            "canon:kunigami",
            "weapon:anti_tilt",
            "risk_auxiliary",
        ]
        warnings: list[str] = []
        if loss_streak_fired:
            warnings.append("kunigami_loss_streak_warning")
        if overconf_fired:
            warnings.append("kunigami_overconfidence_warning")
        tags.extend(warnings)
        if not warnings:
            tags.append("kunigami_observation_clean")

        # Soft tilt score for the dashboard's R5 panel: 0 if no warning,
        # 0.5 for one warning, 1.0 for both.
        tilt_score = float(len(warnings)) / 2.0

        narrative_parts: list[str] = [
            f"[kunigami v1] {market.symbol} {market.timeframe} @ "
            f"{market.as_of}: ",
            f"recent_trades={self.n_recent_trades} losses={n_losses}; ",
            f"peer_conf_avg={mean_conf:.3f} (n={n_seen}).",
        ]
        if warnings:
            narrative_parts.append(" Warnings: " + ", ".join(warnings) + ".")
        else:
            narrative_parts.append(" No tilt detected; squad is clean.")

        if warnings:
            # Snapshot the warning state so the Sentinel R5 polling can
            # decide whether to apply the dampener over the next 24h.
            self._last_warning_at = market.as_of
            self._last_warning_tags = tuple(warnings)

        return Thought(
            schema_version=SCHEMA_VERSION,
            agent_id=self.agent_id,
            tick_id=market.tick_id,
            timestamp=market.as_of,
            symbol=market.symbol,
            narrative="".join(narrative_parts),
            tags=tags,
            confidence_in_thought=float(tilt_score),
            expected_action="dampen" if warnings else "wait",
            coordinate=None,                # Kunigami never proposes
            decision_horizon=market.as_of,
            ttl_ticks=KUNIGAMI_V1_TTL_TICKS,
            references=[],
            read=ThoughtRead(
                signal_family="risk_watch",
                direction_bias="flat",     # Kunigami never proposes a direction
                regime_read=(
                    "tilt_warning" if warnings else "clean"
                ),
                expected_stop_pips=None,
                expected_r=None,
                driving_evidence=tuple(warnings) if warnings else (
                    "kunigami_observation_clean",
                ),
            ),
        )

    def intend(
        self,
        market: MarketState,
        my_recent_thought: Thought,
        **_kwargs: object,
    ) -> AgentProposal | None:
        # Kunigami NEVER opens trades. Roster section 3.10 + doctrine
        # section 4.2 -- "auxiliary risk role; no shooting drive".
        # ``_kwargs`` absorbs the F21 ``workspace`` kwarg.
        return None

    # ------------------------------------------------------------------
    # Internal evaluators
    # ------------------------------------------------------------------

    def _evaluate_loss_streak(self) -> tuple[bool, int]:
        """Return (fired, n_high_confidence_losses_in_window)."""
        n_losses = sum(
            1 for r in self._recent_trades
            if r.pnl_pips <= 0
            and r.source_conviction >= KUNIGAMI_V1_HIGH_CONVICTION_FLOOR
        )
        fired = (
            len(self._recent_trades) >= KUNIGAMI_V1_LOSS_STREAK_WINDOW
            and n_losses >= KUNIGAMI_V1_LOSS_STREAK_TRIGGER
        )
        return fired, n_losses

    def _evaluate_overconfidence(
        self,
        market: MarketState,
        ledger: ThoughtLedger,
    ) -> tuple[bool, float, int]:
        """Return (fired, mean_confidence_in_window, n_thoughts_seen).

        Reads PRIOR-tick peer Thoughts only (ledger guards enforce
        backwards-only). The cap window is `OVERCONF_WINDOW_TICKS` --
        recent thoughts dominate.
        """
        peers = ledger.read(
            as_of=market.as_of,
            current_tick=market.tick_id,
            symbol=None,                # all symbols
        )
        # Last N thoughts from OTHER strikers.
        non_self = [
            t for t in peers if t.agent_id != self.agent_id
        ]
        # Sort by tick_id descending, take the most recent N.
        non_self.sort(key=lambda t: t.tick_id, reverse=True)
        window = non_self[: KUNIGAMI_V1_OVERCONF_WINDOW_TICKS]
        n_seen = len(window)
        if n_seen == 0:
            return False, 0.0, 0
        mean_conf = (
            sum(float(t.confidence_in_thought) for t in window) / float(n_seen)
        )
        # Require a minimum sample size before firing -- avoids the
        # window's first few ticks firing on n=1.
        fired = (
            n_seen >= 10
            and mean_conf > KUNIGAMI_V1_OVERCONF_THRESHOLD
        )
        return fired, float(mean_conf), int(n_seen)


# Backwards-compatible alias for v0.2 callers (tests, roster loaders).
KunigamiRensuke = A10KunigamiV1
