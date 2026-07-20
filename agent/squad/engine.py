"""Squad tick engine -- observe / intend / aggregate / Sentinel / paper fill.

Ported v1 (unvalidated port) of the research driver
``sim/scoring/run_phi4_squad_gate.py::_drive_squad_replay`` @ commit
e084c5b (2026-07-14). Simplified for the live paper runtime:

* Online mode: one newly-closed H4 bar at a time (``on_bar``).
* Batch mode: walk an interleaved historical stream (parity harness).
* Always ``use_workspace=True`` + ``sentinel_blocks=True`` (G7-shaped).
* Kunigami is a Sentinel R5 side channel only (not in the publisher roster).
* Shadow-ledger / Wild-Card Kunigami gate / F17 DeltaInfo NOT ported
  (research-only diagnostics).
* Persists open positions + cursors to ``state.json``; appends the
  three-JSONL schema the /v2 LIVE page already tails.

Labelled "ported v1 (unvalidated port)" until the parity harness
proves proposal-level fidelity against g7retry1-phi41.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from agent.alphas.backtest import FIXED_LOT
from agent.squad.aggregator import AggregationOutcome, aggregate
from agent.squad.aggregator_arms.multi_position import (
    ARM4_K_POSITIONS,
    _proposal_risk_dollars as arm4_proposal_risk_dollars,
)
from agent.squad.ledger import FullLedger
from agent.squad.paper_broker import OpenPaperTrade, PaperBroker, TradeRecord
from agent.squad.roster import SquadRoster, prepare_roster
from agent.squad.sentinel import (
    MIN_LOT,
    SANDBOX_PER_TRADE_RISK_FRAC,
    SentinelContext,
    check_r6_per_symbol_risk_cap,
    evaluate_proposal as sentinel_evaluate_proposal,
)
from agent.squad.types import AgentProposal, MarketState, Thought, YieldReason
from agent.squad.workspace import ReasoningWorkspace, WorkspaceSnapshot
from agent.types import Bar

log = logging.getLogger(__name__)

WARMUP_BARS = 200
SANDBOX_EQUITY_DOLLARS = 100.0
SANDBOX_PIP_VALUE_PER_MIN_LOT = 0.10
ARM4_SANDBOX_RISK_CAP_FRAC = 0.50
STATE_FILE = "state.json"
KILL_FILE = "kill.txt"
HEARTBEAT_PREFIX = "heartbeat_"

JSONL_FILES = (
    "proposals_all.jsonl",
    "proposals_rejected.jsonl",
    "trades.jsonl",
)

# Per-tick summary rows land here (see _emit_tick_summary). One row per
# on_bar() call, regardless of whether any proposals fired -- this is the
# /v2 dashboard's proof-of-life signal on quiet bars.
TICK_SUMMARY_FILE = "events.jsonl"


class _AgentScopedSnapshot:
    """Read-tracking wrapper around a WorkspaceSnapshot (G7 C4 counts)."""

    __slots__ = ("_snap", "_agent_id", "_read_counts")

    def __init__(
        self,
        snap: WorkspaceSnapshot,
        agent_id: str,
        read_counts: dict[str, int],
    ) -> None:
        self._snap = snap
        self._agent_id = agent_id
        self._read_counts = read_counts

    def _record(self) -> None:
        self._read_counts[self._agent_id] = (
            self._read_counts.get(self._agent_id, 0) + 1
        )

    def read_for(self, **kwargs: Any) -> tuple[Thought, ...]:
        self._record()
        return self._snap.read_for(**kwargs)

    def peer_thoughts(self, **kwargs: Any) -> tuple[Thought, ...]:
        self._record()
        return self._snap.peer_thoughts(**kwargs)

    def latest_by_agent(self, **kwargs: Any) -> dict[str, Thought]:
        self._record()
        return self._snap.latest_by_agent(**kwargs)

    @property
    def thoughts(self) -> tuple[Thought, ...]:
        return self._snap.thoughts

    @property
    def as_of(self) -> datetime:
        return self._snap.as_of

    @property
    def current_tick(self) -> int:
        return self._snap.current_tick


@dataclass
class TickResult:
    """Artefacts produced by one ``on_bar`` call."""

    proposals: list[AgentProposal] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    closed_trades: list[TradeRecord] = field(default_factory=list)
    thoughts: list[Thought] = field(default_factory=list)
    yields: list[YieldReason] = field(default_factory=list)
    # Count of proposals whose Sentinel decision was ``allowed=True`` in
    # ``_admit`` (informational; feeds the per-tick ``tick_summary``
    # event). Aggregator rejections and arm4 concurrency rejections are
    # NOT counted here since they occur outside the Sentinel gate.
    sentinel_pass_count: int = 0


NotifyFn = Callable[[dict, str], None]


class SquadEngine:
    """Online / batch squad paper engine.

    Constructed once; call ``prepare(bars_by_symbol)`` then either
    ``on_bar(...)`` repeatedly (live) or ``run_batch(...)`` (parity).
    """

    def __init__(
        self,
        roster: SquadRoster,
        out_dir: Path,
        *,
        aggregator_arm: str = "phi41",
        broker: PaperBroker | None = None,
        notifier: NotifyFn | None = None,
        source_label: str = "live_market",
        equity: float = SANDBOX_EQUITY_DOLLARS,
    ) -> None:
        if aggregator_arm not in ("phi41", "arm3", "arm4"):
            raise ValueError(f"unknown aggregator_arm: {aggregator_arm!r}")
        self.roster = roster
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.aggregator_arm = aggregator_arm
        self.multi_position = aggregator_arm == "arm4"
        self.broker = broker or PaperBroker()
        self.notifier = notifier
        self.source_label = source_label
        self.equity = float(equity)

        self.ledger = FullLedger()
        self.workspace = ReasoningWorkspace()
        self.tick_id = 0
        self.bars_seen: dict[str, int] = {}
        self.bars_by_symbol: dict[str, list[Bar]] = {}

        self.open_trades: dict[str, OpenPaperTrade] = {}
        self.open_trades_multi: dict[str, list[OpenPaperTrade]] = {}

        self.per_agent_consecutive_losses: dict[str, int] = {}
        self.per_agent_proposals_today: dict[str, int] = {}
        self.per_agent_equity: dict[str, float] = {
            a.agent_id: self.equity for a in roster.proposers
        }
        self.current_day: Any = None

        self.workspace_publish_counts: dict[str, int] = {}
        self.workspace_read_counts: dict[str, int] = {}

        self.last_bar_times: dict[str, str] = {}
        self._fh: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def prepare(self, bars_by_symbol: dict[str, list[Bar]]) -> None:
        self.bars_by_symbol = {s: list(b) for s, b in bars_by_symbol.items()}
        for s in self.bars_by_symbol:
            self.bars_seen.setdefault(s, 0)
        prepare_roster(self.roster, self.bars_by_symbol)
        self.load_state()

    def kill_active(self) -> str | None:
        kill = self.out_dir / KILL_FILE
        if not kill.exists():
            return None
        try:
            return kill.read_text(encoding="utf-8")[:200].strip() or "killed"
        except OSError:
            return "killed"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return self.out_dir / STATE_FILE

    def save_state(self) -> None:
        open_list: list[dict] = []
        if self.multi_position:
            for trades in self.open_trades_multi.values():
                open_list.extend(self.broker.to_persistable(t) for t in trades)
        else:
            open_list.extend(
                self.broker.to_persistable(t) for t in self.open_trades.values()
            )
        state = {
            "schema": 1,
            "source": self.source_label,
            "aggregator_arm": self.aggregator_arm,
            "tick_id": self.tick_id,
            "bars_seen": dict(self.bars_seen),
            "last_bar_times": dict(self.last_bar_times),
            "open_positions": open_list,
            "per_agent_consecutive_losses": dict(self.per_agent_consecutive_losses),
            "per_agent_equity": dict(self.per_agent_equity),
            "workspace_publish_counts": dict(self.workspace_publish_counts),
            "workspace_read_counts": dict(self.workspace_read_counts),
            "saved_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        tmp = self._state_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        tmp.replace(self._state_path())
        self._write_workspace_counts()

    def load_state(self) -> None:
        path = self._state_path()
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.tick_id = int(state.get("tick_id", 0))
        self.bars_seen.update({
            k: int(v) for k, v in (state.get("bars_seen") or {}).items()
        })
        self.last_bar_times.update(dict(state.get("last_bar_times") or {}))
        self.per_agent_consecutive_losses.update({
            k: int(v) for k, v in (state.get("per_agent_consecutive_losses") or {}).items()
        })
        self.per_agent_equity.update({
            k: float(v) for k, v in (state.get("per_agent_equity") or {}).items()
        })
        self.workspace_publish_counts.update(
            dict(state.get("workspace_publish_counts") or {}),
        )
        self.workspace_read_counts.update(
            dict(state.get("workspace_read_counts") or {}),
        )
        for row in state.get("open_positions") or []:
            try:
                ot = self.broker.from_persistable(row)
            except Exception as exc:  # noqa: BLE001
                log.warning("skip corrupt open position: %s", exc)
                continue
            if self.multi_position:
                self.open_trades_multi.setdefault(ot.symbol, []).append(ot)
            else:
                self.open_trades[ot.symbol] = ot
        log.info(
            "SquadEngine resumed: tick_id=%d open=%d last_bars=%s",
            self.tick_id,
            (
                sum(len(v) for v in self.open_trades_multi.values())
                if self.multi_position else len(self.open_trades)
            ),
            self.last_bar_times,
        )

    def _write_workspace_counts(self) -> None:
        payload = {
            "publish": dict(self.workspace_publish_counts),
            "read": dict(self.workspace_read_counts),
            "n_thoughts": sum(self.workspace_publish_counts.values()),
            "source": self.source_label,
        }
        (self.out_dir / "workspace_counts.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8",
        )

    def write_heartbeat(self, note: str = "") -> None:
        day = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
        path = self.out_dir / f"{HEARTBEAT_PREFIX}{day}.log"
        line = (
            f"{datetime.now(tz=timezone.utc).isoformat()} "
            f"tick={self.tick_id} source={self.source_label} "
            f"open={len(self.open_trades) if not self.multi_position else sum(len(v) for v in self.open_trades_multi.values())}"
            f"{(' ' + note) if note else ''}\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def _append_jsonl(self, filename: str, row: dict) -> None:
        path = self.out_dir / filename
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        if self.notifier is not None:
            try:
                self.notifier(row, filename)
            except Exception as exc:  # noqa: BLE001
                log.warning("notifier failed: %s", exc)

    def _emit_tick_summary(
        self,
        *,
        symbol: str,
        bar_time_iso: str,
        eligible: list[Any],
        result: TickResult,
    ) -> None:
        """Append one ``tick_summary`` row to ``events.jsonl``.

        Fired at the tail of every ``on_bar`` call regardless of whether
        any proposals materialised -- silent ticks (the ~99% case on
        quiet bars) still get a row so the /v2 dashboard can prove the
        squad is evaluating rather than asleep. Note: Karasu (news
        defender) and Kunigami (R5 side channel) are NOT in
        ``eligible`` -- they're not proposers, and their advisories
        ride as separate ``thought`` events.
        """
        proposers_who_fired: list[str] = sorted({
            p.agent_id for p in result.proposals if p.symbol == symbol
        })
        players_evaluated: list[str] = sorted(a.agent_id for a in eligible)
        row = {
            "type": "tick_summary",
            "timestamp": bar_time_iso,
            "symbol": symbol,
            "tick_id": int(self.tick_id),
            "players_evaluated": players_evaluated,
            "players_who_proposed": proposers_who_fired,
            "proposal_count": int(
                sum(1 for p in result.proposals if p.symbol == symbol)
            ),
            "post_sentinel_count": int(result.sentinel_pass_count),
            "workspace_thought_count": int(len(self.workspace.thoughts)),
        }
        self._append_jsonl(TICK_SUMMARY_FILE, row)

    # ------------------------------------------------------------------
    # Market state helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_market(bar: Bar, *, tick_id: int, symbol: str) -> MarketState:
        return MarketState(
            tick_id=int(tick_id),
            symbol=symbol,
            timeframe=bar.timeframe.value if hasattr(bar.timeframe, "value") else str(bar.timeframe),
            as_of=bar.time,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )

    def _extend_history(self, symbol: str, bar: Bar) -> int:
        """Append bar to per-symbol history if new; return its index."""
        series = self.bars_by_symbol.setdefault(symbol, [])
        if series and series[-1].time == bar.time:
            return len(series) - 1
        if series and series[-1].time > bar.time:
            # Out-of-order; find or ignore.
            for i, b in enumerate(series):
                if b.time == bar.time:
                    return i
            return len(series) - 1
        series.append(bar)
        return len(series) - 1

    # ------------------------------------------------------------------
    # Per-bar tick
    # ------------------------------------------------------------------

    def on_bar(
        self,
        symbol: str,
        bar: Bar,
        *,
        bar_index: int | None = None,
        next_bar: Bar | None = None,
    ) -> TickResult:
        """Process one newly closed H4 bar for ``symbol``.

        ``next_bar`` is required to open a new trade (fill at next open).
        When omitted, the engine looks up ``bars_by_symbol[symbol][i+1]``.
        """
        result = TickResult()
        if bar_index is None:
            bar_index = self._extend_history(symbol, bar)
        else:
            # Ensure history is at least as long as bar_index+1 for fills.
            series = self.bars_by_symbol.setdefault(symbol, [])
            while len(series) <= bar_index:
                series.append(bar)
            series[bar_index] = bar

        self.tick_id += 1
        tick_id = self.tick_id
        self.bars_seen[symbol] = self.bars_seen.get(symbol, 0) + 1
        self.last_bar_times[symbol] = bar.time.isoformat()

        market = self._to_market(bar, tick_id=tick_id, symbol=symbol)

        # Day roll-over resets R3 daily counter.
        bar_day = bar.time.date() if bar.time is not None else self.current_day
        if self.current_day is None or bar_day != self.current_day:
            self.current_day = bar_day
            self.per_agent_proposals_today.clear()

        # ---- manage open trades on this symbol ----
        result.closed_trades.extend(self._manage_opens(symbol, bar, tick_id))

        # ---- eligible agents ----
        eligible = sorted(
            [a for a in self.roster.proposers if symbol in a.symbols],
            key=lambda a: a.agent_id,
        )

        # ---- Phase 1: observe ----
        my_thought: dict[str, Thought] = {}
        for agent in eligible:
            t = agent.observe(market, self.ledger)
            self.ledger.append(t)
            result.thoughts.append(t)
            my_thought[agent.agent_id] = t
            if self.workspace.publish(t):
                self.workspace_publish_counts[agent.agent_id] = (
                    self.workspace_publish_counts.get(agent.agent_id, 0) + 1
                )

        # Kunigami side channel observe (R5 warnings); not a publisher
        # for peer chemistry, but his Thought lands on the ledger so
        # overconfidence reads keep working.
        kuni = self.roster.kunigami
        if symbol in kuni.symbols:
            kt = kuni.observe(market, self.ledger)
            self.ledger.append(kt)
            result.thoughts.append(kt)

        # Karasu news-window observe (R7 side channel); publishes an
        # advisory Thought when a scheduled release is inside the
        # blackout window on this symbol. Also published to the
        # workspace so peer intend() can see the advisory.
        kara = getattr(self.roster, "karasu", None)
        if kara is not None and symbol in kara.symbols:
            karat = kara.observe(market, self.ledger)
            self.ledger.append(karat)
            result.thoughts.append(karat)
            if self.workspace.publish(karat):
                self.workspace_publish_counts[kara.agent_id] = (
                    self.workspace_publish_counts.get(kara.agent_id, 0) + 1
                )

        bar_time_iso = self.last_bar_times[symbol]

        if self.bars_seen[symbol] <= WARMUP_BARS:
            self._emit_tick_summary(
                symbol=symbol, bar_time_iso=bar_time_iso,
                eligible=eligible, result=result,
            )
            self.save_state()
            return result

        series = self.bars_by_symbol[symbol]
        if next_bar is None:
            if bar_index >= len(series) - 1:
                self._emit_tick_summary(
                    symbol=symbol, bar_time_iso=bar_time_iso,
                    eligible=eligible, result=result,
                )
                self.save_state()
                return result
            next_bar = series[bar_index + 1]

        base_snapshot = self.workspace.snapshot_at_barrier(
            as_of=bar.time, current_tick=int(tick_id),
        )

        # ---- Phase 2: intend ----
        proposals_this_tick: list[AgentProposal] = []
        for agent in eligible:
            if market.timeframe != agent.home_tf:
                continue
            t = my_thought[agent.agent_id]
            scoped = _AgentScopedSnapshot(
                base_snapshot, agent.agent_id, self.workspace_read_counts,
            )
            decision = agent.intend(market, t, workspace=scoped)
            if isinstance(decision, YieldReason):
                result.yields.append(decision)
                continue
            if decision is None:
                continue
            proposals_this_tick.append(decision)
            result.proposals.append(decision)
            self._append_jsonl("proposals_all.jsonl", decision.to_jsonable())
            self.per_agent_proposals_today[decision.agent_id] = (
                self.per_agent_proposals_today.get(decision.agent_id, 0) + 1
            )

        if not proposals_this_tick:
            self._emit_tick_summary(
                symbol=symbol, bar_time_iso=bar_time_iso,
                eligible=eligible, result=result,
            )
            self.workspace.prune_before(max(0, tick_id - 500))
            self.save_state()
            return result

        outcome = aggregate(
            proposals_this_tick, tick_id=tick_id, arm=self.aggregator_arm,
        )
        for rej in outcome.rejected:
            result.rejected.append(rej)
            self._append_jsonl("proposals_rejected.jsonl", rej)

        # ---- Sentinel + open ----
        closed_extra = self._admit(
            symbol=symbol,
            bar=bar,
            next_bar=next_bar,
            tick_id=tick_id,
            outcome=outcome,
            result=result,
        )
        result.closed_trades.extend(closed_extra)

        # tick_summary lands AFTER the tick's individual proposal /
        # tackle / shot rows so operators reading events.jsonl see the
        # summary as a natural "closing footer" for the tick.
        self._emit_tick_summary(
            symbol=symbol, bar_time_iso=bar_time_iso,
            eligible=eligible, result=result,
        )
        self.workspace.prune_before(max(0, tick_id - 500))
        self.save_state()
        return result

    def _manage_opens(
        self, symbol: str, bar: Bar, tick_id: int,
    ) -> list[TradeRecord]:
        closed: list[TradeRecord] = []
        if self.multi_position:
            still: list[OpenPaperTrade] = []
            for ot in self.open_trades_multi.get(symbol, ()):
                self.broker.update_excursion(ot, bar)
                if self.broker.check_exit(ot, bar):
                    closed.append(self._finalise(ot))
                else:
                    still.append(ot)
            if symbol in self.open_trades_multi:
                if still:
                    self.open_trades_multi[symbol] = still
                else:
                    self.open_trades_multi.pop(symbol, None)
        else:
            ot = self.open_trades.get(symbol)
            if ot is not None:
                self.broker.update_excursion(ot, bar)
                if self.broker.check_exit(ot, bar):
                    closed.append(self._finalise(ot))
                    self.open_trades.pop(symbol, None)
        return closed

    def _finalise(self, ot: OpenPaperTrade) -> TradeRecord:
        tr = self.broker.score(ot)
        self._append_jsonl("trades.jsonl", tr.to_jsonable())
        from agent.squad.agents.a10_kunigami import ClosedTradeRecord
        self.roster.kunigami.record_closed_trade(ClosedTradeRecord(
            agent_id=tr.agent_id,
            exit_time=tr.exit_time,
            pnl_pips=tr.pnl_pips,
            source_conviction=float(ot.source_conviction),
        ))
        if tr.pnl_pips <= 0:
            self.per_agent_consecutive_losses[tr.agent_id] = (
                self.per_agent_consecutive_losses.get(tr.agent_id, 0) + 1
            )
        else:
            self.per_agent_consecutive_losses[tr.agent_id] = 0
        self.per_agent_equity[tr.agent_id] = (
            self.per_agent_equity.get(tr.agent_id, self.equity) + tr.pnl_pips
        )
        return tr

    def _admit(
        self,
        *,
        symbol: str,
        bar: Bar,
        next_bar: Bar,
        tick_id: int,
        outcome: AggregationOutcome,
        result: TickResult,
    ) -> list[TradeRecord]:
        """Sentinel + concurrency gate; open winning proposals."""
        closed: list[TradeRecord] = []
        kuni_active = bool(self.roster.kunigami.warning_active_at(bar.time))
        karasu = getattr(self.roster, "karasu", None)
        candidates = outcome.ranked_by_symbol.get(symbol, [])
        for rank_idx, proposal in enumerate(candidates):
            if proposal.symbol != symbol:
                continue
            karasu_impact = "none"
            karasu_title: str | None = None
            karasu_curs: frozenset[str] | None = None
            karasu_mte: int | None = None
            if karasu is not None:
                kw = karasu.warning_active_at(proposal.timestamp, proposal.symbol)
                karasu_impact = kw.impact
                karasu_title = kw.event_title
                karasu_curs = kw.currencies if kw.currencies else None
                karasu_mte = kw.minutes_to_event
            sentinel_ctx = SentinelContext(
                equity=self.equity,
                pip_value_per_min_lot=SANDBOX_PIP_VALUE_PER_MIN_LOT,
                consecutive_losses=self.per_agent_consecutive_losses.get(
                    proposal.agent_id, 0,
                ),
                proposals_today_by_agent=dict(self.per_agent_proposals_today),
                kunigami_loss_streak_active=kuni_active,
                karasu_impact=karasu_impact,
                karasu_event_title=karasu_title,
                karasu_event_currencies=karasu_curs,
                karasu_minutes_to_event=karasu_mte,
            )
            decision = sentinel_evaluate_proposal(proposal, sentinel_ctx)
            if not decision.allowed:
                rej = {
                    "tick_id": int(tick_id),
                    "symbol": symbol,
                    "winner_agent_id": proposal.agent_id,
                    "winner_conviction": float(proposal.conviction),
                    "loser_agent_id": proposal.agent_id,
                    "loser_conviction": float(proposal.conviction),
                    "loser_direction": proposal.direction,
                    "winner_direction": proposal.direction,
                    "rejection_reason": f"sentinel_{decision.rule}_block",
                    "sentinel_reason": decision.reason,
                    "rank_at_block": int(rank_idx),
                    "timestamp": proposal.timestamp.isoformat(),
                }
                result.rejected.append(rej)
                self._append_jsonl("proposals_rejected.jsonl", rej)
                continue

            # Sentinel passed. Track for the per-tick summary event
            # even if a downstream gate (min-lot floor, arm4 slot,
            # concurrency limit) later blocks the fill: those are
            # NOT Sentinel decisions.
            result.sentinel_pass_count += 1

            # Sentinel accept: enforce decision.risk_scale on the sizer output.
            # R5 (loss-streak) and R7 (news-impact medium) both return an
            # advisory scale between 0.0 and 1.0 that has historically been
            # informational only; the executor was still filling FIXED_LOT.
            # Multiply here so the paper broker's fill reflects the scaled
            # position. If scaling drives below the broker min-lot floor we
            # SKIP the trade rather than round back up -- rounding up would
            # negate the point of the scale-down.
            risk_scale = float(getattr(decision, "risk_scale", 1.0) or 1.0)
            scaled_lot = round(FIXED_LOT * risk_scale, 8)
            if scaled_lot + 1e-9 < MIN_LOT:
                rej = {
                    "tick_id": int(tick_id),
                    "symbol": symbol,
                    "winner_agent_id": proposal.agent_id,
                    "winner_conviction": float(proposal.conviction),
                    "loser_agent_id": proposal.agent_id,
                    "loser_conviction": float(proposal.conviction),
                    "loser_direction": proposal.direction,
                    "winner_direction": proposal.direction,
                    "rejection_reason": "sentinel_risk_scale_below_min_lot",
                    "sentinel_reason": (
                        f"risk_scale={risk_scale:.4f} x FIXED_LOT={FIXED_LOT} "
                        f"= {scaled_lot:.4f} < min_lot {MIN_LOT}"
                    ),
                    "sentinel_rule": decision.rule,
                    "rank_at_block": int(rank_idx),
                    "timestamp": proposal.timestamp.isoformat(),
                }
                result.rejected.append(rej)
                self._append_jsonl("proposals_rejected.jsonl", rej)
                continue

            if self.multi_position:
                reason = self._arm4_reject_reason(symbol, proposal)
                if reason is not None:
                    rej = {
                        "tick_id": int(tick_id),
                        "symbol": symbol,
                        "winner_agent_id": proposal.agent_id,
                        "winner_conviction": float(proposal.conviction),
                        "loser_agent_id": proposal.agent_id,
                        "loser_conviction": float(proposal.conviction),
                        "loser_direction": proposal.direction,
                        "winner_direction": proposal.direction,
                        "rejection_reason": reason,
                        "rank_at_block": int(rank_idx),
                        "timestamp": proposal.timestamp.isoformat(),
                    }
                    result.rejected.append(rej)
                    self._append_jsonl("proposals_rejected.jsonl", rej)
                    continue
            elif symbol in self.open_trades:
                rej = {
                    "tick_id": int(tick_id),
                    "symbol": symbol,
                    "winner_agent_id": proposal.agent_id,
                    "winner_conviction": float(proposal.conviction),
                    "loser_agent_id": proposal.agent_id,
                    "loser_conviction": float(proposal.conviction),
                    "loser_direction": proposal.direction,
                    "winner_direction": proposal.direction,
                    "rejection_reason": "open_position_concurrency_limit",
                    "timestamp": proposal.timestamp.isoformat(),
                }
                result.rejected.append(rej)
                self._append_jsonl("proposals_rejected.jsonl", rej)
                continue

            try:
                target_hh = 24.0
                for a in self.roster.proposers:
                    if a.agent_id == proposal.agent_id:
                        target_hh = float(a.canon_role.target_hold_hours)
                        break
                risk_dollars = 0.0
                if self.multi_position:
                    risk_dollars = arm4_proposal_risk_dollars(
                        proposal,
                        pip_value_per_min_lot=SANDBOX_PIP_VALUE_PER_MIN_LOT,
                    )
                ot = self.broker.open_from_proposal(
                    proposal, next_bar,
                    target_hold_hours=target_hh,
                    risk_dollars=risk_dollars,
                )
                if risk_scale != 1.0:
                    ot.trade.lot_size = scaled_lot
                    ot.trade.commission = (
                        scaled_lot / FIXED_LOT * ot.trade.commission
                    )
                if self.multi_position:
                    self.open_trades_multi.setdefault(symbol, []).append(ot)
                    if len(self.open_trades_multi[symbol]) >= ARM4_K_POSITIONS:
                        break
                    continue
                self.open_trades[symbol] = ot
                break
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Failed to open paper trade tick=%d %s/%s: %s",
                    tick_id, symbol, proposal.agent_id, exc,
                )
        return closed

    def _arm4_reject_reason(
        self, symbol: str, proposal: AgentProposal,
    ) -> str | None:
        current = self.open_trades_multi.get(symbol, [])
        if len(current) >= ARM4_K_POSITIONS:
            return "arm4_slot_full"
        if proposal.agent_id in {t.agent_id for t in current}:
            return "arm4_same_agent_already_on_symbol"
        combined = sum(float(t.source_risk_dollars) for t in current)
        additional = arm4_proposal_risk_dollars(
            proposal, pip_value_per_min_lot=SANDBOX_PIP_VALUE_PER_MIN_LOT,
        )
        r6 = check_r6_per_symbol_risk_cap(
            symbol=symbol,
            current_symbol_risk_dollars=combined,
            additional_risk_dollars=additional,
            equity=self.equity,
            cap_frac=ARM4_SANDBOX_RISK_CAP_FRAC,
        )
        if not r6.allowed:
            return "arm4_sentinel_R6_block"
        return None

    # ------------------------------------------------------------------
    # Batch driver (parity harness)
    # ------------------------------------------------------------------

    def run_batch(
        self,
        bars_by_symbol: dict[str, list[Bar]],
        *,
        max_bars: int | None = None,
    ) -> dict[str, Any]:
        """Walk the interleaved historical stream once."""
        self.prepare(bars_by_symbol)
        flat: list[tuple[datetime, str, int, Bar]] = []
        for sym, bars in bars_by_symbol.items():
            for i, b in enumerate(bars):
                flat.append((b.time, sym, i, b))
        flat.sort(key=lambda x: (x[0], x[1]))

        n_proposals = 0
        n_trades = 0
        n_rejected = 0
        processed = 0
        for _, sym, i, bar in flat:
            if max_bars is not None and processed >= max_bars:
                break
            next_bar = (
                bars_by_symbol[sym][i + 1]
                if i + 1 < len(bars_by_symbol[sym]) else None
            )
            # During warmup we still need the observe / tick cadence
            # even if no next_bar yet -- on_bar handles the gate.
            tr = self.on_bar(sym, bar, bar_index=i, next_bar=next_bar)
            n_proposals += len(tr.proposals)
            n_trades += len(tr.closed_trades)
            n_rejected += len(tr.rejected)
            processed += 1

        # Force-close leftovers.
        for sym, ot in list(self.open_trades.items()):
            last = bars_by_symbol[sym][-1]
            tr = self.broker.force_close(ot, last)
            self._append_jsonl("trades.jsonl", tr.to_jsonable())
            n_trades += 1
            self.open_trades.pop(sym, None)
        for sym, trades in list(self.open_trades_multi.items()):
            last = bars_by_symbol[sym][-1]
            for ot in trades:
                tr = self.broker.force_close(ot, last)
                self._append_jsonl("trades.jsonl", tr.to_jsonable())
                n_trades += 1
            self.open_trades_multi.pop(sym, None)

        self.save_state()
        return {
            "bars_processed": processed,
            "n_proposals": n_proposals,
            "n_rejected": n_rejected,
            "n_trades": n_trades,
            "workspace_publish": dict(self.workspace_publish_counts),
            "workspace_read": dict(self.workspace_read_counts),
        }


# Silence unused-import lint for constants re-exported via research parity.
_ = (MIN_LOT, SANDBOX_PER_TRADE_RISK_FRAC)
