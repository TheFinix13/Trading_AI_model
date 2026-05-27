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


class GateProfile(BaseModel):
    """Per-strategy gate override. Each flag controls whether a specific gate
    applies to this strategy. True = gate is active, False = gate is bypassed.

    Strategies with self-contained quality control (like LZI retest) can
    disable redundant gates while keeping essential safety gates.
    """
    name: str = "default"

    # Essential safety gates (should almost always be True)
    check_rr_minimum: bool = True
    check_daily_dd_halt: bool = True
    check_max_positions: bool = True
    check_stop_bounds: bool = True

    # Quality gates (can be relaxed for self-validating strategies)
    require_precision_partner: bool = True
    require_structural_anchor: bool = True
    require_close_confirmation: bool = True
    reject_false_breakouts: bool = True
    require_fvg_or_sweep_with_bos: bool = True
    check_blocked_sessions: bool = True
    check_blocked_hours: bool = True
    check_min_confluences: bool = True
    apply_caution_days_boost: bool = True
    apply_ml_scorer: bool = True

    # ML override threshold (if apply_ml_scorer is True but at a different threshold)
    ml_score_override: float | None = None

    # If set, overrides global blocked_hours_ny for this strategy
    blocked_hours_override: list[int] | None = None


GATE_PROFILE_DEFAULT = GateProfile(name="default")

GATE_PROFILE_LZI = GateProfile(
    name="lzi_retest",
    require_precision_partner=False,
    require_structural_anchor=False,
    require_close_confirmation=False,
    reject_false_breakouts=False,
    require_fvg_or_sweep_with_bos=False,
    check_blocked_hours=True,
    blocked_hours_override=[13],
    check_min_confluences=False,
    apply_caution_days_boost=False,
    apply_ml_scorer=True,
    ml_score_override=0.40,
)

GATE_PROFILE_FVG = GateProfile(
    name="fvg_retest",
    require_precision_partner=False,   # FVG IS the precision partner
    require_structural_anchor=False,   # Quality scoring + reaction confirmation replaces this
    require_close_confirmation=False,  # Reaction candle IS the confirmation
    reject_false_breakouts=True,       # FVGs near false breakouts are bad
    require_fvg_or_sweep_with_bos=False,  # Not BOS-based
    check_blocked_hours=True,
    check_min_confluences=False,       # Quality score replaces confluence counting
    apply_caution_days_boost=True,     # Keep caution on Thu/Fri for FVG
    apply_ml_scorer=True,              # Use generic scorer until FVG-specific one exists
    ml_score_override=0.30,            # Slightly relaxed from 0.35
)

GATE_PROFILE_SD_ZONE = GateProfile(
    name="sd_zone_retest",
    require_precision_partner=False,    # The zone IS the core level
    require_structural_anchor=False,    # Quality scoring + reaction confirmation replaces this
    require_close_confirmation=False,   # Reaction IS confirmation
    reject_false_breakouts=True,        # Keep
    require_fvg_or_sweep_with_bos=False,
    check_blocked_hours=True,
    check_min_confluences=False,        # Quality score replaces
    apply_caution_days_boost=True,
    apply_ml_scorer=True,
    ml_score_override=0.30,
)

GATE_PROFILES: dict[str, GateProfile] = {
    "default": GATE_PROFILE_DEFAULT,
    "lzi_retest": GATE_PROFILE_LZI,
    "LiquidityGrabReversal": GATE_PROFILE_LZI,
    "fvg_retest": GATE_PROFILE_FVG,
    "FVGRetest": GATE_PROFILE_FVG,
    "sd_zone_retest": GATE_PROFILE_SD_ZONE,
    "SDZoneRetest": GATE_PROFILE_SD_ZONE,
}


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
    # Caution days philosophy: Thursday and Friday have historically lower WR
    # (Thu: 11-30%, Fri: 22-24% in various test windows). Instead of blocking
    # them outright (which would miss legitimate setups), we:
    #   1. Raise the ML score threshold by +caution_score_boost (0.15)
    #   2. Require at least one positively-scored confluence booster
    #   3. The human partner can always override manually
    # This makes the system MORE selective on these days, not blind to them.
    no_trade_days: list[str] = []  # No days completely blocked — human can always trade
    caution_days: list[str] = ["Thu", "Fri"]  # Both require elevated threshold

    # Extra gates for caution days: require at least one confluence booster with
    # positive lift (from the optimizer) to fire on caution days. This ensures
    # that Thursday/Friday trades only happen when there's structural support,
    # not just a marginal signal.
    caution_require_positive_booster: bool = True


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


