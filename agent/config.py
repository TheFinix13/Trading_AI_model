"""Configuration loading (v2 reset).

What survives after the audit (see `docs/audit/preservation_list.md` and
`docs/audit/redundancy_map.md`):

* :class:`RiskConfig`      — sizing floor/cap, daily DD halt, max open positions
* :class:`SessionConfig`   — timezone + no-trade windows
* :class:`DetectorsConfig` — per-detector knobs (swing lookback, FVG min size,
                              zone impulse) and the quality-graded fib block
* :class:`HTFConfig`       — HTF lookback/zone-depth (alignment booster reset)
* :class:`ReactionConfig`  — reaction-engine knobs (impulse override, level
                              proximity, conviction). Session axis neutralised.
* :class:`BacktestConfig`  — spread/slippage/commission + capital base
* :class:`EvalConfig`      — locked dev/sealed split + bootstrap settings

What was burned:

* ``GateProfile``, ``GATE_PROFILES``         — per-strategy override toggles
* ``MLConfig``                                — scorer paths + score thresholds
* ``RankingConfig``                           — SQS / leaderboard / regime
* ``LiquidityConfig``                         — LZI two-phase choreography
* ``BacktestGateConfig`` / ``DemoConfig``     — dev-span pass/fail thresholds
* ``LiveTradingConfig``                       — duplicated by `agent.live.config.LiveConfig`
* ``RulesConfig``                             — the entire v1 confluence stack
"""
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


class FibConfig(BaseModel):
    """Quality-graded Fibonacci retracement configuration."""
    active_levels: list[float] = [0.382, 0.500, 0.618, 0.705]
    ote_zone_start: float = 0.618
    ote_zone_end: float = 0.710
    min_impulse_quality: float = 35.0
    min_impulse_pips: float = 20.0
    include_786_as_invalidation: bool = True
    extension_levels: list[float] = [1.272, 1.618, 2.0]


class DetectorsConfig(BaseModel):
    swing_lookback: int = 5
    zone_min_impulse_pips: float = 30.0
    zone_max_age_bars: int = 500
    fvg_min_size_pips: float = 5.0
    fib_levels: list[float] = [0.382, 0.5, 0.618, 0.786]
    trendline_min_swings: int = 2
    liquidity_wick_min_ratio: float = 2.0
    fib: FibConfig = FibConfig()


class HTFConfig(BaseModel):
    """Higher-timeframe context layer configuration."""
    enabled: bool = True
    lookback_days: int = 5
    h4_lookback_bars: int = 30
    d1_lookback_bars: int = 20
    # Zones (demand/supply) persist for months on the daily until consumed, so
    # they need a far deeper lookback than the bias/level window.
    d1_zone_lookback_bars: int = 180
    require_htf_alignment: bool = False
    # Reset to neutral for the v2 baseline. The ablation grid is the only
    # acceptable way to discover whether HTF alignment boosts a cell.
    htf_alignment_boost: float = 0.0
    htf_misalignment_penalty: float = 0.0
    update_interval_bars: int = 4


class ReactionConfig(BaseModel):
    """Reaction engine: present-tense commitment detection.

    Measures *committed* price action on the just-closed bar(s) — displacement,
    range expansion, momentum, order-flow imbalance — and fires when conviction
    is high AND price is acting on a pre-marked level. All thresholds live here
    so they can be tuned without touching code.
    """

    enabled: bool = True

    # ── Component 1: Displacement (body vs ATR, strong directional close) ──
    displacement_atr_mult: float = 1.3
    displacement_close_frac: float = 0.62

    # ── Component 2: Range expansion (volatility ignition) ──
    expansion_lookback: int = 20
    expansion_mult: float = 1.5
    expansion_bars: int = 1

    # ── Component 3: Momentum (ROC normalised by ATR + consecutive closes) ──
    momentum_lookback: int = 4
    momentum_atr_norm: float = 2.0

    # ── Component 4: Order-flow imbalance proxy ──
    imbalance_use_volume: bool = True
    imbalance_volume_lookback: int = 10

    # ── Composite blend ──
    weight_displacement: float = 0.35
    weight_expansion: float = 0.20
    weight_momentum: float = 0.25
    weight_imbalance: float = 0.20
    # Conviction gate. v2 default is the neutral 0.40 prior; the ablation grid
    # is the only acceptable way to choose a tighter floor per cell.
    conviction_threshold: float = 0.40

    # ── Level proximity ──
    level_proximity_atr_mult: float = 0.8
    require_level: bool = True

    # ── Impulse override (react to clean impulsive moves in open space) ──
    impulse_override_enabled: bool = True
    impulse_min_conviction: float = 0.66
    impulse_min_displacement: float = 0.45
    impulse_min_expansion: float = 0.60

    # ── ERL / IRL liquidity magnets (quarantined — see docs/10 §10.6) ──
    liquidity_magnet_enabled: bool = False
    range_lookback_bars: int = 120
    magnet_proximity_atr_mult: float = 0.6
    magnet_conviction_boost: float = 0.05
    magnet_chase_penalty: float = 0.15
    range_premium_frac: float = 0.66

    # ── Stop / target ──
    stop_atr_mult: float = 1.1
    stop_buffer_pips: float = 3.0
    fallback_rr: float = 2.0
    min_rr: float = 1.2

    # ── HTF directional filter — neutralised for v2 baseline ──
    reaction_htf_boost: float = 0.0
    reaction_htf_penalty: float = 0.0

    # ── Session axis ──
    # Session is an explicit ablation AXIS in v2 (London / NY / Asia / all),
    # not a built-in conviction modifier. ``session_aware`` is retained so the
    # legacy call-site signature still accepts a ``session_label`` kwarg, but
    # the engine no longer mutates conviction based on it.
    session_aware: bool = False
    high_impulse_sessions: list[str] = []
    session_conviction_boost: float = 0.0
    off_session_conviction_penalty: float = 0.0

    # ── Anticipation → reaction flip ──
    flip_enabled: bool = True
    flip_min_conviction: float = 0.66


