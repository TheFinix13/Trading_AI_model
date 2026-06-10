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
    check_interval_seconds: int = 30
    broker_type: str = "paper"  # "mt5", "exness", "paper"

    # MT5/Exness credentials (loaded from .env)
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str = ""

    # Trading mode: "anticipation" | "reaction" | "hybrid".
    # hybrid (default): anticipation marks levels, reaction pulls the trigger.
    mode: str = "hybrid"

    # Risk parameters (override global risk config for live)
    risk_per_trade_pct: float = 1.0
    max_daily_dd_pct: float = 3.0
    max_open_positions: int = 1
    lot_size_override: float | None = None

    # Adaptive risk band for conviction-scaled sizing (fractions of balance).
    risk_min_pct: float = 0.005
    risk_max_pct: float = 0.02

    # ── Post-loss cooldown / no-revenge guard ──
    # Hard ceiling on the risk a SINGLE trade may take (fraction of balance).
    # An oversized/override lot that would risk more than this is clamped down
    # (never below the broker minimum lot). Prevents the Jun-2 1.0-lot-on-$100.
    max_trade_risk_pct: float = 0.02
    revenge_guard_enabled: bool = True
    post_loss_cooldown_minutes: float = 60.0   # no new entry for N minutes after a loss
    post_loss_cooldown_bars: int = 2           # …or N bars (bar-driven harnesses)
    post_loss_risk_multiplier: float = 0.5     # halve next trade's risk until a win
    max_consecutive_losses: int = 3            # circuit breaker: halt session after N losses
    catastrophic_loss_frac: float = 0.10       # a single loss >= 10% of balance halts session
    halt_on_stop_out: bool = True
    # A strong reaction OPPOSITE to the last loss may bypass the cooldown (a
    # committed flip into a reversal is not revenge). The circuit breaker / stop-
    # out halt are never bypassed. 0 disables the override.
    post_loss_cooldown_override_conviction: float = 0.80
    post_loss_cooldown_override_opposite_only: bool = True

    # ── Synthetic ("soft") stop layer: stop-hunt mitigation ──
    # Soft stop = the real risk level, held in memory, acted on only when a bar
    # CLOSES beyond it (wick-proof). A wide catastrophe stop rests on the broker
    # as an offline backstop. See agent/live/soft_stop.py.
    soft_stop_enabled: bool = True
    soft_stop_confirm_on_close: bool = True
    catastrophe_stop_mult: float = 2.5
    soft_stop_panic_mult: float = 1.0
    soft_stop_min_catastrophe_pips: float = 8.0

    # Live journal + learning store
    journal_root: str = "data/journal/live"

    # Notification
    telegram_enabled: bool = True

    # ML gate
    score_threshold: float = 0.55

    # Position management
    move_be_at_r: float = 1.0
    trailing_stop_enabled: bool = False
    trailing_stop_distance_pips: float = 20.0

    # ── Partial scale-out (KEEP-INFRA, default OFF) ──
    # Wired through PositionMonitor; remained as infra after the v2 reset
    # because the underlying SoftStop / monitor loop already handles it. The
    # Phase-C / Phase-D allocator + managed-exit policy layers were burned.
    partial_exit_enabled: bool = False
    partial_at_r: float = 1.0
    partial_fraction: float = 0.5
    partial_move_to_be: bool = True

    # Kill switch
    kill_file: str = "kill.txt"

    # Paper broker settings
    paper_initial_balance: float = 10000.0
    paper_use_cached_data: bool = True

    # Reconnection
    max_reconnect_attempts: int = 5
    reconnect_delay_seconds: int = 10