class RulesConfig(BaseModel):
    min_confluences: int = 1
    # Cap: setups with MORE than this many confluences are rejected. The v8 OOS
    # backtest showed 5+ confluences were losers on the 2024-2026 window
    # (31.6% WR / -97 pips), but 6-confl trades were winners in 2025-2026
    # (66.7% WR / +44 pips). Evidence is mixed; set to 0 to disable.
    # When combined with day blocking, the cap over-filters.
    max_confluences: int = 0
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

    # Candle-close confirmation gate. When True, after a setup is detected on bar i,
    # the engine waits for bar i+1 to close in the trade direction (bullish close
    # for long, bearish close for short) AND for bar i+1's range to NOT have hit
    # the proposed stop. Only then is entry placed at bar i+2 open. This blocks
    # the classic "spike-and-reverse" / fake-breakout entries that gave the M15
    # journal so many same-day losses.
    require_close_confirmation: bool = True

    # False-breakout filter. When True, setups whose detection bar wicked beyond
    # the entry zone but closed back inside (a stop-hunt fake) are rejected.
    # This is the protection that would have blocked trade #9 in the user's
    # journal critique.
    reject_false_breakouts: bool = True

    # ----- Precision gates (added 2026-05-03 from W18 detector audit) ---------
    # The audit (`scripts/audit_detectors.py`) showed that, on the user's first
    # ingested week, three signal classes generated almost all the bleed:
    #
    #   * `session_london_ny_overlap` alone   ->  20% WR / -153 pips / 10 trades
    #   * `bos`-only entries                  ->  39% WR / -144 pips / 18 trades
    #   * `zone`-only entries                 ->  47% WR /  -84 pips / 38 trades
    #
    # While the precision *winners* clustered tightly around an FVG / sweep /
    # daily-level partner. We expose the relevant filters here so backtests and
    # live runs can be tuned without touching code. Defaults reflect what the
    # audit said was correct for EURUSD this week; tune as more weeks land.

    # If True, reject any setup whose confluence stack lacks a "displacement"
    # tag — something that says price has *committed* (FVG just left behind, or
    # a fresh liquidity sweep). This is what turns a level (zone / fib / BOS
    # alone) into a level price is *acting on*.
    #
    # Empirical justification (W18 audit, scripts/audit_detectors.py):
    #   * fvg + zone               -> 80% WR (v1) / 89% WR (v2)
    #   * sweep_swing_* + zone     -> 100% WR
    #   * bare zone or bare bos    -> 39-47% WR, -84 to -144 pips
    #
    # Daily-level proximity (`near_PDX`) is necessary but not sufficient — it
    # marks where to look, not whether to enter. We exclude it from the
    # precision-partner whitelist so it can't single-handedly let a noisy
    # bos-only setup pass.
    require_precision_partner: bool = True
    precision_partner_tags: list[str] = [
        "fvg",
        "sweep_PDH", "sweep_PDL", "sweep_PDM",
        "sweep_PWH", "sweep_PWL", "sweep_PWM",
        "sweep_swing_high", "sweep_swing_low",
        "sweep_equal_highs", "sweep_equal_lows",
    ]
    # Sessions to block trading in. London/NY-overlap was a -153p loser; we
    # require a precision partner there even if `require_precision_partner` is
    # off, OR we just block it outright. Default: block.
    blocked_session_tags: list[str] = ["session_london_ny_overlap"]
    # When `bos` is part of the stack, additionally require an FVG or a sweep.
    # BOS-only entries had 39% WR and bled -144 pips this week.
    require_fvg_or_sweep_with_bos: bool = True

    # Second-stage gate (added 2026-05-03 from 3-year audit). After
    # `require_precision_partner` whitelists the *trigger* (fvg / sweep), we
    # additionally require a *structural anchor* — fib retrace, range phase,
    # or NY session label. The 3-year audit showed every profitable combo had
    # at least one of these:
    #     fvg + phase_distribution + zone        (90% WR / +473p)
    #     fib_382 + sweep_swing_high + zone      (54% WR / +343p)
    #     fib_382 + fvg + zone                   (100% WR / +321p)
    #     fvg + sweep_equal_lows + zone          (100% WR / +320p)
    #     fib_382 + session_ny + zone            (50% WR / +400p)
    # Setups without a structural anchor (bare zone + fvg, bare bos + sweep)
    # were the biggest contributors to the -37% bleed in the v6 baseline.
    require_structural_anchor: bool = True
    structural_anchor_tags: list[str] = [
        "fib_382", "fib_500", "fib_618", "fib_786",
        "fib_ote", "fib_50", "fib_high_quality",
        "phase_distribution",
        "session_ny",
    ]

    # Per-timeframe minimum confluence override. H1 chops with 2-confluence
    # setups (33% WR / -$378 in the W18 audit), so we require 3 there. M5/M15
    # remain at the global `min_confluences`. Set to {} to disable.
    min_confluences_per_tf: dict[str, int] = {"H1": 3}

    # New-York-time hours of day in which trading is blocked. Tuned from the
    # 3-year detector audit (data/agent_3yr_v5_M15H1.db, 2023-05 to 2026-05):
    #   * NY 03:00 (London open chop):    44.9% WR / -448 pips / 69 trades
    #   * NY 04:00 (London early):        45.5% WR / -214 pips / 55 trades
    #   * NY 12:00 (London close):        44.5% WR / -402 pips / 146 trades
    #   * NY 13:00 (NY pre-close chop):   32.9% WR / -857 pips / 70 trades
    # All four are statistically significant losing windows. Set to [] to
    # disable time-of-day blocking. Re-tune via `scripts/audit_detectors.py`.
    blocked_hours_ny: list[int] = [3, 4, 12, 13, 16, 17, 18]


