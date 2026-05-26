"""Session/Time Ranking — score each trading session window.

Ranks the following session windows (UTC):
  - London Open (07:00-10:00)
  - NY Open (13:00-16:00)
  - London Body (10:00-12:00)
  - NY Body (16:00-19:00)
  - London-NY Overlap (12:00-13:00)
  - Asia (00:00-07:00)
  - Off-session (19:00-00:00)

Each session is scored across:
  1. Win Rate (0-30 pts)
  2. Avg R-Multiple of wins (0-25 pts)
  3. Average SQS (0-25 pts)
  4. Frequency / sample size (0-20 pts)

The output helps the trader concentrate execution in sessions that historically
produce the highest quality setups and avoid low-edge windows.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from agent.config import RankingConfig
from agent.ranking.sqs import (
    SQSResult,
    compute_sqs,
    _compute_avg_hold_per_tf,
    _is_win,
    _parse_entry_time,
)


SESSION_WINDOWS: list[tuple[str, int, int]] = [
    ("Asia", 0, 7),
    ("London Open", 7, 10),
    ("London Body", 10, 12),
    ("London-NY Overlap", 12, 13),
    ("NY Open", 13, 16),
    ("NY Body", 16, 19),
    ("Off-session", 19, 24),
]


@dataclass
class SessionStats:
    """Score breakdown for a single session window."""

    session_name: str
    total_score: float
    win_rate_score: float
    avg_r_score: float
    avg_sqs_score: float
    frequency_score: float
    # Raw metrics
    n_trades: int = 0
    n_wins: int = 0
    win_rate: float = 0.0
    avg_r_multiple: float = 0.0
    avg_sqs: float = 0.0
    hour_range: str = ""


@dataclass
class SessionLeaderboard:
    """Ranked list of session windows ordered by total score."""

    sessions: list[SessionStats] = field(default_factory=list)

    @property
    def ranked(self) -> list[SessionStats]:
        return sorted(self.sessions, key=lambda s: s.total_score, reverse=True)


def _classify_session(hour: int) -> str:
    """Map an hour (0-23 UTC) to a session name."""
    for name, start, end in SESSION_WINDOWS:
        if start <= hour < end:
            return name
    return "Off-session"


def _session_win_rate_score(win_rate: float) -> float:
    """Convert win rate to 0-30 score (wider range than TF ranking)."""
    if win_rate >= 0.80:
        return 30.0
    elif win_rate >= 0.70:
        return 25.0
    elif win_rate >= 0.60:
        return 20.0
    elif win_rate >= 0.50:
        return 15.0
    elif win_rate >= 0.40:
        return 10.0
    else:
        return 5.0


def _avg_r_score(avg_r: float) -> float:
    """0-25 pts based on average R-multiple of winning trades."""
    if avg_r > 2.0:
        return 25.0
    elif avg_r > 1.5:
        return 20.0
    elif avg_r > 1.0:
        return 15.0
    else:
        return 10.0


def _avg_sqs_score(avg_sqs: float) -> float:
    """Linear scale: avg_sqs / 4, capped at 25."""
    return min(25.0, avg_sqs / 4.0)


def _session_frequency_score(n_trades: int, cfg: RankingConfig) -> float:
    """0-20 pts based on sample size for statistical significance."""
    if n_trades >= cfg.session_min_trades_excellent:
        return 20.0
    elif n_trades >= cfg.session_min_trades_good:
        return 16.0
    elif n_trades >= cfg.session_min_trades_ok:
        return 10.0
    else:
        return 5.0


def rank_sessions(
    trades: list[dict], cfg: RankingConfig | None = None
) -> SessionLeaderboard:
    """Score and rank all session windows based on trade performance.

    Args:
        trades: List of trade dicts from backtest DB.
        cfg: Optional RankingConfig for threshold tuning.

    Returns:
        SessionLeaderboard with per-session score breakdowns.
    """
    if cfg is None:
        cfg = RankingConfig()
    if not trades:
        return SessionLeaderboard()

    # Group trades by session
    by_session: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        entry_dt = _parse_entry_time(t)
        if entry_dt:
            session_name = _classify_session(entry_dt.hour)
            by_session[session_name].append(t)

    # Pre-compute avg hold times for SQS
    avg_holds = _compute_avg_hold_per_tf(trades)

    session_stats: list[SessionStats] = []
    for name, start, end in SESSION_WINDOWS:
        sess_trades = by_session.get(name, [])
        n = len(sess_trades)
        if n == 0:
            session_stats.append(
                SessionStats(
                    session_name=name,
                    total_score=0.0,
                    win_rate_score=0.0,
                    avg_r_score=0.0,
                    avg_sqs_score=0.0,
                    frequency_score=0.0,
                    hour_range=f"{start:02d}:00-{end:02d}:00 UTC",
                )
            )
            continue

        wins = sum(1 for t in sess_trades if _is_win(t))
        wr = wins / n if n else 0.0

        # Avg R of winners
        winning_r: list[float] = []
        for t in sess_trades:
            if _is_win(t):
                r = float(t.get("r_multiple", 0) or 0)
                if r <= 0:
                    pnl = float(t.get("pnl_pips", 0) or 0)
                    entry = float(t.get("entry_price", 0) or 0)
                    stop = float(t.get("stop", 0) or t.get("stop_price", 0) or 0)
                    stop_dist = abs(entry - stop) * 10000 if entry and stop else 30.0
                    r = pnl / stop_dist if stop_dist > 0 else 0
                if r > 0:
                    winning_r.append(r)
        avg_r = sum(winning_r) / len(winning_r) if winning_r else 0.0

        # Compute SQS for each trade
        sqs_scores: list[float] = []
        for t in sess_trades:
            tf = str(t.get("timeframe", "unknown"))
            avg_hold = avg_holds.get(tf, 14400.0)
            sqs_scores.append(compute_sqs(t, avg_hold_seconds=avg_hold, cfg=cfg).total)
        avg_sqs = sum(sqs_scores) / len(sqs_scores) if sqs_scores else 0.0

        wr_pts = _session_win_rate_score(wr)
        r_pts = _avg_r_score(avg_r)
        sqs_pts = _avg_sqs_score(avg_sqs)
        freq_pts = _session_frequency_score(n, cfg)

        session_stats.append(
            SessionStats(
                session_name=name,
                total_score=wr_pts + r_pts + sqs_pts + freq_pts,
                win_rate_score=wr_pts,
                avg_r_score=r_pts,
                avg_sqs_score=sqs_pts,
                frequency_score=freq_pts,
                n_trades=n,
                n_wins=wins,
                win_rate=wr,
                avg_r_multiple=avg_r,
                avg_sqs=avg_sqs,
                hour_range=f"{start:02d}:00-{end:02d}:00 UTC",
            )
        )

    return SessionLeaderboard(sessions=session_stats)
