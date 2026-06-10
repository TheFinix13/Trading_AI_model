"""Performance metrics computed from a list of completed trades."""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from agent.types import Trade

# Trading-days-per-year; used to annualise the **calendar-day equity-curve**
# Sharpe. The previous implementation applied this factor to a per-trade PnL
# series, which inflated Sharpe on high-frequency timeframes (M15) and deflated
# it on low-frequency ones (H4/D1). All v2 reads use ``_daily_equity_sharpe``.
_TRADING_DAYS_PER_YEAR = 252


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

    sharpe = _daily_equity_sharpe(closed)

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


# ---------------------------------------------------------------------------
# Confidence intervals — so we can tell edge from noise (docs/10 §10.2)
# ---------------------------------------------------------------------------

@dataclass
class MetricCI:
    """A point estimate with a bootstrap confidence interval."""

    value: float
    lo: float
    hi: float

    @property
    def excludes_zero(self) -> bool:
        """True if the whole interval sits on one side of zero (a real signal,
        not noise straddling break-even)."""
        return (self.lo > 0 and self.hi > 0) or (self.lo < 0 and self.hi < 0)

    def __str__(self) -> str:
        return f"{self.value:+.4f} [{self.lo:+.4f}, {self.hi:+.4f}]"


def _daily_equity_sharpe(trades: list[Trade]) -> float:
    """Annualised Sharpe of the calendar-day P&L series.

    Aggregate each trade's PnL by its UTC exit date, then compute
    ``mean / std * sqrt(252)`` on that daily-return series. This gives a
    Sharpe that is comparable across timeframes (a TF-agnostic measurement
    of risk-adjusted return) — unlike the legacy per-trade formula, which
    rewarded high-frequency strategies with an artificial sqrt(N) boost.
    """
    if not trades:
        return 0.0
    by_day: dict = defaultdict(float)
    for t in trades:
        if t.exit_time is None:
            continue
        by_day[t.exit_time.date()] += t.pnl
    series = list(by_day.values())
    if len(series) < 2:
        return 0.0
    mean = sum(series) / len(series)
    variance = sum((x - mean) ** 2 for x in series) / (len(series) - 1)
    std = variance ** 0.5
    if std <= 0:
        return 0.0
    return (mean / std) * (_TRADING_DAYS_PER_YEAR ** 0.5)


def _expectancy(pnls: list[float]) -> float:
    return sum(pnls) / len(pnls) if pnls else 0.0


def _profit_factor(pnls: list[float]) -> float:
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0))
    if gl > 0:
        return gp / gl
    return float("inf") if gp > 0 else 0.0


def _win_rate(pnls: list[float]) -> float:
    return sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0.0


def bootstrap_ci(
    pnls: list[float],
    metric_fn,
    *,
    n_resamples: int = 1000,
    ci_level: float = 0.95,
    seed: int = 12345,
) -> MetricCI:
    """Bootstrap a confidence interval for ``metric_fn`` over per-trade P&Ls.

    Resampling trades with replacement gives an honest sense of how much the
    metric depends on a handful of lucky/unlucky trades — the antidote to the
    "100% win rate over 6 trades" trap.
    """
    point = metric_fn(pnls)
    if len(pnls) < 2:
        return MetricCI(point, point, point)
    rng = random.Random(seed)
    n = len(pnls)
    samples: list[float] = []
    for _ in range(n_resamples):
        resample = [pnls[rng.randrange(n)] for _ in range(n)]
        v = metric_fn(resample)
        if v == float("inf"):
            continue
        samples.append(v)
    if not samples:
        return MetricCI(point, point, point)
    samples.sort()
    alpha = (1.0 - ci_level) / 2.0
    lo = samples[int(alpha * len(samples))]
    hi = samples[min(len(samples) - 1, int((1.0 - alpha) * len(samples)))]
    return MetricCI(point if point != float("inf") else hi, lo, hi)


def bootstrap_p_value(
    pnls: list[float],
    *,
    metric_fn=None,
    n_resamples: int = 1000,
    alternative: str = "greater",
    seed: int = 12345,
) -> float:
    """One-sided bootstrap p-value for the metric (default: expectancy).

    The null is "no edge" (mean = 0). The p-value is the share of bootstrap
    resamples whose ``metric_fn`` value falls on the wrong side of 0
    (``<= 0`` for ``alternative="greater"``, ``>= 0`` for ``"less"``). This is
    the same machinery the bootstrap CI already runs, exposed as a single
    scalar so the ablation grid can feed it into Benjamini-Hochberg.

    Add-one smoothing prevents impossible-looking ``p == 0`` from a finite
    resample count.
    """
    metric_fn = metric_fn or _expectancy
    n = len(pnls)
    if n < 2:
        return 1.0
    rng = random.Random(seed)
    extreme = 0
    total = 0
    for _ in range(n_resamples):
        resample = [pnls[rng.randrange(n)] for _ in range(n)]
        v = metric_fn(resample)
        if v == float("inf") or v == float("-inf"):
            continue
        total += 1
        if alternative == "greater" and v <= 0:
            extreme += 1
        elif alternative == "less" and v >= 0:
            extreme += 1
    if total == 0:
        return 1.0
    return (extreme + 1) / (total + 1)


