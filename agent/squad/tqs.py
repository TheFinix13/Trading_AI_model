"""F12 — Trade Quality Score.

Per-trade fitness used by the allocator (devour reweighting), the
adversarial scoreboard (F14), and Population-Based Training (Phi5+).

Formula (foundations F12 in `04-quant-foundations.md`):

    TQS = R^0.7 * efficiency * time_score * cleanliness * beauty_bonus

Components:

* R               — max(0, realised R-multiple). Losing trades score 0.
* efficiency      — 1 - MAE_pips / max(MFE_pips, 1), clipped to [0, 1].
* time_score      — Gaussian centred at the agent's target hold time.
* cleanliness     — 1.0 if no adds + no panic + broker-stop never threatened,
                    else 0.7 (uses `conflab/friction.py` indirectly via the
                    journal flag plumbed through by the kernel).
* beauty_bonus    — 1.2 if entry was inside a chemical-reaction coordinate;
                    else 1.0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TQSComponents:
    """Per-component breakdown, journalled per trade (F12 mitigation).

    The dashboard flags agents whose component distribution skews to a
    single dominant factor (foundations F12 failure-mode mitigation).
    """

    r: float
    efficiency: float
    time_score: float
    cleanliness: float
    beauty_bonus: float

    @property
    def tqs(self) -> float:
        if self.r <= 0:
            return 0.0
        return float(
            (self.r ** 0.7)
            * self.efficiency
            * self.time_score
            * self.cleanliness
            * self.beauty_bonus
        )

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "r": float(self.r),
            "efficiency": float(self.efficiency),
            "time_score": float(self.time_score),
            "cleanliness": float(self.cleanliness),
            "beauty_bonus": float(self.beauty_bonus),
            "tqs": float(self.tqs),
        }


def compute_efficiency(mae_pips: float, mfe_pips: float) -> float:
    """`max(0, 1 - MAE_pips / max(MFE_pips, 1))`, clipped to [0, 1]."""
    if mae_pips < 0:
        raise ValueError(f"MAE must be non-negative pips, got {mae_pips}")
    denom = max(float(mfe_pips), 1.0)
    return float(max(0.0, min(1.0, 1.0 - float(mae_pips) / denom)))


def compute_time_score(actual_hold_hours: float, target_hold_hours: float) -> float:
    """Gaussian centred at the agent's target hold (F12)."""
    if target_hold_hours <= 0:
        return 0.0
    delta = float(actual_hold_hours) - float(target_hold_hours)
    return float(np.exp(-(delta ** 2) / (2.0 * float(target_hold_hours) ** 2)))


def compute_cleanliness(
    *,
    had_adds: bool,
    had_panic_exit: bool,
    broker_stop_threatened: bool,
) -> float:
    """`1.0` if perfectly clean else `0.7`. F12."""
    return 1.0 if not (had_adds or had_panic_exit or broker_stop_threatened) else 0.7


def compute_beauty_bonus(entry_inside_chemical_reaction: bool) -> float:
    """`1.2` if entry was inside a chemical-reaction coordinate, else `1.0`."""
    return 1.2 if entry_inside_chemical_reaction else 1.0


def compute_tqs(
    *,
    r_multiple: float,
    mae_pips: float,
    mfe_pips: float,
    actual_hold_hours: float,
    target_hold_hours: float,
    had_adds: bool = False,
    had_panic_exit: bool = False,
    broker_stop_threatened: bool = False,
    entry_inside_chemical_reaction: bool = False,
) -> TQSComponents:
    """Compute the full F12 TQS for one closed trade."""
    r = max(0.0, float(r_multiple))
    return TQSComponents(
        r=r,
        efficiency=compute_efficiency(mae_pips, mfe_pips),
        time_score=compute_time_score(actual_hold_hours, target_hold_hours),
        cleanliness=compute_cleanliness(
            had_adds=had_adds,
            had_panic_exit=had_panic_exit,
            broker_stop_threatened=broker_stop_threatened,
        ),
        beauty_bonus=compute_beauty_bonus(entry_inside_chemical_reaction),
    )
