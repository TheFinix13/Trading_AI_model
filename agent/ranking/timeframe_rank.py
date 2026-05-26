"""Timeframe Ranking — score each timeframe across multiple quality dimensions.

Ranks M5, M15, H1, H4, D1 (or any TF present in the trade log) on:
  1. Win Rate (0-25 pts)
  2. Sharpe Ratio proxy (0-25 pts) — based on per-trade R-multiples
  3. Average SQS (0-25 pts)
  4. Trade Frequency / sample size (0-15 pts)
  5. Consistency (0-10 pts) — ratio of profitable weeks

The purpose is to surface which timeframe produces the most reliably high-quality
trades, accounting for both profitability and execution quality. A TF that wins
rarely but at 3R each time may score higher than one that wins often at 1R.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from agent.config import RankingConfig
from agent.ranking.sqs import SQSResult, compute_sqs, _compute_avg_hold_per_tf, _is_win, _parse_entry_time


@dataclass
class TimeframeStats:
    """Score breakdown for a single timeframe."""

    timeframe: str
    total_score: float
    win_rate_score: float
    sharpe_score: float
    avg_sqs_score: float
    frequency_score: float
    consistency_score: float
    # Raw metrics for display
    n_trades: int = 0
    n_wins: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    avg_sqs: float = 0.0
    avg_r_multiple: float = 0.0
    profitable_weeks_ratio: float = 0.0


@dataclass
class TimeframeLeaderboard:
    """Ranked list of timeframes ordered by total score."""

    timeframes: list[TimeframeStats] = field(default_factory=list)

    @property
    def ranked(self) -> list[TimeframeStats]:
        return sorted(self.timeframes, key=lambda t: t.total_score, reverse=True)


def _win_rate_score(win_rate: float) -> float:
    """Convert win rate to 0-25 score."""
    if win_rate >= 0.80:
        return 25.0
    elif win_rate >= 0.70:
        return 20.0
    elif win_rate >= 0.60:
        return 15.0
    elif win_rate >= 0.50:
        return 10.0
    else:
        return 5.0


def _sharpe_score(sharpe: float) -> float:
    """Convert Sharpe ratio to 0-25 score."""
    if sharpe > 2.0:
        return 25.0
    elif sharpe > 1.5:
        return 20.0
    elif sharpe > 1.0:
        return 15.0
    elif sharpe > 0.5:
        return 10.0
    else:
        return 5.0


def _avg_sqs_score(avg_sqs: float) -> float:
    """Linear scale: avg_sqs / 4, capped at 25."""
    return min(25.0, avg_sqs / 4.0)


def _frequency_score(n_trades: int, cfg: RankingConfig) -> float:
    """Score based on statistical significance of sample size."""
    if n_trades >= cfg.tf_min_trades_excellent:
        return 15.0
    elif n_trades >= cfg.tf_min_trades_good:
        return 12.0
    elif n_trades >= cfg.tf_min_trades_ok:
        return 8.0
    else:
        return 4.0


def _consistency_score(trades: list[dict]) -> float:
    """0-10 pts: ratio of profitable weeks to total weeks traded."""
    if not trades:
        return 0.0

    weekly_pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        entry_dt = _parse_entry_time(t)
        if entry_dt:
            week_key = entry_dt.strftime("%Y-W%W")
            weekly_pnl[week_key] += float(t.get("pnl_pips", 0) or 0)

    if not weekly_pnl:
        return 0.0

    profitable_weeks = sum(1 for pnl in weekly_pnl.values() if pnl > 0)
    ratio = profitable_weeks / len(weekly_pnl)
    return ratio * 10.0


def _compute_sharpe(trades: list[dict]) -> float:
    """Compute a Sharpe-like ratio from per-trade R-multiples.

    Uses R-multiples (or pnl_pips / stop_pips as proxy) as the return series.
    Sharpe = mean(returns) / std(returns). Annualization not applied since
    we're comparing across TFs with different trade frequencies.
    """
    returns: list[float] = []
    for t in trades:
        r = float(t.get("r_multiple", 0) or 0)
        if r == 0:
            pnl = float(t.get("pnl_pips", 0) or 0)
            stop = float(t.get("stop_pips", 0) or 0)
            if stop > 0:
                r = pnl / stop
            else:
                entry = float(t.get("entry_price", 0) or 0)
                stop_price = float(t.get("stop", 0) or t.get("stop_price", 0) or 0)
                stop_dist = abs(entry - stop_price) * 10000 if entry and stop_price else 30.0
                r = pnl / stop_dist if stop_dist > 0 else 0
        returns.append(r)

    if len(returns) < 2:
        return 0.0

    mean_r = sum(returns) / len(returns)
    variance = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std_r = math.sqrt(variance) if variance > 0 else 0.001
    return mean_r / std_r


def rank_timeframes(
    trades: list[dict], cfg: RankingConfig | None = None
) -> TimeframeLeaderboard:
    """Score and rank all timeframes present in the trade log.

    Args:
        trades: List of trade dicts from backtest DB.
        cfg: Optional RankingConfig for threshold tuning.

    Returns:
        TimeframeLeaderboard with per-TF score breakdowns, sorted by total.
    """
    if cfg is None:
        cfg = RankingConfig()
    if not trades:
        return TimeframeLeaderboard()

    # Group trades by timeframe
    by_tf: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        tf = str(t.get("timeframe", "unknown"))
        by_tf[tf].append(t)

    # Pre-compute avg hold times for SQS
    avg_holds = _compute_avg_hold_per_tf(trades)

    tf_stats: list[TimeframeStats] = []
    for tf, tf_trades in by_tf.items():
        n = len(tf_trades)
        wins = sum(1 for t in tf_trades if _is_win(t))
        wr = wins / n if n else 0.0

        # Compute SQS for each trade in this TF
        avg_hold = avg_holds.get(tf, 14400.0)
        sqs_scores = [compute_sqs(t, avg_hold_seconds=avg_hold, cfg=cfg).total for t in tf_trades]
        avg_sqs = sum(sqs_scores) / len(sqs_scores) if sqs_scores else 0.0

        sharpe = _compute_sharpe(tf_trades)

        # Compute R-multiple average for wins
        r_mults = [float(t.get("r_multiple", 0) or 0) for t in tf_trades if _is_win(t)]
        avg_r = sum(r_mults) / len(r_mults) if r_mults else 0.0

        wr_pts = _win_rate_score(wr)
        sh_pts = _sharpe_score(sharpe)
        sqs_pts = _avg_sqs_score(avg_sqs)
        freq_pts = _frequency_score(n, cfg)
        cons_pts = _consistency_score(tf_trades)

        tf_stats.append(
            TimeframeStats(
                timeframe=tf,
                total_score=wr_pts + sh_pts + sqs_pts + freq_pts + cons_pts,
                win_rate_score=wr_pts,
                sharpe_score=sh_pts,
                avg_sqs_score=sqs_pts,
                frequency_score=freq_pts,
                consistency_score=cons_pts,
                n_trades=n,
                n_wins=wins,
                win_rate=wr,
                sharpe_ratio=sharpe,
                avg_sqs=avg_sqs,
                avg_r_multiple=avg_r,
                profitable_weeks_ratio=cons_pts / 10.0,
            )
        )

    return TimeframeLeaderboard(timeframes=tf_stats)
