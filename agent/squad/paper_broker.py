"""Paper broker -- production fill model, never places broker orders.

Ported v1 (unvalidated port) trade lifecycle helpers from the research
repo ``sim/scoring/run_isagi_phi3_gate.py`` @ commit e084c5b
(2026-07-14). Delegates entry/exit to ``agent.alphas.backtest._open`` /
``_check_exit`` so simulated fills are comparable to the sealed
E004 / G7 caches. Shadow-only: never talks to MT5.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from agent.alphas.backtest import _check_exit as prod_exit
from agent.alphas.backtest import _open as prod_open
from agent.alphas.base import AlphaSignal
from agent.config import Config, load_config
from agent.squad.tqs import compute_tqs
from agent.squad.types import AgentProposal
from agent.types import Bar, Direction


@dataclass
class TradeRecord:
    """Closed simulated trade with TQS components + proposal provenance."""

    agent_id: str
    symbol: str
    entry_time: datetime
    exit_time: datetime
    direction: str
    entry: float
    stop: float
    take_profit: float
    exit_price: float
    exit_reason: str
    pnl_pips: float
    mae_pips: float
    mfe_pips: float
    bars_held: int
    r_multiple: float
    tqs_components: dict
    source_conviction: float | None = None
    source_regime_fit: float | None = None
    source_sl_pips: float | None = None
    source_atr_pips: float | None = None
    source_h1_swing_pips: float | None = None
    source_tick_id: int | None = None

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("entry_time", "exit_time"):
            if isinstance(d[k], datetime):
                d[k] = d[k].isoformat()
        return d


@dataclass
class OpenPaperTrade:
    """In-flight production Trade plus provenance stash."""

    trade: Any  # agent.types.Trade
    agent_id: str
    symbol: str
    source_conviction: float
    source_regime_fit: float
    source_sl_pips: float
    source_atr_pips: float | None
    source_h1_swing_pips: float | None
    source_tick_id: int
    target_hold_hours: float
    source_risk_dollars: float = 0.0


class PaperBroker:
    """Simulated fills/exits; never places broker orders."""

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or load_config()

    def open_from_proposal(
        self,
        proposal: AgentProposal,
        next_bar: Bar,
        *,
        target_hold_hours: float = 24.0,
        risk_dollars: float = 0.0,
    ) -> OpenPaperTrade:
        take_profit = (
            float(proposal.ladder[0].price)
            if proposal.ladder else float(proposal.entry)
        )
        direction = (
            Direction.LONG if proposal.direction == "long" else Direction.SHORT
        )
        shim = AlphaSignal(
            direction=direction,
            entry=float(proposal.entry),
            stop=float(proposal.stop),
            take_profit=take_profit,
            reason=proposal.rationale.get("signal_reason", "squad_proposal"),
            conviction=float(proposal.conviction),
            meta=dict(proposal.rationale),
        )
        trade = prod_open(shim, next_bar, self.cfg)
        rat = proposal.rationale or {}
        return OpenPaperTrade(
            trade=trade,
            agent_id=proposal.agent_id,
            symbol=proposal.symbol,
            source_conviction=float(proposal.conviction),
            source_regime_fit=float(proposal.regime_fit),
            source_sl_pips=abs(proposal.entry - proposal.stop) * 10000.0,
            source_atr_pips=rat.get("atr_pips"),
            source_h1_swing_pips=rat.get("h1_swing_pips"),
            source_tick_id=int(proposal.tick_id),
            target_hold_hours=float(target_hold_hours),
            source_risk_dollars=float(risk_dollars),
        )

    @staticmethod
    def update_excursion(ot: OpenPaperTrade, bar: Bar) -> None:
        trade = ot.trade
        if trade.direction.value == "long":
            excursion_against = trade.entry_price - bar.low
            excursion_for = bar.high - trade.entry_price
        else:
            excursion_against = bar.high - trade.entry_price
            excursion_for = trade.entry_price - bar.low
        mae = max(0.0, excursion_against) * 10000.0
        mfe = max(0.0, excursion_for) * 10000.0
        if mae > trade.mae_pips:
            trade.mae_pips = mae
        if mfe > trade.mfe_pips:
            trade.mfe_pips = mfe

    def check_exit(self, ot: OpenPaperTrade, bar: Bar) -> bool:
        return bool(prod_exit(ot.trade, bar, self.cfg))

    def score(self, ot: OpenPaperTrade) -> TradeRecord:
        trade = ot.trade
        entry_t = trade.entry_time
        exit_t = trade.exit_time or entry_t
        actual_hold_hours = max(
            0.0, (exit_t - entry_t).total_seconds() / 3600.0,
        )
        stop_distance_price = abs(trade.entry_price - trade.stop_price)
        stop_distance_pips = stop_distance_price * 10000.0
        r_multiple = (
            float(trade.pnl_pips) / stop_distance_pips
            if stop_distance_pips > 0 else 0.0
        )
        components = compute_tqs(
            r_multiple=r_multiple,
            mae_pips=float(trade.mae_pips),
            mfe_pips=float(trade.mfe_pips),
            actual_hold_hours=actual_hold_hours,
            target_hold_hours=float(ot.target_hold_hours),
            had_adds=False,
            had_panic_exit=False,
            broker_stop_threatened=False,
            entry_inside_chemical_reaction=False,
        )
        return TradeRecord(
            agent_id=ot.agent_id,
            symbol=ot.symbol,
            entry_time=entry_t,
            exit_time=exit_t,
            direction=trade.direction.value,
            entry=float(trade.entry_price),
            stop=float(trade.stop_price),
            take_profit=float(trade.tp_price),
            exit_price=float(trade.exit_price) if trade.exit_price else 0.0,
            exit_reason=trade.exit_reason or "open",
            pnl_pips=float(trade.pnl_pips),
            mae_pips=float(trade.mae_pips),
            mfe_pips=float(trade.mfe_pips),
            bars_held=int(trade.bars_held or 0),
            r_multiple=r_multiple,
            tqs_components=components.to_jsonable(),
            source_conviction=ot.source_conviction,
            source_regime_fit=ot.source_regime_fit,
            source_sl_pips=ot.source_sl_pips,
            source_atr_pips=ot.source_atr_pips,
            source_h1_swing_pips=ot.source_h1_swing_pips,
            source_tick_id=ot.source_tick_id,
        )

    def force_close(self, ot: OpenPaperTrade, bar: Bar, reason: str = "end_of_data") -> TradeRecord:
        trade = ot.trade
        if trade.exit_time is None:
            trade.exit_time = bar.time
            trade.exit_price = bar.close
            trade.exit_reason = reason
            if trade.direction.value == "long":
                pip = (bar.close - trade.entry_price) * 10000.0
            else:
                pip = (trade.entry_price - bar.close) * 10000.0
            trade.pnl_pips = pip
            trade.pnl = (
                pip * trade.lot_size * self.cfg.backtest.pip_value_per_lot
                - trade.commission
            )
        return self.score(ot)

    def to_persistable(self, ot: OpenPaperTrade) -> dict[str, Any]:
        """Serialize an open trade for ``state.json`` resume."""
        t = ot.trade
        return {
            "agent_id": ot.agent_id,
            "symbol": ot.symbol,
            "direction": t.direction.value,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "entry_price": float(t.entry_price),
            "stop_price": float(t.stop_price),
            "tp_price": float(t.tp_price),
            "lot_size": float(t.lot_size),
            "commission": float(t.commission),
            "mae_pips": float(t.mae_pips),
            "mfe_pips": float(t.mfe_pips),
            "source_conviction": ot.source_conviction,
            "source_regime_fit": ot.source_regime_fit,
            "source_sl_pips": ot.source_sl_pips,
            "source_atr_pips": ot.source_atr_pips,
            "source_h1_swing_pips": ot.source_h1_swing_pips,
            "source_tick_id": ot.source_tick_id,
            "target_hold_hours": ot.target_hold_hours,
            "source_risk_dollars": ot.source_risk_dollars,
        }

    def from_persistable(self, d: dict[str, Any]) -> OpenPaperTrade:
        """Rehydrate an open trade from ``state.json``."""
        from agent.types import Setup, Timeframe, Trade

        direction = (
            Direction.LONG if d["direction"] == "long" else Direction.SHORT
        )
        entry_time = datetime.fromisoformat(d["entry_time"])
        setup = Setup(
            direction=direction,
            timeframe=Timeframe.H4,
            detected_at=entry_time,
            detected_bar_index=0,
            entry=float(d["entry_price"]),
            stop=float(d["stop_price"]),
            take_profit=float(d["tp_price"]),
        )
        trade = Trade(
            setup=setup,
            direction=direction,
            entry_time=entry_time,
            entry_price=float(d["entry_price"]),
            stop_price=float(d["stop_price"]),
            tp_price=float(d["tp_price"]),
            lot_size=float(d.get("lot_size", 0.1)),
            commission=float(d.get("commission", 0.0)),
        )
        trade.mae_pips = float(d.get("mae_pips", 0.0))
        trade.mfe_pips = float(d.get("mfe_pips", 0.0))
        return OpenPaperTrade(
            trade=trade,
            agent_id=d["agent_id"],
            symbol=d["symbol"],
            source_conviction=float(d.get("source_conviction", 0.0)),
            source_regime_fit=float(d.get("source_regime_fit", 0.0)),
            source_sl_pips=float(d.get("source_sl_pips", 0.0)),
            source_atr_pips=d.get("source_atr_pips"),
            source_h1_swing_pips=d.get("source_h1_swing_pips"),
            source_tick_id=int(d.get("source_tick_id", 0)),
            target_hold_hours=float(d.get("target_hold_hours", 24.0)),
            source_risk_dollars=float(d.get("source_risk_dollars", 0.0)),
        )
