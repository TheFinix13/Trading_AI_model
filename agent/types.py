"""Core domain types shared across modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Timeframe(str, Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def minutes(self) -> int:
        return {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}[self.value]


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: Timeframe

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


@dataclass
class Swing:
    time: datetime
    price: float
    is_high: bool
    bar_index: int


@dataclass
class Zone:
    """Supply or demand zone."""
    direction: Direction  # LONG = demand, SHORT = supply
    top: float
    bottom: float
    created_at: datetime
    created_bar_index: int
    impulse_pips: float
    mitigated: bool = False
    mitigated_at: datetime | None = None
    mitigated_bar_index: int | None = None

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


@dataclass
class FVG:
    """Fair Value Gap."""
    direction: Direction
    top: float
    bottom: float
    created_at: datetime
    created_bar_index: int
    size_pips: float
    filled: bool = False
    filled_at: datetime | None = None


@dataclass
class BreakOfStructure:
    direction: Direction
    broken_swing_price: float
    broken_at: datetime
    broken_bar_index: int


@dataclass
class FibLevel:
    impulse_start: float
    impulse_end: float
    direction: Direction
    levels: dict[float, float]  # 0.382 -> price, 0.5 -> price, etc.
    created_at: datetime


@dataclass
class Trendline:
    slope: float
    intercept: float
    anchors: list[Swing]
    direction: Direction
    valid: bool = True

    def price_at(self, bar_index: int) -> float:
        return self.slope * bar_index + self.intercept


@dataclass
class LiquidityWick:
    """A long wick that pierced a recent swing high/low (stop hunt)."""
    direction: Direction  # which side liquidity was grabbed (LONG = buyside grab above highs)
    wick_top: float
    wick_bottom: float
    time: datetime
    bar_index: int
    wick_to_body_ratio: float


@dataclass
class Setup:
    """A complete confluence setup ready to be evaluated for entry."""
    direction: Direction
    timeframe: Timeframe
    detected_at: datetime
    detected_bar_index: int

    entry: float
    stop: float
    take_profit: float

    confluences: list[str] = field(default_factory=list)
    zone: Zone | None = None
    fvg: FVG | None = None
    fib: FibLevel | None = None
    bos: BreakOfStructure | None = None
    trendline: Trendline | None = None
    liquidity_wick: LiquidityWick | None = None

    features: dict[str, float] = field(default_factory=dict)
    ml_score: float | None = None

    @property
    def stop_pips(self) -> float:
        return abs(self.entry - self.stop) * 10000

    @property
    def reward_pips(self) -> float:
        return abs(self.take_profit - self.entry) * 10000

    @property
    def rr(self) -> float:
        if self.stop_pips == 0:
            return 0.0
        return self.reward_pips / self.stop_pips


@dataclass
class Trade:
    setup: Setup
    direction: Direction
    entry_time: datetime
    entry_price: float
    stop_price: float
    tp_price: float
    lot_size: float

    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None  # "tp", "sl", "manual", "circuit_breaker"

    pnl: float = 0.0
    pnl_pips: float = 0.0
    commission: float = 0.0

    # Excursion tracking. MAE = worst price reached against the position; MFE = best.
    # Both stored as absolute pip distance from entry (always >= 0).
    mae_pips: float = 0.0
    mfe_pips: float = 0.0
    bars_held: int = 0

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def is_winner(self) -> bool | None:
        if self.is_open:
            return None
        return self.pnl > 0