class BacktestConfig(BaseModel):
    initial_balance: float = 10000.0
    # Default (D1) costs. Per-TF overrides are below; ``cost_for(tf)`` honours
    # them so each ablation cell pays the spread / slippage actually quoted on
    # that timeframe. Without per-TF costs, M1 cells look artificially edgy:
    # 1 pip of spread is ~5% of an M1 ATR but ~1% of an H1 ATR.
    spread_pips: float = 1.0
    commission_per_lot: float = 7.0
    slippage_pips: float = 0.5
    pip_value_per_lot: float = 10.0
    # Stop management (used by the position monitor's BE step).
    move_be_at_r: float = 1.0
    be_lock_r: float = 0.0
    # Per-TF cost overrides (EURUSD retail). Each entry is
    # ``{"spread": pips, "slippage": pips}``. Lower TFs eat a much larger
    # fraction of their own ATR, so they need realistically wider costs to
    # avoid the "M1 looks like alpha" artefact. ``commission_per_lot`` and
    # ``pip_value_per_lot`` are broker constants and stay TF-invariant.
    cost_by_tf: dict[str, dict[str, float]] = {
        "D1":  {"spread": 1.0, "slippage": 0.5},
        "H4":  {"spread": 1.0, "slippage": 0.5},
        "H1":  {"spread": 1.2, "slippage": 0.6},
        "M30": {"spread": 1.4, "slippage": 0.7},
        "M15": {"spread": 1.6, "slippage": 0.8},
        "M5":  {"spread": 2.0, "slippage": 1.0},
        "M3":  {"spread": 2.5, "slippage": 1.2},
        "M1":  {"spread": 3.0, "slippage": 1.5},
    }

    def cost_for(self, timeframe: str) -> tuple[float, float, float]:
        """Return ``(spread_pips, slippage_pips, commission_per_lot)`` for ``timeframe``.

        Falls back to the top-level ``spread_pips`` / ``slippage_pips`` when the
        TF isn't listed in ``cost_by_tf``. ``commission_per_lot`` is a broker
        constant and doesn't vary by TF.
        """
        override = self.cost_by_tf.get(timeframe)
        if override is None:
            return self.spread_pips, self.slippage_pips, self.commission_per_lot
        return (
            float(override.get("spread", self.spread_pips)),
            float(override.get("slippage", self.slippage_pips)),
            self.commission_per_lot,
        )


class EvalConfig(BaseModel):
    """Locked out-of-sample evaluation protocol (see docs/10).

    The split is fixed here so decisions can't silently drift onto data we've
    already seen. The primary OOS read is a chunked alpha walk over the
    development span; the sealed window is touched only once, at final sign-off.
    """
    dev_start: str = "2015-01-01"
    dev_end: str = "2025-12-01"
    sealed_test_start: str = "2025-12-01"
    sealed_test_end: str = "2026-06-09"
    train_months: int = 24
    test_months: int = 3
    embargo_days: int = 2
    bootstrap_resamples: int = 1000
    ci_level: float = 0.95


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
    reaction: ReactionConfig = ReactionConfig()
    htf: HTFConfig = HTFConfig()
    backtest: BacktestConfig = BacktestConfig()
    eval: EvalConfig = EvalConfig()

    mode: str = "backtest"
    # IANA timezone for cosmetic / dashboard display. Bars stay in UTC.
    display_timezone: str = "America/New_York"
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
    # Drop any sections that belong to burned config classes so a stale YAML
    # doesn't fail validation against the v2 schema.
    for burned in ("rules", "ml", "ranking", "liquidity", "live", "demo",
                   "backtest_gate", "gate_profiles"):
        data.pop(burned, None)

    cfg = Config(**data)

    cfg.mode = os.getenv("AGENT_MODE", cfg.mode)
    cfg.mt5_login = os.getenv("MT5_LOGIN", cfg.mt5_login)
    cfg.mt5_password = os.getenv("MT5_PASSWORD", cfg.mt5_password)
    cfg.mt5_server = os.getenv("MT5_SERVER", cfg.mt5_server)
    cfg.mt5_path = os.getenv("MT5_PATH", cfg.mt5_path)
    cfg.symbol = os.getenv("SYMBOL", cfg.symbol)
    cfg.primary_timeframe = os.getenv("TIMEFRAME_PRIMARY", cfg.primary_timeframe)

    if v := os.getenv("RISK_PCT"):
        cfg.risk.pct_target = float(v)
    if v := os.getenv("RISK_FLOOR_PCT"):
        cfg.risk.pct_floor = float(v)
    if v := os.getenv("DAILY_DD_HALT_PCT"):
        cfg.risk.daily_dd_halt_pct = float(v)

    if v := os.getenv("DATA_DIR"):
        cfg.data_dir = Path(v)
    if v := os.getenv("MODEL_DIR"):
        cfg.model_dir = Path(v)
    if v := os.getenv("JOURNAL_DB"):
        cfg.journal_db = Path(v)
    if v := os.getenv("KILL_SWITCH_FILE"):
        cfg.kill_switch_file = Path(v)

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.model_dir.mkdir(parents=True, exist_ok=True)

    return cfg
