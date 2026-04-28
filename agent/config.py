"""Configuration loading. YAML config + .env overrides."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class RiskConfig(BaseModel):
    pct_target: float = 0.01
    pct_floor: float = 0.03
    pct_floor_threshold_account: float = 300.0
    daily_dd_halt_pct: float = 0.03
    max_open_positions: int = 1
    lot_step: float = 0.01
    lot_min: float = 0.01
    lot_hard_cap_under_300: float = 0.01
    lot_hard_cap_under_1000: float = 0.10
    lot_hard_cap: float = 1.0


class NoTradeWindow(BaseModel):
    name: str
    day_of_week: int
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class SessionConfig(BaseModel):
    timezone: str = "Europe/London"
    no_trade_windows: list[NoTradeWindow] = []
    # Whole days to block from trading. Names are case-insensitive (e.g. "Wed",
    # "wednesday"). The journal showed Wednesday is consistently unprofitable on
    # EURUSD so it's a sensible default to add when going live with limited capital.
    no_trade_days: list[str] = []


class DetectorsConfig(BaseModel):
    swing_lookback: int = 5
    zone_min_impulse_pips: float = 30.0
    zone_max_age_bars: int = 500
    fvg_min_size_pips: float = 5.0
    fib_levels: list[float] = [0.382, 0.5, 0.618, 0.786]
    trendline_min_swings: int = 2
    liquidity_wick_min_ratio: float = 2.0


class RulesConfig(BaseModel):
    min_confluences: int = 1
    required_factors: list[str] = ["zone"]
    optional_factors: list[str] = ["bos", "fib", "trendline", "liquidity_wick", "htf_alignment"]
    rr_min: float = 1.5
    stop_buffer_pips: float = 5.0

    # Risk-aligned stop cap. When `enforce_live_stop_cap` is True, the rule engine rejects
    # setups whose stop_pips exceeds what the live account can ever absorb at min lot
    # within the risk floor:  max_stop_pips = (live_min_balance * pct_floor) / (lot_min * pip_value).
    # Disable for pure edge validation on a $10k backtest balance; enable when checking
    # whether the live $100 account can actually trade these setups.
    enforce_live_stop_cap: bool = False
    live_min_balance: float = 100.0

    # Higher-timeframe (HTF) bias filter. When enabled, setups on M15/H1 are confirmed
    # against D1+H4 trend and active HTF zones. Modes:
    #   - 'off': don't use HTF context at all (default).
    #   - 'advisory': add 'htf_bias_long'/'htf_bias_short'/'htf_zone_*' tags to the setup
    #     so the discoverer can learn to weight them, but never block a trade.
    #   - 'strict': block any LTF setup whose direction contradicts the HTF trend.
    htf_bias_mode: str = "off"
    htf_bias_min_slope_pips: float = 0.5  # below this, HTF trend is treated as neutral


class MLConfig(BaseModel):
    enabled: bool = True
    prob_threshold: float = 0.55
    walkforward_train_months: int = 24
    walkforward_test_months: int = 3
    refit_frequency: str = "weekly"


class BacktestConfig(BaseModel):
    initial_balance: float = 10000.0
    spread_pips: float = 1.0
    commission_per_lot: float = 7.0
    slippage_pips: float = 0.5
    pip_value_per_lot: float = 10.0

    # Stop management. Once MFE crosses `move_be_at_r` (in R units, where 1R = stop_pips),
    # snap the stop to entry + `be_lock_r` * stop_pips in our favor. Setting move_be_at_r
    # to 0 disables this feature. Set ~1.0 to address spike-out losses where the trade
    # went 3R+ in our favor before reversing to -1R.
    move_be_at_r: float = 1.0
    be_lock_r: float = 0.0  # 0 = pure breakeven; 0.2 = lock in 0.2R


class DemoConfig(BaseModel):
    start_balance: float = 100.0
    target_balance: float = 1000.0
    max_dd_pct: float = 0.25
    max_single_trade_profit_share: float = 0.15
    min_trades_required: int = 200


class BacktestGateConfig(BaseModel):
    profit_factor_min: float = 1.3
    max_dd_pct: float = 0.20
    min_trades: int = 100
    require_oos_pass: bool = True
    require_regime_pass: bool = True


class Timeframes(BaseModel):
    htf: str = "D1"
    mtf: str = "H4"
    ltf: str = "H1"
    ttf: str = "M15"


class Config(BaseModel):
    symbol: str = "EURUSD"
    timeframes: Timeframes = Timeframes()
    primary_timeframe: str = "H1"
    risk: RiskConfig = RiskConfig()
    session: SessionConfig = SessionConfig()
    detectors: DetectorsConfig = DetectorsConfig()
    rules: RulesConfig = RulesConfig()
    ml: MLConfig = MLConfig()
    backtest: BacktestConfig = BacktestConfig()
    demo: DemoConfig = DemoConfig()
    backtest_gate: BacktestGateConfig = BacktestGateConfig()

    mode: str = "backtest"
    mt5_login: str = ""
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str = ""
    data_dir: Path = PROJECT_ROOT / "data" / "parquet"
    model_dir: Path = PROJECT_ROOT / "models"
    journal_db: Path = PROJECT_ROOT / "journal.db"
    kill_switch_file: Path = PROJECT_ROOT / "kill_switch"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_config(yaml_path: str | None = None) -> Config:
    """Load merged config from YAML + env. Cached after first call."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)

    yaml_file = Path(yaml_path) if yaml_path else PROJECT_ROOT / "config" / "default.yaml"
    data = _load_yaml(yaml_file)

    cfg = Config(**data)

    cfg.mode = os.getenv("AGENT_MODE", cfg.mode)
    cfg.mt5_login = os.getenv("MT5_LOGIN", cfg.mt5_login)
    cfg.mt5_password = os.getenv("MT5_PASSWORD", cfg.mt5_password)
    cfg.mt5_server = os.getenv("MT5_SERVER", cfg.mt5_server)
    cfg.mt5_path = os.getenv("MT5_PATH", cfg.mt5_path)
    cfg.symbol = os.getenv("SYMBOL", cfg.symbol)
    cfg.primary_timeframe = os.getenv("TIMEFRAME_PRIMARY", cfg.primary_timeframe)

    if (v := os.getenv("RISK_PCT")):
        cfg.risk.pct_target = float(v)
    if (v := os.getenv("RISK_FLOOR_PCT")):
        cfg.risk.pct_floor = float(v)
    if (v := os.getenv("DAILY_DD_HALT_PCT")):
        cfg.risk.daily_dd_halt_pct = float(v)

    if (v := os.getenv("DATA_DIR")):
        cfg.data_dir = Path(v)
    if (v := os.getenv("MODEL_DIR")):
        cfg.model_dir = Path(v)
    if (v := os.getenv("JOURNAL_DB")):
        cfg.journal_db = Path(v)
    if (v := os.getenv("KILL_SWITCH_FILE")):
        cfg.kill_switch_file = Path(v)

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.model_dir.mkdir(parents=True, exist_ok=True)

    return cfg
