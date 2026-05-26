"""Tests for the ranking subsystem: SQS, Timeframe, and Session rankings.

Covers:
  - SQS computation with known parameters (perfect trade, average trade)
  - SQS = 0 for losses
  - Component-level scoring (timing, zone respect, etc.)
  - Timeframe ranking with synthetic multi-TF data
  - Session ranking with synthetic session data
  - Edge cases: no trades, single trade, all losses
  - Strategy leaderboard ordering
  - Full report generation
"""
from __future__ import annotations

import pytest
from datetime import datetime

from agent.config import RankingConfig
from agent.ranking.sqs import (
    SQSResult,
    compute_sqs,
    rank_strategies,
    _compute_risk_reward_score,
    _compute_zone_respect,
    _compute_timing_score,
    _is_win,
)
from agent.ranking.timeframe_rank import rank_timeframes, TimeframeLeaderboard
from agent.ranking.session_rank import rank_sessions, SessionLeaderboard, _classify_session
from agent.ranking import generate_full_report, RankingReport


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_winning_trade(
    *,
    r_multiple: float = 2.0,
    pnl_pips: float = 60.0,
    entry_time: str = "2025-03-10T08:30:00",
    exit_time: str = "2025-03-10T10:30:00",
    mae_pips: float = 5.0,
    stop_pips: float = 30.0,
    timeframe: str = "H1",
    strategy_name: str = "FVGRetest",
    exit_reason: str = "tp_hit",
    confluences_json: str = '["zone", "fvg", "htf_bias_long"]',
) -> dict:
    return {
        "id": 1,
        "direction": "long",
        "timeframe": timeframe,
        "entry_price": 1.08000,
        "exit_price": 1.08600,
        "stop": 1.07700,
        "tp": 1.08600,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "exit_reason": exit_reason,
        "pnl_pips": pnl_pips,
        "pnl_usd": 60.0,
        "confluences_json": confluences_json,
        "r_multiple": r_multiple,
        "mae_pips": mae_pips,
        "mfe_pips": pnl_pips,
        "lot_size": 0.01,
        "commission": 0.7,
        "strategy_name": strategy_name,
        "stop_pips": stop_pips,
    }


def _make_losing_trade(
    *,
    entry_time: str = "2025-03-10T14:00:00",
    timeframe: str = "M15",
    strategy_name: str = "BOSContinuation",
) -> dict:
    return {
        "id": 2,
        "direction": "short",
        "timeframe": timeframe,
        "entry_price": 1.08500,
        "exit_price": 1.08800,
        "stop": 1.08800,
        "tp": 1.08200,
        "entry_time": entry_time,
        "exit_time": "2025-03-10T15:30:00",
        "exit_reason": "stop_hit",
        "pnl_pips": -30.0,
        "pnl_usd": -30.0,
        "confluences_json": '["zone", "bos"]',
        "r_multiple": -1.0,
        "mae_pips": 30.0,
        "mfe_pips": 5.0,
        "lot_size": 0.01,
        "commission": 0.7,
        "strategy_name": strategy_name,
        "stop_pips": 30.0,
    }


# ---------------------------------------------------------------------------
# SQS Tests
# ---------------------------------------------------------------------------

