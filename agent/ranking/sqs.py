"""Strategy Quality Score (SQS) — per-trade quality attribution.

Each closed trade receives a score 0-100 composed of five dimensions:
  1. Risk-Reward Score (0-30): Actual R-multiple achieved
  2. Execution Efficiency (0-25): How quickly TP was hit relative to expected hold time
  3. Zone Respect (0-20): MAE relative to stop distance (low MAE = zone held)
  4. Timing Score (0-15): Entry during a high-probability kill-zone window
  5. Regime Bonus (0-10): Strategy type matched the detected market regime

The SQS is a *quality* metric, not a profitability metric. A 2R winner that entered
at the perfect session, respected the zone, and hit TP quickly scores higher than a
3R grinder that barely survived. This biases the leaderboard toward repeatable edge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agent.config import RankingConfig


@dataclass
class SQSResult:
    """Score breakdown for a single trade."""

    trade_id: int | None
    total: float
    risk_reward_score: float
    execution_efficiency: float
    zone_respect: float
    timing_score: float
    regime_bonus: float
    strategy_name: str = ""
    timeframe: str = ""
    direction: str = ""
    entry_time: str = ""


@dataclass
class StrategyStats:
    """Aggregate stats for one strategy in the leaderboard."""

    strategy_name: str
    n_trades: int
    n_wins: int
    win_rate: float
    avg_sqs: float
    median_sqs: float
    total_pips: float
    avg_r_multiple: float
    best_trade_sqs: float
    worst_trade_sqs: float


@dataclass
class StrategyLeaderboard:
    """Ranked list of strategies ordered by average SQS."""

    strategies: list[StrategyStats] = field(default_factory=list)
    all_scores: list[SQSResult] = field(default_factory=list)

    @property
    def ranked(self) -> list[StrategyStats]:
        return sorted(self.strategies, key=lambda s: s.avg_sqs, reverse=True)


def _parse_entry_time(trade: dict) -> datetime | None:
    """Parse entry_time from a trade dict, handling both ISO strings and datetime objects."""
    et = trade.get("entry_time")
    if et is None:
        return None
    if isinstance(et, datetime):
        return et
    try:
        return datetime.fromisoformat(str(et))
    except (ValueError, TypeError):
        return None


def _parse_exit_time(trade: dict) -> datetime | None:
    et = trade.get("exit_time")
    if et is None:
        return None
    if isinstance(et, datetime):
        return et
    try:
        return datetime.fromisoformat(str(et))
    except (ValueError, TypeError):
        return None


def _get_strategy_name(trade: dict) -> str:
    """Extract strategy name from trade dict. Checks confluences_json for strategy tag."""
    if "strategy_name" in trade and trade["strategy_name"]:
        return trade["strategy_name"]
    confluences = _parse_confluences(trade)
    for c in confluences:
        if c.startswith("strategy_"):
            return c.replace("strategy_", "")
    return "unknown"


def _parse_confluences(trade: dict) -> list[str]:
    raw = trade.get("confluences_json", "[]")
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _is_win(trade: dict) -> bool:
    pnl = trade.get("pnl_pips", 0) or 0
    return float(pnl) > 0


def _compute_risk_reward_score(trade: dict, cfg: RankingConfig) -> float:
    """0-30 pts based on actual R-multiple. Losses score 0."""
    if not _is_win(trade):
        return 0.0
    r_mult = float(trade.get("r_multiple", 0) or 0)
    if r_mult <= 0:
        # Fallback: compute from pnl_pips / stop distance
        pnl_pips = float(trade.get("pnl_pips", 0) or 0)
        stop_dist = _stop_distance_pips(trade)
        r_mult = pnl_pips / stop_dist if stop_dist > 0 else 0
    return min(cfg.rr_max_pts, r_mult * (cfg.rr_max_pts / cfg.rr_cap_multiple))


def _stop_distance_pips(trade: dict) -> float:
    """Compute stop distance in pips from trade fields."""
    if "stop_pips" in trade and trade["stop_pips"]:
        return abs(float(trade["stop_pips"]))
    entry = float(trade.get("entry_price", 0) or 0)
    stop = float(trade.get("stop", 0) or trade.get("stop_price", 0) or 0)
    if entry and stop:
        return abs(entry - stop) * 10000
    return 30.0  # conservative fallback


def _compute_execution_efficiency(
    trade: dict, avg_hold_seconds: float, cfg: RankingConfig
) -> float:
    """0-25 pts. Winners: how fast TP was hit vs average hold time.
    The intuition is that fast TP hits indicate the setup was timed precisely —
    price moved decisively in our direction without dithering."""
    if not _is_win(trade):
        return 0.0

    entry_dt = _parse_entry_time(trade)
    exit_dt = _parse_exit_time(trade)
    if not entry_dt or not exit_dt:
        return 5.0  # can't compute; give baseline

    hold_seconds = (exit_dt - entry_dt).total_seconds()
    if avg_hold_seconds <= 0:
        return 15.0

    ratio = hold_seconds / avg_hold_seconds
    exit_reason = str(trade.get("exit_reason", "")).lower()
    is_tp = "tp" in exit_reason or "take_profit" in exit_reason or "take profit" in exit_reason

    if not is_tp:
        return 5.0

    if ratio <= cfg.exec_fast_pct:
        return cfg.exec_max_pts  # 25
    elif ratio <= cfg.exec_normal_pct:
        return 20.0
    elif ratio <= cfg.exec_slow_pct:
        return 15.0
    elif ratio <= cfg.exec_very_slow_pct:
        return 10.0
    else:
        return 5.0


def _compute_zone_respect(trade: dict, cfg: RankingConfig) -> float:
    """0-20 pts. Low MAE relative to stop = price respected the entry zone.
    This rewards entries where price never meaningfully threatened the stop."""
    if not _is_win(trade):
        return 0.0

    mae = float(trade.get("mae_pips", 0) or 0)
    stop_dist = _stop_distance_pips(trade)
    if stop_dist <= 0:
        return 10.0

    ratio = mae / stop_dist
    if ratio < cfg.zone_excellent_pct:
        return cfg.zone_max_pts  # 20
    elif ratio < cfg.zone_good_pct:
        return 15.0
    elif ratio < cfg.zone_ok_pct:
        return 10.0
    elif ratio < cfg.zone_poor_pct:
        return 5.0
    else:
        return 2.0


def _compute_timing_score(trade: dict, cfg: RankingConfig) -> float:
    """0-15 pts based on entry session window."""
    entry_dt = _parse_entry_time(trade)
    if not entry_dt:
        return 3.0
    hour = entry_dt.hour

    lo, lc = cfg.london_open
    no, nc = cfg.ny_open
    lb_start, lb_end = cfg.london_body
    nb_start, nb_end = cfg.ny_body
    asia_start, asia_end = cfg.asia

    if lo <= hour < lc:
        return cfg.timing_max_pts  # 15
    elif no <= hour < nc:
        return cfg.timing_max_pts  # 15
    elif lb_start <= hour < lb_end:
        return 10.0
    elif nb_start <= hour < nb_end:
        return 10.0
    elif asia_start <= hour < asia_end:
        return 5.0
    else:
        return 3.0


def _compute_regime_bonus(trade: dict, cfg: RankingConfig) -> float:
    """0-10 pts. Strategy matched the detected regime = full marks.
    Regime info comes from confluences (phase_*, htf_bias_*)."""
    if not _is_win(trade):
        return 0.0

    strategy = _get_strategy_name(trade)
    confluences = _parse_confluences(trade)

    preferred_regimes = cfg.regime_affinity.get(strategy, [])
    if not preferred_regimes:
        return 5.0  # unknown strategy, neutral

    # Detect regime from confluence tags
    detected_regime = _detect_regime_from_confluences(confluences)

    if detected_regime in preferred_regimes:
        return cfg.regime_max_pts  # 10
    elif detected_regime == "unknown":
        return 5.0
    else:
        return 3.0  # mismatch but won


def _detect_regime_from_confluences(confluences: list[str]) -> str:
    """Infer market regime from confluence tags."""
    for c in confluences:
        if "phase_distribution" in c:
            return "chop"
        if "phase_accumulation" in c:
            return "chop"
        if "htf_bias_long" in c:
            return "trending_up"
        if "htf_bias_short" in c:
            return "trending_down"
        if "low_vol" in c:
            return "low_vol"
        if "high_vol" in c:
            return "high_vol"
    return "unknown"


def compute_sqs(
    trade: dict,
    avg_hold_seconds: float = 14400.0,
    cfg: RankingConfig | None = None,
) -> SQSResult:
    """Compute the Strategy Quality Score for a single closed trade.

    Args:
        trade: Dict with trade fields (from backtest DB or journal).
        avg_hold_seconds: Average hold time in seconds for this timeframe.
            Used for execution efficiency scoring. Default 4h (H1 typical).
        cfg: Optional RankingConfig; uses defaults if not provided.

    Returns:
        SQSResult with component breakdown and total score.
    """
    if cfg is None:
        cfg = RankingConfig()

    rr = _compute_risk_reward_score(trade, cfg)
    ee = _compute_execution_efficiency(trade, avg_hold_seconds, cfg)
    zr = _compute_zone_respect(trade, cfg)
    ts = _compute_timing_score(trade, cfg)
    rb = _compute_regime_bonus(trade, cfg)

    return SQSResult(
        trade_id=trade.get("id"),
        total=rr + ee + zr + ts + rb,
        risk_reward_score=rr,
        execution_efficiency=ee,
        zone_respect=zr,
        timing_score=ts,
        regime_bonus=rb,
        strategy_name=_get_strategy_name(trade),
        timeframe=str(trade.get("timeframe", "")),
        direction=str(trade.get("direction", "")),
        entry_time=str(trade.get("entry_time", "")),
    )


def _compute_avg_hold_per_tf(trades: list[dict]) -> dict[str, float]:
    """Compute average hold time in seconds, grouped by timeframe."""
    from collections import defaultdict

    hold_times: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        entry_dt = _parse_entry_time(t)
        exit_dt = _parse_exit_time(t)
        if entry_dt and exit_dt:
            tf = str(t.get("timeframe", "unknown"))
            hold_times[tf].append((exit_dt - entry_dt).total_seconds())

    return {
        tf: (sum(times) / len(times)) if times else 14400.0
        for tf, times in hold_times.items()
    }


def rank_strategies(
    trades: list[dict], cfg: RankingConfig | None = None
) -> StrategyLeaderboard:
    """Score all trades and rank strategies by average SQS.

    Groups trades by strategy_name, computes per-trade SQS, then aggregates
    into a leaderboard sorted by avg_sqs descending.
    """
    if cfg is None:
        cfg = RankingConfig()
    if not trades:
        return StrategyLeaderboard()

    avg_holds = _compute_avg_hold_per_tf(trades)

    # Score each trade
    scores: list[SQSResult] = []
    for t in trades:
        tf = str(t.get("timeframe", "unknown"))
        avg_hold = avg_holds.get(tf, 14400.0)
        scores.append(compute_sqs(t, avg_hold_seconds=avg_hold, cfg=cfg))

    # Group by strategy
    from collections import defaultdict

    by_strategy: dict[str, list[tuple[dict, SQSResult]]] = defaultdict(list)
    for trade, score in zip(trades, scores):
        by_strategy[score.strategy_name].append((trade, score))

    # Build stats per strategy
    strategy_stats: list[StrategyStats] = []
    for name, pairs in by_strategy.items():
        trade_scores = [s.total for _, s in pairs]
        trade_scores_sorted = sorted(trade_scores)
        n = len(pairs)
        wins = sum(1 for t, _ in pairs if _is_win(t))
        total_pips = sum(float(t.get("pnl_pips", 0) or 0) for t, _ in pairs)
        r_mults = [
            float(t.get("r_multiple", 0) or 0)
            for t, _ in pairs
            if _is_win(t) and float(t.get("r_multiple", 0) or 0) > 0
        ]

        strategy_stats.append(
            StrategyStats(
                strategy_name=name,
                n_trades=n,
                n_wins=wins,
                win_rate=wins / n if n else 0.0,
                avg_sqs=sum(trade_scores) / n if n else 0.0,
                median_sqs=trade_scores_sorted[n // 2] if n else 0.0,
                total_pips=total_pips,
                avg_r_multiple=(sum(r_mults) / len(r_mults)) if r_mults else 0.0,
                best_trade_sqs=max(trade_scores) if trade_scores else 0.0,
                worst_trade_sqs=min(trade_scores) if trade_scores else 0.0,
            )
        )

    return StrategyLeaderboard(strategies=strategy_stats, all_scores=scores)
