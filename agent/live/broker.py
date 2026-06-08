"""Broker abstraction layer for live trading.

Provides a unified async interface for:
- MT5 (Windows, via MetaTrader5 package)
- Exness (wraps MT5 with Exness-specific server config)
- Paper (local simulation for testing without a real broker)
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agent.types import Bar, Direction, Timeframe

log = logging.getLogger(__name__)

# MT5 enforces a 31-character limit on order comments and only accepts a
# narrow set of ASCII characters. Anything outside that range (brackets,
# quotes, commas, etc.) triggers a "-2 Invalid 'comment' argument" rejection.
_MT5_COMMENT_MAX_LEN = 31
_MT5_COMMENT_SAFE_RE = re.compile(r"[^A-Za-z0-9 _\-]")


def _sanitize_mt5_comment(comment: str | None, max_len: int = _MT5_COMMENT_MAX_LEN) -> str:
    """Make an order comment safe for MT5's strict ``order_send`` validation.

    MT5 rejects comments longer than 31 characters or containing characters
    outside basic ASCII alphanumerics, spaces, underscores and hyphens. This
    strips any unsafe characters, collapses surrounding whitespace and
    truncates to ``max_len``. Always returns a non-empty, valid string so the
    request can never be rejected on the ``comment`` field.
    """
    if not comment:
        return "AI"
    safe = _MT5_COMMENT_SAFE_RE.sub("", str(comment))
    safe = safe.strip()
    if not safe:
        return "AI"
    return safe[:max_len]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    leverage: int
    currency: str = "USD"
    server: str = ""
    login: int = 0


@dataclass
class Position:
    ticket: int
    symbol: str
    direction: Direction
    volume: float
    open_price: float
    open_time: datetime
    stop_loss: float
    take_profit: float
    current_price: float = 0.0
    profit: float = 0.0
    swap: float = 0.0
    comment: str = ""


@dataclass
class OrderResult:
    success: bool
    ticket: int | None = None
    fill_price: float | None = None
    fill_time: datetime | None = None
    message: str = ""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BrokerConnection(ABC):
    """Abstract broker interface for the live trading loop."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the broker. Returns True on success."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up connection resources."""
        ...

    @abstractmethod
    async def get_latest_bars(
        self, symbol: str, timeframe: str, count: int
    ) -> list[Bar]:
        """Fetch the most recent `count` bars for the given symbol/timeframe."""
        ...

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        direction: Direction,
        lot: float,
        stop: float,
        tp: float,
        comment: str = "",
    ) -> OrderResult:
        """Place a market order with SL and TP."""
        ...

    @abstractmethod
    async def close_position(self, ticket: int, symbol: str) -> OrderResult:
        """Close an open position by ticket."""
        ...

    @abstractmethod
    async def modify_position(
        self, ticket: int, symbol: str, stop: float | None = None, tp: float | None = None
    ) -> OrderResult:
        """Modify SL/TP on an open position."""
        ...

    @abstractmethod
    async def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        """Get all open positions, optionally filtered by symbol."""
        ...

    @abstractmethod
    async def get_account_info(self) -> AccountInfo:
        """Get current account state (balance, equity, margin)."""
        ...

    @abstractmethod
    async def get_current_price(self, symbol: str) -> tuple[float, float]:
        """Get current bid/ask for a symbol. Returns (bid, ask)."""
        ...


# ---------------------------------------------------------------------------
# MT5 Broker (Windows-only)
# ---------------------------------------------------------------------------


class MT5Broker(BrokerConnection):
    """MT5 connection via the MetaTrader5 Python package.

    This only works on Windows or via a bridge (Docker/VPS).
    Wraps synchronous MT5 calls in asyncio.to_thread for non-blocking operation.
    """

    _TF_MAP = {
        "M1": "TIMEFRAME_M1",
        "M5": "TIMEFRAME_M5",
        "M15": "TIMEFRAME_M15",
        "H1": "TIMEFRAME_H1",
        "H4": "TIMEFRAME_H4",
        "D1": "TIMEFRAME_D1",
    }

    _SYMBOL_SUFFIXES = ["", "m", ".", "c", "M", ".raw", "#"]

    def __init__(self, login: int, password: str, server: str, path: str = ""):
        self._login = login
        self._password = password
        self._server = server
        self._path = path
        self._mt5: Any = None
        self._connected = False
        self._resolved_symbols: dict[str, str] = {}

    async def connect(self) -> bool:
        try:
            import MetaTrader5 as mt5
        except ImportError:
            log.error(
                "MetaTrader5 package not available. "
                "This requires Windows or a Docker bridge. "
                "Use --broker paper for local testing on macOS."
            )
            return False

        self._mt5 = mt5

        def _init():
            kwargs: dict[str, Any] = {}
            if self._path:
                kwargs["path"] = self._path
            if not mt5.initialize(**kwargs):
                return False
            authorized = mt5.login(
                login=self._login,
                password=self._password,
                server=self._server,
            )
            return bool(authorized)

        self._connected = await asyncio.to_thread(_init)
        if self._connected:
            info = self._mt5.account_info()
            log.info(
                "MT5 connected: login=%d server=%s balance=%.2f",
                info.login, info.server, info.balance,
            )
        else:
            err = self._mt5.last_error()
            log.error("MT5 connection failed: %s", err)
        return self._connected

    async def disconnect(self) -> None:
        if self._mt5 and self._connected:
            await asyncio.to_thread(self._mt5.shutdown)
            self._connected = False
            log.info("MT5 disconnected")

    def _resolve_symbol_sync(self, base_symbol: str) -> str:
        """Find the actual symbol name on this broker (synchronous, call from thread)."""
        mt5 = self._mt5

        for suffix in self._SYMBOL_SUFFIXES:
            variant = f"{base_symbol}{suffix}"
            info = mt5.symbol_info(variant)
            if info is not None:
                mt5.symbol_select(variant, True)
                return variant

        # Fuzzy search across all available symbols
        all_symbols = mt5.symbols_get()
        if all_symbols:
            base_lower = base_symbol.lower()
            for s in all_symbols:
                if base_lower in s.name.lower():
                    mt5.symbol_select(s.name, True)
                    return s.name

        return base_symbol

    async def resolve_symbol(self, base_symbol: str) -> str:
        """Resolve a base symbol (e.g. EURUSD) to the broker's actual name.

        Caches the result so subsequent calls are instant.
        """
        if base_symbol in self._resolved_symbols:
            return self._resolved_symbols[base_symbol]

        resolved = await asyncio.to_thread(self._resolve_symbol_sync, base_symbol)
        self._resolved_symbols[base_symbol] = resolved

        if resolved != base_symbol:
            log.info("Symbol resolved: %s -> %s", base_symbol, resolved)
        else:
            log.info("Symbol confirmed: %s (exact match)", base_symbol)

        return resolved

    async def get_latest_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        mt5 = self._mt5
        tf_attr = self._TF_MAP.get(timeframe)
        if not tf_attr:
            log.error("Unsupported timeframe: %s", timeframe)
            return []

        resolved = await self.resolve_symbol(symbol)

        def _fetch():
            mt5.symbol_select(resolved, True)
            tf_val = getattr(mt5, tf_attr)
            rates = mt5.copy_rates_from_pos(resolved, tf_val, 0, count)
            return rates

        rates = await asyncio.to_thread(_fetch)
        if rates is None or len(rates) == 0:
            err = mt5.last_error() if mt5 else "mt5 not initialized"
            log.warning(
                "0 bars returned for %s %s (resolved=%s). MT5 error: %s",
                symbol, timeframe, resolved, err,
            )
            return []

        tf_enum = Timeframe(timeframe)
        bars: list[Bar] = []
        for r in rates:
            bars.append(Bar(
                time=datetime.fromtimestamp(r["time"], tz=timezone.utc),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r["tick_volume"]),
                timeframe=tf_enum,
            ))
        return bars

    def _get_filling_mode(self, symbol: str) -> int:
        """Pick a filling mode the symbol actually supports.

        ``filling_mode`` is a bitmask of the modes the broker allows for the
        symbol. Sending an unsupported filling type is one of the most common
        causes of Exness order rejections, so we probe it explicitly and fall
        back to IOC if the info is unavailable.
        """
        mt5 = self._mt5
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC
        filling = getattr(info, "filling_mode", 0)
        # Bit 1 = FOK, Bit 2 = IOC (per MT5 SYMBOL_FILLING_* flags).
        if filling & 1:
            return mt5.ORDER_FILLING_FOK
        if filling & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    async def place_order(
        self, symbol: str, direction: Direction, lot: float,
        stop: float, tp: float, comment: str = "",
    ) -> OrderResult:
        mt5 = self._mt5
        symbol = await self.resolve_symbol(symbol)

        def _place():
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return OrderResult(False, message=f"No tick data for {symbol}")

            price = tick.ask if direction == Direction.LONG else tick.bid
            order_type = mt5.ORDER_TYPE_BUY if direction == Direction.LONG else mt5.ORDER_TYPE_SELL

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot),
                "type": order_type,
                "price": float(price),
                "sl": float(stop),
                "tp": float(tp),
                "deviation": 20,
                "magic": int(271828),
                "comment": _sanitize_mt5_comment(comment),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._get_filling_mode(symbol),
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                err = mt5.last_error()
                retcode = getattr(result, "retcode", "?")
                res_comment = getattr(result, "comment", "")
                log.error(
                    "Order rejected: retcode=%s comment=%r last_error=%s request=%s",
                    retcode, res_comment, err, request,
                )
                return OrderResult(
                    False,
                    message=f"Order rejected: retcode={retcode} comment={res_comment!r} last_error={err}",
                )
            return OrderResult(
                success=True,
                ticket=result.order,
                fill_price=result.price,
                fill_time=datetime.now(tz=timezone.utc),
            )

        return await asyncio.to_thread(_place)

    async def close_position(self, ticket: int, symbol: str) -> OrderResult:
        mt5 = self._mt5
        symbol = await self.resolve_symbol(symbol)

        def _close():
            positions = mt5.positions_get(symbol=symbol)
            pos = next((p for p in (positions or []) if p.ticket == ticket), None)
            if pos is None:
                return OrderResult(False, message="Position not found")

            tick = mt5.symbol_info_tick(symbol)
            price = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask
            opp_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(pos.volume),
                "type": opp_type,
                "position": ticket,
                "price": float(price),
                "deviation": 20,
                "magic": int(271828),
                "comment": _sanitize_mt5_comment("AI close"),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._get_filling_mode(symbol),
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                err = mt5.last_error()
                retcode = getattr(result, "retcode", "?")
                res_comment = getattr(result, "comment", "")
                log.error(
                    "Close rejected: retcode=%s comment=%r last_error=%s request=%s",
                    retcode, res_comment, err, request,
                )
                return OrderResult(
                    False,
                    message=f"Close failed: retcode={retcode} comment={res_comment!r} last_error={err}",
                )
            return OrderResult(True, ticket=ticket, fill_price=result.price, fill_time=datetime.now(tz=timezone.utc))

        return await asyncio.to_thread(_close)

    async def modify_position(
        self, ticket: int, symbol: str, stop: float | None = None, tp: float | None = None
    ) -> OrderResult:
        mt5 = self._mt5
        symbol = await self.resolve_symbol(symbol)

        def _modify():
            positions = mt5.positions_get(symbol=symbol)
            pos = next((p for p in (positions or []) if p.ticket == ticket), None)
            if pos is None:
                return OrderResult(False, message="Position not found")

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": symbol,
                "position": ticket,
                "sl": float(stop) if stop is not None else pos.sl,
                "tp": float(tp) if tp is not None else pos.tp,
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                return OrderResult(False, message=f"Modify failed: rc={getattr(result, 'retcode', '?')}")
            return OrderResult(True, ticket=ticket)

        return await asyncio.to_thread(_modify)

    async def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        mt5 = self._mt5
        if symbol:
            symbol = await self.resolve_symbol(symbol)

        def _get():
            if symbol:
                positions = mt5.positions_get(symbol=symbol) or []
            else:
                positions = mt5.positions_get() or []
            return [
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    direction=Direction.LONG if p.type == mt5.POSITION_TYPE_BUY else Direction.SHORT,
                    volume=p.volume,
                    open_price=p.price_open,
                    open_time=datetime.fromtimestamp(p.time, tz=timezone.utc),
                    stop_loss=p.sl,
                    take_profit=p.tp,
                    current_price=p.price_current,
                    profit=p.profit,
                    swap=p.swap,
                    comment=p.comment,
                )
                for p in positions
            ]

        return await asyncio.to_thread(_get)

    async def get_account_info(self) -> AccountInfo:
        mt5 = self._mt5

        def _info():
            info = mt5.account_info()
            if info is None:
                return AccountInfo(0, 0, 0, 0, 0)
            return AccountInfo(
                balance=info.balance,
                equity=info.equity,
                margin=info.margin,
                free_margin=info.margin_free,
                leverage=info.leverage,
                currency=info.currency,
                server=info.server,
                login=info.login,
            )

        return await asyncio.to_thread(_info)

    async def get_current_price(self, symbol: str) -> tuple[float, float]:
        mt5 = self._mt5
        symbol = await self.resolve_symbol(symbol)

        def _price():
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return (0.0, 0.0)
            return (tick.bid, tick.ask)

        return await asyncio.to_thread(_price)


# ---------------------------------------------------------------------------
# Exness Demo Broker
# ---------------------------------------------------------------------------


class ExnessDemoBroker(MT5Broker):
    """Exness-specific MT5 connection.

    Exness uses MT5 as the trading platform. This subclass configures
    Exness-specific server names and provides guidance on setup.

    Common Exness MT5 servers:
      - Exness-MT5Real     (live accounts)
      - Exness-MT5Trial    (demo accounts)
      - Exness-MT5Real2-15 (various regional servers)
    """

    EXNESS_DEMO_SERVERS = [
        "Exness-MT5Trial",
        "Exness-MT5Trial2",
        "Exness-MT5Trial3",
        "Exness-MT5Trial4",
        "Exness-MT5Trial5",
        "Exness-MT5Trial6",
        "Exness-MT5Trial7",
    ]

    def __init__(self, login: int, password: str, server: str = "Exness-MT5Trial", path: str = ""):
        super().__init__(login=login, password=password, server=server, path=path)

    async def connect(self) -> bool:
        connected = await super().connect()
        if connected:
            log.info("Connected to Exness demo via MT5 (server: %s)", self._server)
        return connected


# ---------------------------------------------------------------------------
# Paper Broker (cross-platform, no dependencies)
# ---------------------------------------------------------------------------


class PaperBroker(BrokerConnection):
    """Simulated broker for testing the signal loop without a real account.

    - Maintains virtual balance and tracks positions in-memory.
    - Uses cached parquet data or generates synthetic prices for bar data.
    - Simulates fills at current bar close (no slippage by default).
    - Works on any platform (macOS, Linux, Windows) with zero dependencies
      beyond pandas (already a project dependency).
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        data_dir: Path | None = None,
        spread_pips: float = 1.5,
        slippage_pips: float = 0.5,
    ):
        self._balance = initial_balance
        self._equity = initial_balance
        self._data_dir = data_dir
        self._spread_pips = spread_pips
        self._slippage_pips = slippage_pips

        self._positions: dict[int, Position] = {}
        self._next_ticket = 10001
        self._connected = False

        # Price state: updated each time bars are fetched
        self._last_prices: dict[str, tuple[float, float]] = {}  # symbol -> (bid, ask)
        self._bar_cache: dict[str, pd.DataFrame] = {}

    async def connect(self) -> bool:
        self._connected = True
        log.info(
            "Paper broker connected (balance=%.2f, spread=%.1f pips)",
            self._balance, self._spread_pips,
        )
        return True

    async def disconnect(self) -> None:
        self._connected = False
        log.info("Paper broker disconnected. Final balance: %.2f", self._balance)

    async def get_latest_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        tf_enum = Timeframe(timeframe)
        df = await self._load_data(symbol, timeframe)

        if df is None or df.empty:
            log.warning("Paper broker: no data available for %s %s", symbol, timeframe)
            return []

        # Return last `count` bars
        df_slice = df.tail(count)
        bars: list[Bar] = []
        for ts, row in df_slice.iterrows():
            bars.append(Bar(
                time=ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0)),
                timeframe=tf_enum,
            ))

        # Update simulated price from latest bar
        if bars:
            last = bars[-1]
            spread = self._spread_pips * 0.0001
            bid = last.close
            ask = bid + spread
            self._last_prices[symbol] = (bid, ask)

        return bars

    async def _load_data(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        cache_key = f"{symbol}_{timeframe}"
        if cache_key in self._bar_cache:
            return self._bar_cache[cache_key]

        if self._data_dir:
            # Try loading from parquet cache
            parquet_path = self._data_dir / f"{symbol}_{timeframe}.parquet"
            if parquet_path.exists():
                df = pd.read_parquet(parquet_path)
                if not df.empty:
                    self._bar_cache[cache_key] = df
                    log.info("Paper broker: loaded %d bars from %s", len(df), parquet_path)
                    return df

        # Fallback: try yfinance for recent data
        try:
            df = await asyncio.to_thread(self._fetch_yfinance, symbol, timeframe)
            if df is not None and not df.empty:
                self._bar_cache[cache_key] = df
                return df
        except Exception as e:
            log.debug("yfinance unavailable: %s", e)

        return None

    @staticmethod
    def _fetch_yfinance(symbol: str, timeframe: str) -> pd.DataFrame | None:
        """Fetch data via yfinance as a fallback price source."""
        try:
            import yfinance as yf
        except ImportError:
            return None

        # Map our symbol format to yfinance tickers
        yf_symbol = f"{symbol[:3]}{symbol[3:]}=X"  # EURUSD -> EURUSD=X
        interval_map = {"M1": "1m", "M5": "5m", "M15": "15m", "H1": "1h", "H4": "4h", "D1": "1d"}
        interval = interval_map.get(timeframe, "1h")

        period_map = {"M1": "7d", "M5": "60d", "M15": "60d", "H1": "730d", "H4": "730d", "D1": "max"}
        period = period_map.get(timeframe, "60d")

        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            return None

        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
        df.index = pd.to_datetime(df.index, utc=True)
        return df[["open", "high", "low", "close", "volume"]]

    async def place_order(
        self, symbol: str, direction: Direction, lot: float,
        stop: float, tp: float, comment: str = "",
    ) -> OrderResult:
        bid, ask = self._last_prices.get(symbol, (0.0, 0.0))
        if bid == 0:
            return OrderResult(False, message="No price data available for paper execution")

        # Simulate fill with slippage
        slippage = self._slippage_pips * 0.0001 * random.choice([1, -1, 0, 0])
        fill_price = (ask if direction == Direction.LONG else bid) + slippage

        ticket = self._next_ticket
        self._next_ticket += 1

        pos = Position(
            ticket=ticket,
            symbol=symbol,
            direction=direction,
            volume=lot,
            open_price=fill_price,
            open_time=datetime.now(tz=timezone.utc),
            stop_loss=stop,
            take_profit=tp,
            current_price=fill_price,
            profit=0.0,
            comment=comment,
        )
        self._positions[ticket] = pos

        log.info(
            "PAPER ORDER: %s %s %.2f lots @ %.5f (SL=%.5f TP=%.5f) ticket=%d",
            direction.value.upper(), symbol, lot, fill_price, stop, tp, ticket,
        )
        return OrderResult(True, ticket=ticket, fill_price=fill_price, fill_time=pos.open_time)

    async def close_position(self, ticket: int, symbol: str) -> OrderResult:
        if ticket not in self._positions:
            return OrderResult(False, message=f"Paper position {ticket} not found")

        pos = self._positions.pop(ticket)
        bid, ask = self._last_prices.get(symbol, (pos.open_price, pos.open_price))
        close_price = bid if pos.direction == Direction.LONG else ask

        # Calculate P&L
        pips = (close_price - pos.open_price) * 10000
        if pos.direction == Direction.SHORT:
            pips = -pips
        pnl = pips * pos.volume * 10.0  # pip_value_per_lot = $10 for EURUSD standard lot
        self._balance += pnl
        self._equity = self._balance

        log.info(
            "PAPER CLOSE: ticket=%d %s %.5f -> %.5f pnl=%.2f (%.1f pips)",
            ticket, pos.direction.value, pos.open_price, close_price, pnl, pips,
        )
        return OrderResult(True, ticket=ticket, fill_price=close_price, fill_time=datetime.now(tz=timezone.utc))

    async def modify_position(
        self, ticket: int, symbol: str, stop: float | None = None, tp: float | None = None
    ) -> OrderResult:
        if ticket not in self._positions:
            return OrderResult(False, message=f"Paper position {ticket} not found")

        pos = self._positions[ticket]
        if stop is not None:
            pos.stop_loss = stop
        if tp is not None:
            pos.take_profit = tp
        log.debug("PAPER MODIFY: ticket=%d new_sl=%.5f new_tp=%.5f", ticket, pos.stop_loss, pos.take_profit)
        return OrderResult(True, ticket=ticket)

    async def get_open_positions(self, symbol: str | None = None) -> list[Position]:
        positions = list(self._positions.values())
        if symbol:
            positions = [p for p in positions if p.symbol == symbol]

        # Update current prices and unrealized P&L
        for pos in positions:
            bid, ask = self._last_prices.get(pos.symbol, (pos.open_price, pos.open_price))
            pos.current_price = bid if pos.direction == Direction.LONG else ask
            pips = (pos.current_price - pos.open_price) * 10000
            if pos.direction == Direction.SHORT:
                pips = -pips
            pos.profit = pips * pos.volume * 10.0

        return positions

    async def get_account_info(self) -> AccountInfo:
        # Calculate equity including unrealized P&L
        unrealized = sum(p.profit for p in self._positions.values())
        self._equity = self._balance + unrealized
        return AccountInfo(
            balance=self._balance,
            equity=self._equity,
            margin=0.0,
            free_margin=self._equity,
            leverage=100,
            currency="USD",
            server="paper",
            login=0,
        )

    async def get_current_price(self, symbol: str) -> tuple[float, float]:
        return self._last_prices.get(symbol, (0.0, 0.0))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_broker(
    broker_type: str,
    login: int = 0,
    password: str = "",
    server: str = "",
    path: str = "",
    initial_balance: float = 10000.0,
    data_dir: Path | None = None,
) -> BrokerConnection:
    """Factory function to create the appropriate broker instance."""
    if broker_type == "mt5":
        return MT5Broker(login=login, password=password, server=server, path=path)
    elif broker_type == "exness":
        return ExnessDemoBroker(login=login, password=password, server=server, path=path)
    elif broker_type == "paper":
        return PaperBroker(initial_balance=initial_balance, data_dir=data_dir)
    else:
        raise ValueError(f"Unknown broker type: {broker_type!r}. Use 'mt5', 'exness', or 'paper'.")