def benjamini_hochberg(
    p_values: list[float], *, fdr: float = 0.05,
) -> tuple[list[bool], list[float]]:
    """Benjamini-Hochberg multiple-testing correction.

    Given m p-values from m independent tests, returns ``(rejects, q_values)``:
    a boolean mask of which nulls are rejected at the chosen ``fdr`` level, and
    the per-test q-values (smallest FDR at which each test would be called).

    With 224 cells at α=0.05 we'd expect ~11 false positives by chance — BH
    keeps the *expected proportion of false discoveries* among the rejected
    cells at most ``fdr``. Use this rather than raw α to decide which cells
    survive the ablation grid.
    """
    m = len(p_values)
    if m == 0:
        return [], []
    indexed = sorted(enumerate(p_values), key=lambda kv: kv[1])
    q = [0.0] * m
    prev_q = 1.0
    # Walk largest-to-smallest p so the monotone q-value adjustment is one pass.
    for rank in range(m, 0, -1):
        orig_idx, p = indexed[rank - 1]
        raw_q = p * m / rank
        prev_q = min(prev_q, raw_q)
        q[orig_idx] = min(1.0, prev_q)
    rejects = [qv <= fdr for qv in q]
    return rejects, q


MIN_TRADES_FOR_EDGE = 30


@dataclass
class Scorecard:
    """An OOS scorecard with confidence intervals — what we judge changes on."""

    label: str
    n_trades: int
    expectancy: MetricCI
    profit_factor: MetricCI
    win_rate: MetricCI
    base: PerfMetrics

    @property
    def verdict(self) -> str:
        """'EDGE' only when the expectancy CI is positive AND there are enough
        trades to trust it. A 100%-win-rate over 7 trades is NOT an edge — the
        sample-size guard kills that false positive."""
        if self.n_trades < MIN_TRADES_FOR_EDGE:
            return "thin"
        if self.expectancy.excludes_zero and self.expectancy.value > 0:
            return "EDGE"
        return "noise"

    def __str__(self) -> str:
        verdict = self.verdict
        return (
            f"[{self.label}] n={self.n_trades}  "
            f"exp/trade={self.expectancy}  PF={self.profit_factor.value:.2f} "
            f"[{self.profit_factor.lo:.2f},{self.profit_factor.hi:.2f}]  "
            f"WR={self.win_rate.value:.1%}  DD={self.base.max_drawdown_pct:.1%}  "
            f"Sharpe={self.base.sharpe:.2f}  → {verdict}"
        )


def make_scorecard(
    label: str,
    trades: list[Trade],
    initial_balance: float,
    *,
    n_resamples: int = 1000,
    ci_level: float = 0.95,
) -> Scorecard:
    """Build a confidence-interval scorecard from completed trades."""
    closed = [t for t in trades if not t.is_open and t.exit_price is not None]
    pnls = [t.pnl for t in closed]
    base = compute_metrics(trades, initial_balance)
    kw = {"n_resamples": n_resamples, "ci_level": ci_level}
    return Scorecard(
        label=label,
        n_trades=len(closed),
        expectancy=bootstrap_ci(pnls, _expectancy, **kw),
        profit_factor=bootstrap_ci(pnls, _profit_factor, **kw),
        win_rate=bootstrap_ci(pnls, _win_rate, **kw),
        base=base,
    )


# Killzone order for session breakdowns: the high-liquidity windows first.
KILLZONE_ORDER = ["london_ny_overlap", "london", "ny", "asia", "off"]


def scorecard_by_session(
    label: str,
    trades: list[Trade],
    initial_balance: float,
    *,
    n_resamples: int = 1000,
    ci_level: float = 0.95,
    sessions: list[str] | None = None,
) -> dict[str, Scorecard]:
    """Per-session (killzone) scorecards — isolates e.g. the London/NY overlap.

    Each completed trade is bucketed by the session of its **entry** time
    (`agent.detectors.sessions.label_session`), then scored independently with
    CIs. This is how we read the reaction path's overlap numbers on their own
    before the bigger refactor. Returns ``{session_label: Scorecard}`` ordered by
    :data:`KILLZONE_ORDER` (then any extras)."""
    from agent.detectors.sessions import label_session

    buckets: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        if t.is_open or t.exit_time is None:
            continue
        buckets[label_session(t.entry_time)].append(t)

    order = sessions or KILLZONE_ORDER
    ordered = [s for s in order if s in buckets] + [s for s in buckets if s not in order]
    return {
        s: make_scorecard(f"{label}/{s}", buckets[s], initial_balance,
                          n_resamples=n_resamples, ci_level=ci_level)
        for s in ordered
    }
