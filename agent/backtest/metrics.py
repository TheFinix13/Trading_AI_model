"""Performance metrics computed from a list of completed trades."""
from __future__ import annotations

from dataclasses import dataclass

from agent.types import Trade


@dataclass
class PerfMetrics:
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    expectancy: float
    expectancy_pips: float
    avg_win: float
    avg_loss: float
    max_drawdown: float
    max_drawdown_pct: float
    final_balance: float
    total_return_pct: float
    sharpe: float
    largest_trade_share: float

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def compute_metrics(trades: list[Trade], initial_balance: float) -> PerfMetrics:
    closed = [t for t in trades if not t.is_open and t.exit_price is not None]
    n = len(closed)
    if n == 0:
        return PerfMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, initial_balance, 0, 0, 0)

    pnls = [t.pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gp = sum(wins)
    gl = abs(sum(losses))
    pf = (gp / gl) if gl > 0 else float("inf") if gp > 0 else 0.0

    expectancy = sum(pnls) / n
    expectancy_pips = sum(t.pnl_pips for t in closed) / n
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0

    balance = initial_balance
    peak = balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for p in pnls:
        balance += p
        peak = max(peak, balance)
        dd = peak - balance
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak if peak > 0 else 0.0

    final = initial_balance + sum(pnls)
    ret_pct = (final - initial_balance) / initial_balance if initial_balance > 0 else 0.0

    if len(pnls) >= 2:
        mean = sum(pnls) / len(pnls)
        variance = sum((x - mean) ** 2 for x in pnls) / (len(pnls) - 1)
        std = variance**0.5
        sharpe = (mean / std) * (252**0.5) if std > 0 else 0.0
    else:
        sharpe = 0.0

    total_profit = sum(p for p in pnls if p > 0)
    largest_trade_share = (max(pnls) / total_profit) if total_profit > 0 else 0.0

    return PerfMetrics(
        n_trades=n,
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=len(wins) / n,
        gross_profit=gp,
        gross_loss=gl,
        profit_factor=pf,
        expectancy=expectancy,
        expectancy_pips=expectancy_pips,
        avg_win=avg_win,
        avg_loss=avg_loss,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        final_balance=final,
        total_return_pct=ret_pct,
        sharpe=sharpe,
        largest_trade_share=largest_trade_share,
    )
