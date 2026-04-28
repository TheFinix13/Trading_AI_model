"""Execution layer: places orders via MT5 in paper/live, mock executor for tests."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agent.types import Direction, Setup

log = logging.getLogger(__name__)


@dataclass
class OrderResult:
    accepted: bool
    ticket: int | None = None
    fill_price: float | None = None
    fill_time: datetime | None = None
    message: str = ""


class Executor(ABC):
    @abstractmethod
    def place_market_order(self, setup: Setup, lot: float, symbol: str) -> OrderResult: ...

    @abstractmethod
    def close_position(self, ticket: int, symbol: str) -> OrderResult: ...

    @abstractmethod
    def open_positions(self, symbol: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def account_balance(self) -> float: ...


class MockExecutor(Executor):
    """In-memory executor for tests and dry runs."""

    def __init__(self, starting_balance: float = 100.0):
        self._balance = starting_balance
        self._positions: dict[int, dict[str, Any]] = {}
        self._next_ticket = 1

    def place_market_order(self, setup: Setup, lot: float, symbol: str) -> OrderResult:
        ticket = self._next_ticket
        self._next_ticket += 1
        self._positions[ticket] = {
            "ticket": ticket,
            "symbol": symbol,
            "direction": setup.direction.value,
            "lot": lot,
            "entry": setup.entry,
            "stop": setup.stop,
            "tp": setup.take_profit,
            "open_time": setup.detected_at,
        }
        return OrderResult(accepted=True, ticket=ticket, fill_price=setup.entry, fill_time=setup.detected_at)

    def close_position(self, ticket: int, symbol: str) -> OrderResult:
        if ticket not in self._positions:
            return OrderResult(accepted=False, message="ticket not found")
        del self._positions[ticket]
        return OrderResult(accepted=True, ticket=ticket)

    def open_positions(self, symbol: str) -> list[dict[str, Any]]:
        return [p for p in self._positions.values() if p["symbol"] == symbol]

    def account_balance(self) -> float:
        return self._balance


class MT5Executor(Executor):
    """Places orders via the MetaTrader5 Python package (Windows-only at runtime)."""

    def __init__(self, magic: int = 271828, deviation: int = 10):
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as e:
            raise RuntimeError("MetaTrader5 package not available") from e
        self.mt5 = mt5
        self.magic = magic
        self.deviation = deviation

    def place_market_order(self, setup: Setup, lot: float, symbol: str) -> OrderResult:
        mt5 = self.mt5
        info = mt5.symbol_info_tick(symbol)
        if info is None:
            return OrderResult(False, message=f"no tick for {symbol}")

        price = info.ask if setup.direction == Direction.LONG else info.bid
        order_type = mt5.ORDER_TYPE_BUY if setup.direction == Direction.LONG else mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": price,
            "sl": float(setup.stop),
            "tp": float(setup.take_profit),
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": "eurusd-ai-agent",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err = mt5.last_error()
            return OrderResult(False, message=f"order_send failed: rc={getattr(result,'retcode',None)} err={err}")
        return OrderResult(
            accepted=True,
            ticket=result.order,
            fill_price=result.price,
            fill_time=datetime.utcnow(),
        )

    def close_position(self, ticket: int, symbol: str) -> OrderResult:
        mt5 = self.mt5
        positions = [p for p in (mt5.positions_get(symbol=symbol) or []) if p.ticket == ticket]
        if not positions:
            return OrderResult(False, message="ticket not found")
        pos = positions[0]
        info = mt5.symbol_info_tick(symbol)
        price = info.bid if pos.type == mt5.POSITION_TYPE_BUY else info.ask
        opp_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": opp_type,
            "position": ticket,
            "price": price,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": "eurusd-ai-agent close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(False, message=f"close failed rc={getattr(result,'retcode',None)}")
        return OrderResult(True, ticket=ticket, fill_price=result.price, fill_time=datetime.utcnow())

    def open_positions(self, symbol: str) -> list[dict[str, Any]]:
        mt5 = self.mt5
        positions = mt5.positions_get(symbol=symbol) or []
        return [
            {
                "ticket": p.ticket,
                "symbol": p.symbol,
                "direction": "long" if p.type == mt5.POSITION_TYPE_BUY else "short",
                "lot": p.volume,
                "entry": p.price_open,
                "stop": p.sl,
                "tp": p.tp,
                "open_time": datetime.fromtimestamp(p.time),
                "profit": p.profit,
            }
            for p in positions
        ]

    def account_balance(self) -> float:
        info = self.mt5.account_info()
        return float(info.balance) if info else 0.0


def make_executor(mode: str = "paper") -> Executor:
    if mode in ("paper", "live"):
        try:
            return MT5Executor()
        except RuntimeError as e:
            log.warning("Falling back to MockExecutor: %s", e)
            return MockExecutor()
    return MockExecutor()
