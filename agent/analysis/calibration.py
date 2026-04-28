"""Probability calibration diagnostics — defense against AI hallucinated confidence.

When an XGBoost classifier outputs probability 0.7, we want it to actually win 70% of
the time on out-of-sample data. If the model is overconfident — saying 0.85 but only
winning 0.55 — it's hallucinating, and any betting system on top of it will lose.

Two key metrics:

1. **Brier score**: mean squared error between predicted probability and outcome.
   Perfectly calibrated AND perfectly discriminative model: Brier = 0.
   Random guessing on a 50/50 problem: Brier = 0.25.
   The lower the better. We treat Brier > 0.27 as "model is delivering nothing useful".

2. **Reliability (calibration) curve**: bin predictions into deciles, then for each
   bin compare *predicted mean* vs *actual win rate*. A perfectly calibrated model lies
   on the y=x line. If high-confidence bins underperform their prediction, the model
   is hallucinating confidence at the top.

We also report Expected Calibration Error (ECE): the probability-weighted average gap
between predicted and observed in each bin."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class CalibrationReport:
    brier: float
    ece: float
    n: int
    bin_edges: list[float]
    bin_pred_means: list[float]
    bin_actual_rates: list[float]
    bin_counts: list[int]
    is_overconfident_high_bins: bool
    summary: str

    def __str__(self) -> str:
        lines = [
            "CALIBRATION REPORT",
            f"  N samples       : {self.n}",
            f"  Brier score     : {self.brier:.4f}  (lower is better; 0.25=random; >0.27=concerning)",
            f"  ECE             : {self.ece:.4f}  (expected calibration error; <0.05 is good)",
            f"  Top-bin overconfidence: {'YES' if self.is_overconfident_high_bins else 'no'}",
            "",
            "  Reliability table (predicted vs actual):",
            f"  {'bin':>14s}  {'pred':>8s}  {'actual':>8s}  {'n':>6s}  {'gap':>8s}",
        ]
        for lo, hi, p, a, n in zip(self.bin_edges[:-1], self.bin_edges[1:],
                                    self.bin_pred_means, self.bin_actual_rates,
                                    self.bin_counts):
            if n == 0:
                continue
            gap = a - p
            lines.append(f"  {lo:.2f}-{hi:.2f}  {p:>8.3f}  {a:>8.3f}  {n:>6d}  {gap:>+8.3f}")
        lines.append("")
        lines.append("  " + self.summary)
        return "\n".join(lines)


def calibration_report(probs: np.ndarray, outcomes: np.ndarray,
                       n_bins: int = 10) -> CalibrationReport:
    """Compute Brier, ECE, and a binned reliability curve.

    Args:
        probs: predicted probabilities of the positive class, shape (n,).
        outcomes: 0/1 ground-truth labels, shape (n,).
        n_bins: number of equal-width probability bins (10 = deciles).
    """
    probs = np.asarray(probs, dtype=float).clip(0.0, 1.0)
    outcomes = np.asarray(outcomes, dtype=int)
    if probs.shape != outcomes.shape:
        raise ValueError(f"probs and outcomes must have same shape, got {probs.shape} vs {outcomes.shape}")
    n = len(probs)
    if n == 0:
        return CalibrationReport(
            brier=float("nan"), ece=float("nan"), n=0, bin_edges=[], bin_pred_means=[],
            bin_actual_rates=[], bin_counts=[], is_overconfident_high_bins=False,
            summary="No predictions to evaluate.",
        )

    brier = float(np.mean((probs - outcomes) ** 2))

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    pred_means: list[float] = []
    act_rates: list[float] = []
    counts: list[int] = []
    ece = 0.0
    high_bin_overconfident = False
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (probs >= lo) & (probs < hi)
        # Include the right edge in the last bin so probs == 1.0 are not lost
        if hi == 1.0:
            mask = (probs >= lo) & (probs <= hi)
        cnt = int(mask.sum())
        counts.append(cnt)
        if cnt == 0:
            pred_means.append(0.0)
            act_rates.append(0.0)
            continue
        p_mean = float(probs[mask].mean())
        a_rate = float(outcomes[mask].mean())
        pred_means.append(p_mean)
        act_rates.append(a_rate)
        ece += (cnt / n) * abs(p_mean - a_rate)
        # Flag overconfidence in the upper-half bins (where we'd actually trade)
        if lo >= 0.6 and a_rate < p_mean - 0.1 and cnt >= 10:
            high_bin_overconfident = True

    if brier > 0.27:
        summary = "Model isn't beating random. Don't trust its predictions for live trading."
    elif high_bin_overconfident:
        summary = ("Model HALLUCINATES at high confidence: top bins overpromise. "
                   "Apply isotonic calibration before trusting >=0.65 thresholds.")
    elif ece > 0.10:
        summary = "Calibration is loose. Expect realized win rate to drift from predictions."
    else:
        summary = "Calibration looks reasonable. Predictions can be used as confidence weights."

    return CalibrationReport(
        brier=brier, ece=ece, n=n,
        bin_edges=edges.tolist(),
        bin_pred_means=pred_means, bin_actual_rates=act_rates, bin_counts=counts,
        is_overconfident_high_bins=high_bin_overconfident,
        summary=summary,
    )
