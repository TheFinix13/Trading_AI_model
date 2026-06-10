"""Correlation-aware meta-allocator (docs/10 §10.4).

Given each surviving alpha's trade stream, build daily P&L series, measure how
correlated the alphas are, and combine them so we don't double-count two alphas
that are really the same trade. The ensemble is reported against the best single
alpha so the diversification benefit (or lack of one) is explicit.

Method: mean-variance (tangency) weights ``w ∝ Σ⁻¹ μ`` on the daily-return
covariance, with Ledoit-Wolf-style shrinkage toward a diagonal target for
numerical stability, then clipped to non-negative (no shorting an alpha) and
normalised. This naturally down-weights correlated, low-edge alphas.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from agent.types import Trade

ANNUALISATION = 252.0**0.5


def daily_returns(trades: list[Trade]) -> dict[date, float]:
    """Sum trade P&L (in pips) per calendar day of exit."""
    out: dict[date, float] = defaultdict(float)
    for t in trades:
        if t.is_open or t.exit_time is None:
            continue
        out[t.exit_time.date()] += t.pnl_pips
    return dict(out)


@dataclass
class AllocationResult:
    names: list[str]
    weights: dict[str, float]
    correlation: np.ndarray
    ensemble_sharpe: float
    best_single_sharpe: float
    best_single_name: str
    ensemble_expectancy_daily: float
    included: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


def _sharpe(series: np.ndarray) -> float:
    if series.size < 2 or series.std(ddof=1) == 0:
        return 0.0
    return float(series.mean() / series.std(ddof=1) * ANNUALISATION)


def allocate(
    streams: dict[str, list[Trade]],
    *,
    min_days: int = 20,
    shrinkage: float = 0.2,
) -> AllocationResult:
    """Compute correlation-aware weights across alpha trade streams."""
    # Align all alphas onto a shared daily grid (union of trading days).
    per_alpha = {name: daily_returns(tr) for name, tr in streams.items()}
    eligible = [n for n, d in per_alpha.items() if len(d) >= min_days]
    excluded = [n for n in streams if n not in eligible]
    if not eligible:
        return AllocationResult([], {}, np.zeros((0, 0)), 0.0, 0.0, "", 0.0,
                                included=[], excluded=excluded)

    all_days = sorted({d for n in eligible for d in per_alpha[n]})
    mat = np.array([[per_alpha[n].get(day, 0.0) for day in all_days] for n in eligible])
    # rows = alphas, cols = days
    mu = mat.mean(axis=1)
    cov = np.cov(mat, ddof=1) if len(eligible) > 1 else np.array([[mat.var(ddof=1)]])
    cov = np.atleast_2d(cov)

    # Correlation matrix for reporting.
    std = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)

    # Shrink covariance toward its diagonal for a stable inverse.
    target = np.diag(np.diag(cov))
    cov_s = (1 - shrinkage) * cov + shrinkage * target
    cov_s += np.eye(len(eligible)) * 1e-9

    try:
        raw = np.linalg.solve(cov_s, mu)
    except np.linalg.LinAlgError:
        raw = mu.copy()
    raw = np.clip(raw, 0.0, None)  # long-only on each alpha
    if raw.sum() <= 0:
        # No positive-edge combination — fall back to equal weight on positives.
        raw = (mu > 0).astype(float)
    weights = raw / raw.sum() if raw.sum() > 0 else np.ones(len(eligible)) / len(eligible)

    ensemble = weights @ mat
    ens_sharpe = _sharpe(ensemble)
    singles = {n: _sharpe(mat[k]) for k, n in enumerate(eligible)}
    best_name = max(singles, key=singles.get)

    return AllocationResult(
        names=eligible,
        weights={n: float(w) for n, w in zip(eligible, weights)},
        correlation=corr,
        ensemble_sharpe=ens_sharpe,
        best_single_sharpe=singles[best_name],
        best_single_name=best_name,
        ensemble_expectancy_daily=float(ensemble.mean()),
        included=eligible,
        excluded=excluded,
    )
