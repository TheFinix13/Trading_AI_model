"""Live trading configuration."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LiveConfig:
    """Configuration for the live/paper trading loop.

    All fields can be overridden via environment variables (LIVE_ prefix)
    or the `[live]` section in config YAML.
    """

    symbol: str = "EURUSD"
    timeframes: list[str] = field(default_factory=lambda: ["H1"])
    check_interval_seconds: int = 60
    broker_type: str = "paper"  # "mt5", "exness", "paper"

    # MT5/Exness credentials (loaded from .env)
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str = ""

    # Risk parameters (override global risk config for live)
    risk_per_trade_pct: float = 1.0
    max_daily_dd_pct: float = 3.0
    max_open_positions: int = 1
    lot_size_override: float | None = None

    # Notification
    telegram_enabled: bool = True

    # ML gate
    score_threshold: float = 0.55

    # Position management
    move_be_at_r: float = 1.0
    trailing_stop_enabled: bool = False
    trailing_stop_distance_pips: float = 20.0

    # Kill switch
    kill_file: str = "kill.txt"

    # Paper broker settings
    paper_initial_balance: float = 10000.0
    paper_use_cached_data: bool = True

    # Reconnection
    max_reconnect_attempts: int = 5
    reconnect_delay_seconds: int = 10