class MLConfig(BaseModel):
    enabled: bool = True
    prob_threshold: float = 0.55
    walkforward_train_months: int = 24
    walkforward_test_months: int = 3
    refit_frequency: str = "weekly"

    # Production scorer paths (per-TF).
    scorer_paths: dict[str, str] = {
        "H1": "models/scorer_EURUSD_H1_v8.joblib",
        "M15": "models/scorer_EURUSD_M15_v8.joblib",
    }
    score_thresholds: dict[str, float] = {
        "H1": 0.35,
        "M15": 0.55,  # Raised: M15 is dormant (28.6% WR OOS) — only fires on very high conviction
    }

    # LZI-specific scorer (uses different features than generic scorer)
    lzi_scorer_path: str = "models/scorer_EURUSD_LZI_H1_v1.joblib"
    lzi_score_threshold: float = 0.40

    # Timeframe activation tiers. Controls how aggressively each TF trades.
    #   "active"  — normal operation, standard thresholds apply
    #   "dormant" — still detects signals but requires elevated score + extra confluence
    #              (score_threshold += caution_score_boost, min_confluences += 1)
    #   "bias_only" — never executes, only provides directional context to lower TFs
    #   "disabled" — completely off
    # The human partner can always override dormant → active for a specific trade.
    timeframe_tiers: dict[str, str] = {
        "H1": "active",       # Proven edge: 62.5% WR, +$6.03 OOS
        "M15": "dormant",     # Poor OOS (28.6% WR) but may recover — keep learning
        "H4": "bias_only",    # Used for HTF zone/trend context, not entries
        "D1": "bias_only",    # Daily bias and zone mapping
        "M5": "disabled",     # No model trained, too noisy for current gates
    }

    # Extra score boost required on caution days (Thu/Fri) and dormant TFs.
    # Effectively raises the bar: "you can trade, but only if it's exceptional."
    caution_score_boost: float = 0.15