class TestSQSComputation:
    """Test per-trade SQS scoring."""

    def test_perfect_winning_trade(self):
        """A 2R winner during London open with low MAE should score high."""
        trade = _make_winning_trade(
            r_multiple=2.0,
            entry_time="2025-03-10T08:30:00",  # London open
            exit_time="2025-03-10T09:00:00",   # Very fast TP (30 min)
            mae_pips=3.0,
            stop_pips=30.0,
        )
        # avg_hold = 2h = 7200s; this trade is 1800s = 25% ratio -> full exec pts
        result = compute_sqs(trade, avg_hold_seconds=7200.0)

        assert isinstance(result, SQSResult)
        assert result.risk_reward_score == 20.0  # 2R * 10 = 20
        assert result.execution_efficiency == 25.0  # TP in 25% of avg hold
        assert result.zone_respect == 20.0  # MAE 3/30 = 10% < 20%
        assert result.timing_score == 15.0  # London open
        assert result.regime_bonus == 10.0  # FVGRetest + trending (htf_bias_long)
        assert result.total == 90.0

    def test_3r_capped_at_30(self):
        """R-multiple above 3 should be capped at 30 pts."""
        trade = _make_winning_trade(r_multiple=5.0)
        result = compute_sqs(trade, avg_hold_seconds=7200.0)
        assert result.risk_reward_score == 30.0

    def test_loss_scores_zero(self):
        """A losing trade should score 0 on all quality dimensions."""
        trade = _make_losing_trade()
        result = compute_sqs(trade, avg_hold_seconds=7200.0)

        assert result.risk_reward_score == 0.0
        assert result.execution_efficiency == 0.0
        assert result.zone_respect == 0.0
        assert result.regime_bonus == 0.0
        # Timing still scores (entry quality matters even on losses for attribution)
        assert result.timing_score == 15.0  # NY open (14:00)
        assert result.total == 15.0

    def test_timing_score_asia(self):
        """Asia session (00:00-07:00 UTC) scores 5 pts."""
        trade = _make_winning_trade(entry_time="2025-03-10T03:00:00")
        result = compute_sqs(trade, avg_hold_seconds=7200.0)
        assert result.timing_score == 5.0

    def test_timing_score_off_session(self):
        """Off-session (19:00-00:00 UTC) scores 3 pts."""
        trade = _make_winning_trade(entry_time="2025-03-10T21:00:00")
        result = compute_sqs(trade, avg_hold_seconds=7200.0)
        assert result.timing_score == 3.0

    def test_zone_respect_poor(self):
        """MAE at 75% of stop distance scores 5 pts."""
        trade = _make_winning_trade(mae_pips=22.5, stop_pips=30.0)
        cfg = RankingConfig()
        score = _compute_zone_respect(trade, cfg)
        assert score == 5.0

    def test_zone_respect_barely_survived(self):
        """MAE at 90% of stop scores 2 pts (barely survived)."""
        trade = _make_winning_trade(mae_pips=27.0, stop_pips=30.0)
        cfg = RankingConfig()
        score = _compute_zone_respect(trade, cfg)
        assert score == 2.0


class TestStrategyLeaderboard:
    """Test strategy ranking/leaderboard."""

    def test_rank_strategies_ordering(self):
        """Better strategy (higher SQS) should rank first."""
        good_trades = [
            _make_winning_trade(r_multiple=2.5, strategy_name="FVGRetest",
                                entry_time="2025-03-10T08:30:00",
                                exit_time="2025-03-10T09:30:00",
                                mae_pips=3.0)
            for _ in range(5)
        ]
        bad_trades = [
            _make_winning_trade(r_multiple=1.0, strategy_name="SDZoneRetest",
                                entry_time="2025-03-10T22:00:00",
                                exit_time="2025-03-11T04:00:00",
                                mae_pips=25.0)
            for _ in range(5)
        ]
        leaderboard = rank_strategies(good_trades + bad_trades)

        ranked = leaderboard.ranked
        assert len(ranked) == 2
        assert ranked[0].strategy_name == "FVGRetest"
        assert ranked[1].strategy_name == "SDZoneRetest"
        assert ranked[0].avg_sqs > ranked[1].avg_sqs

    def test_rank_strategies_empty(self):
        """Empty trade list should produce empty leaderboard."""
        lb = rank_strategies([])
        assert lb.strategies == []
        assert lb.all_scores == []

    def test_rank_strategies_single_trade(self):
        """Single trade should produce a valid leaderboard."""
        lb = rank_strategies([_make_winning_trade()])
        assert len(lb.strategies) == 1
        assert lb.strategies[0].n_trades == 1


# ---------------------------------------------------------------------------
# Timeframe Ranking Tests
# ---------------------------------------------------------------------------

