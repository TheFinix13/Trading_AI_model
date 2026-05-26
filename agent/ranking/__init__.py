"""Ranking subsystem — Strategy Quality Score, Timeframe, and Session rankings.

Exports:
    - compute_sqs: Per-trade SQS computation
    - rank_strategies: Strategy leaderboard
    - rank_timeframes: Timeframe leaderboard
    - rank_sessions: Session leaderboard
    - generate_full_report: Combined report across all three dimensions
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.config import RankingConfig
from agent.ranking.sqs import (
    SQSResult,
    StrategyLeaderboard,
    StrategyStats,
    compute_sqs,
    rank_strategies,
)
from agent.ranking.timeframe_rank import (
    TimeframeLeaderboard,
    TimeframeStats,
    rank_timeframes,
)
from agent.ranking.session_rank import (
    SessionLeaderboard,
    SessionStats,
    rank_sessions,
)


@dataclass
class RankingReport:
    """Combined ranking report across all three dimensions.

    This is the top-level output for the ranking system — a single object
    that tells the trader which strategies, timeframes, and sessions are
    performing best and worst.
    """

    strategy_leaderboard: StrategyLeaderboard
    timeframe_leaderboard: TimeframeLeaderboard
    session_leaderboard: SessionLeaderboard
    total_trades: int = 0
    total_wins: int = 0
    overall_avg_sqs: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full report to a JSON-compatible dict."""
        return {
            "summary": {
                "total_trades": self.total_trades,
                "total_wins": self.total_wins,
                "overall_avg_sqs": round(self.overall_avg_sqs, 2),
            },
            "strategy_leaderboard": [
                {
                    "rank": i + 1,
                    "strategy": s.strategy_name,
                    "n_trades": s.n_trades,
                    "win_rate": round(s.win_rate, 4),
                    "avg_sqs": round(s.avg_sqs, 2),
                    "median_sqs": round(s.median_sqs, 2),
                    "total_pips": round(s.total_pips, 1),
                    "avg_r": round(s.avg_r_multiple, 2),
                }
                for i, s in enumerate(self.strategy_leaderboard.ranked)
            ],
            "timeframe_leaderboard": [
                {
                    "rank": i + 1,
                    "timeframe": t.timeframe,
                    "total_score": round(t.total_score, 2),
                    "n_trades": t.n_trades,
                    "win_rate": round(t.win_rate, 4),
                    "sharpe": round(t.sharpe_ratio, 3),
                    "avg_sqs": round(t.avg_sqs, 2),
                    "consistency": round(t.profitable_weeks_ratio, 2),
                }
                for i, t in enumerate(self.timeframe_leaderboard.ranked)
            ],
            "session_leaderboard": [
                {
                    "rank": i + 1,
                    "session": s.session_name,
                    "hour_range": s.hour_range,
                    "total_score": round(s.total_score, 2),
                    "n_trades": s.n_trades,
                    "win_rate": round(s.win_rate, 4),
                    "avg_r": round(s.avg_r_multiple, 2),
                    "avg_sqs": round(s.avg_sqs, 2),
                }
                for i, s in enumerate(self.session_leaderboard.ranked)
            ],
        }


def generate_full_report(
    trades: list[dict], cfg: RankingConfig | None = None
) -> RankingReport:
    """Run all three ranking systems and produce a combined report.

    Args:
        trades: List of closed trade dicts (from backtest DB or journal).
        cfg: Optional RankingConfig for threshold tuning.

    Returns:
        RankingReport with strategy, timeframe, and session leaderboards.
    """
    if cfg is None:
        cfg = RankingConfig()

    strategy_lb = rank_strategies(trades, cfg=cfg)
    timeframe_lb = rank_timeframes(trades, cfg=cfg)
    session_lb = rank_sessions(trades, cfg=cfg)

    total_trades = len(trades)
    total_wins = sum(1 for t in trades if float(t.get("pnl_pips", 0) or 0) > 0)
    all_sqs = [s.total for s in strategy_lb.all_scores] if strategy_lb.all_scores else []
    overall_avg = sum(all_sqs) / len(all_sqs) if all_sqs else 0.0

    return RankingReport(
        strategy_leaderboard=strategy_lb,
        timeframe_leaderboard=timeframe_lb,
        session_leaderboard=session_lb,
        total_trades=total_trades,
        total_wins=total_wins,
        overall_avg_sqs=overall_avg,
    )


__all__ = [
    "compute_sqs",
    "rank_strategies",
    "rank_timeframes",
    "rank_sessions",
    "generate_full_report",
    "RankingReport",
    "SQSResult",
    "StrategyLeaderboard",
    "StrategyStats",
    "TimeframeLeaderboard",
    "TimeframeStats",
    "SessionLeaderboard",
    "SessionStats",
    "RankingConfig",
]