class RankingConfig(BaseModel):
    """Thresholds for the Strategy Quality Score (SQS) and ranking subsystems.

    All scoring bands are tunable here so backtests can sweep parameters
    without touching scoring logic. Defaults are calibrated to EURUSD
    intraday setups (M5-H4).
    """

    # SQS component weights (max points per component)
    rr_max_pts: float = 30.0
    rr_cap_multiple: float = 3.0
    exec_max_pts: float = 25.0
    zone_max_pts: float = 20.0
    timing_max_pts: float = 15.0
    regime_max_pts: float = 10.0

    # Execution efficiency: hold_time ratio thresholds
    exec_fast_pct: float = 0.25
    exec_normal_pct: float = 0.50
    exec_slow_pct: float = 1.0
    exec_very_slow_pct: float = 2.0

    # Zone respect: MAE / stop thresholds
    zone_excellent_pct: float = 0.20
    zone_good_pct: float = 0.40
    zone_ok_pct: float = 0.60
    zone_poor_pct: float = 0.80

    # Kill-zone session windows (hour ranges, UTC)
    london_open: tuple[int, int] = (7, 10)
    ny_open: tuple[int, int] = (13, 16)
    london_body: tuple[int, int] = (10, 12)
    ny_body: tuple[int, int] = (16, 19)
    asia: tuple[int, int] = (0, 7)

    # Regime-strategy affinity map: strategy_name -> set of preferred regimes
    regime_affinity: dict[str, list[str]] = {
        "LiquidityGrabReversal": ["chop", "low_vol"],
        "FVGRetest": ["trending_up", "trending_down"],
        "BOSContinuation": ["trending_up", "trending_down"],
        "FibRetracement": ["trending_up", "trending_down", "chop"],
        "SDZoneRetest": ["chop", "low_vol"],
    }

    # Timeframe ranking thresholds
    tf_min_trades_excellent: int = 30
    tf_min_trades_good: int = 20
    tf_min_trades_ok: int = 10

    # Session ranking frequency thresholds (same as TF)
    session_min_trades_excellent: int = 30
    session_min_trades_good: int = 20
    session_min_trades_ok: int = 10


class LiquidityConfig(BaseModel):
    """Two-phase liquidity zone (LZI) retest parameters."""
    min_wick_size_pips_h1: float = 10.0
    min_wick_size_pips_h4: float = 15.0
    retest_max_bars: int = 50
    retest_proximity_pips: float = 5.0
    consumption_min_bars: int = 3
    displacement_min_body_pct: float = 0.60
    displacement_min_pips_h1: float = 10.0
    displacement_min_pips_h4: float = 12.0
    zone_expiry_bars: int = 100
    stop_buffer_pips: float = 3.0
    use_pd_array_targeting: bool = True
    fallback_rr: float = 2.0


class LiveTradingConfig(BaseModel):
    """Configuration for the live/paper trading loop (agent/live/)."""
    broker_type: str = "paper"  # "mt5", "exness", "paper"
    check_interval_seconds: int = 60
    risk_per_trade_pct: float = 1.0
    max_daily_dd_pct: float = 3.0
    max_open_positions: int = 1
    lot_size_override: float | None = None
    telegram_enabled: bool = True
    score_threshold: float = 0.55
    move_be_at_r: float = 1.0
    trailing_stop_enabled: bool = False
    trailing_stop_distance_pips: float = 20.0
    paper_initial_balance: float = 10000.0
    max_reconnect_attempts: int = 5
    reconnect_delay_seconds: int = 10


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
    liquidity: LiquidityConfig = LiquidityConfig()
    live: LiveTradingConfig = LiveTradingConfig()
    backtest: BacktestConfig = BacktestConfig()
    demo: DemoConfig = DemoConfig()
    backtest_gate: BacktestGateConfig = BacktestGateConfig()
    ranking: RankingConfig = RankingConfig()

    mode: str = "backtest"
    # IANA timezone name for dashboard display. Bars/journal stay in UTC; this is
    # purely cosmetic. Set to America/New_York to match standard FX charting (NY close).
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