class TestTimeframeRanking:
    """Test timeframe ranking with synthetic data."""

    def test_rank_timeframes_basic(self):
        """H1 with good trades should rank above M15 with mediocre trades."""
        h1_trades = [
            _make_winning_trade(timeframe="H1", r_multiple=2.0,
                                entry_time=f"2025-03-{10+i:02d}T08:30:00",
                                exit_time=f"2025-03-{10+i:02d}T10:30:00",
                                mae_pips=5.0)
            for i in range(15)
        ]
        m15_trades = [
            _make_losing_trade(timeframe="M15",
                               entry_time=f"2025-03-{10+i:02d}T14:00:00")
            for i in range(10)
        ] + [
            _make_winning_trade(timeframe="M15", r_multiple=1.0,
                                entry_time=f"2025-03-{20+i:02d}T14:00:00",
                                exit_time=f"2025-03-{20+i:02d}T16:00:00",
                                mae_pips=20.0)
            for i in range(5)
        ]

        lb = rank_timeframes(h1_trades + m15_trades)
        ranked = lb.ranked
        assert len(ranked) == 2
        assert ranked[0].timeframe == "H1"
        assert ranked[0].total_score > ranked[1].total_score

    def test_rank_timeframes_empty(self):
        """Empty trades produce empty leaderboard."""
        lb = rank_timeframes([])
        assert lb.timeframes == []

    def test_rank_timeframes_consistency(self):
        """Trades spread across weeks should get a consistency score."""
        trades = [
            _make_winning_trade(
                timeframe="H4",
                entry_time=f"2025-{m:02d}-15T09:00:00",
                exit_time=f"2025-{m:02d}-15T13:00:00",
            )
            for m in range(1, 7)
        ]
        lb = rank_timeframes(trades)
        assert len(lb.timeframes) == 1
        assert lb.timeframes[0].consistency_score > 0


# ---------------------------------------------------------------------------
# Session Ranking Tests
# ---------------------------------------------------------------------------

class TestSessionRanking:
    """Test session window ranking."""

    def test_rank_sessions_london_vs_asia(self):
        """London open trades should outscore Asia trades (all else equal)."""
        london_trades = [
            _make_winning_trade(entry_time=f"2025-03-{10+i:02d}T08:00:00",
                                exit_time=f"2025-03-{10+i:02d}T09:30:00",
                                r_multiple=2.0, mae_pips=5.0)
            for i in range(10)
        ]
        asia_trades = [
            _make_winning_trade(entry_time=f"2025-03-{10+i:02d}T03:00:00",
                                exit_time=f"2025-03-{10+i:02d}T05:00:00",
                                r_multiple=1.0, mae_pips=15.0)
            for i in range(10)
        ]
        lb = rank_sessions(london_trades + asia_trades)
        ranked = lb.ranked

        london = next(s for s in ranked if s.session_name == "London Open")
        asia = next(s for s in ranked if s.session_name == "Asia")
        assert london.total_score > asia.total_score

    def test_rank_sessions_empty(self):
        """Empty trades produce sessions with 0 scores."""
        lb = rank_sessions([])
        assert lb.sessions == []

    def test_classify_session(self):
        """Hour classification should map correctly."""
        assert _classify_session(3) == "Asia"
        assert _classify_session(8) == "London Open"
        assert _classify_session(11) == "London Body"
        assert _classify_session(12) == "London-NY Overlap"
        assert _classify_session(14) == "NY Open"
        assert _classify_session(17) == "NY Body"
        assert _classify_session(21) == "Off-session"

    def test_rank_sessions_all_losses(self):
        """All losses should produce low scores but not crash."""
        trades = [
            _make_losing_trade(entry_time=f"2025-03-{10+i:02d}T09:00:00")
            for i in range(5)
        ]
        lb = rank_sessions(trades)
        london = next(
            (s for s in lb.sessions if s.session_name == "London Open"), None
        )
        assert london is not None
        assert london.win_rate == 0.0


# ---------------------------------------------------------------------------
# Integration / Full Report Tests
# ---------------------------------------------------------------------------

class TestFullReport:
    """Test the combined report generation."""

    def test_generate_full_report(self):
        """Full report should combine all three leaderboards."""
        trades = [
            _make_winning_trade(timeframe="H1", r_multiple=2.0,
                                entry_time=f"2025-03-{10+i:02d}T08:30:00",
                                exit_time=f"2025-03-{10+i:02d}T10:30:00")
            for i in range(10)
        ] + [
            _make_losing_trade(timeframe="M15",
                               entry_time=f"2025-03-{10+i:02d}T14:00:00")
            for i in range(5)
        ]

        report = generate_full_report(trades)
        assert isinstance(report, RankingReport)
        assert report.total_trades == 15
        assert report.total_wins == 10
        assert report.overall_avg_sqs > 0

        # Verify serialization
        d = report.to_dict()
        assert "summary" in d
        assert "strategy_leaderboard" in d
        assert "timeframe_leaderboard" in d
        assert "session_leaderboard" in d
        assert d["summary"]["total_trades"] == 15

    def test_full_report_empty(self):
        """Empty trades should not crash."""
        report = generate_full_report([])
        assert report.total_trades == 0
        assert report.overall_avg_sqs == 0.0
