"""ML scorer for rule-engine setups (NOT a separate signal generator).

Pipeline:
  1. Run a backtest with NO scorer → collect every setup the rule engine emits
     and its ground-truth outcome (win/loss with R-multiple).
  2. Build a feature matrix from each setup's `features` dict (FEATURE_COLUMNS).
  3. Train a gradient-boosted classifier with isotonic probability calibration.
  4. At inference time, the Backtester calls scorer(features) → probability.
     Setups below threshold are skipped; setups above are taken.

Why this is different from the discoverer:
  - Discoverer learns from RAW bar features at every bar — broad, noisy, hard.
  - Scorer learns from RULE-FILTERED setups — narrow, well-conditioned, easier.

In practice the scorer is the more reliable layer. The discoverer is for finding
patterns we didn't think of; the scorer is for ranking the patterns we already use."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import joblib
import numpy as np
import pandas as pd

from agent.backtest.engine import Backtester
from agent.config import Config
from agent.features.extractor import FEATURE_COLUMNS
from agent.types import Bar, Trade

log = logging.getLogger(__name__)


@dataclass
class ScorerTrainingData:
    """Labeled rows for fitting the scorer. Each row = one rule-engine setup that
    actually entered a trade in a no-scorer backtest, with the trade's R-multiple
    outcome as the label."""
    X: pd.DataFrame
    y: np.ndarray  # 1 = win (R >= 0), 0 = loss

    def __len__(self) -> int:
        return len(self.X)


def _r_multiple(t: Trade) -> float:
    """Risk-multiple of a closed trade. >0 = win, <0 = loss. Uses pip distances."""
    risk = abs(t.entry_price - t.stop_price) * 10000.0
    if risk <= 0:
        return 0.0
    return (t.pnl_pips or 0.0) / risk


def collect_training_data(cfg: Config, bars: list[Bar],
                           feature_cols: list[str] | None = None) -> ScorerTrainingData:
    """Run a no-scorer backtest, label each trade by win/loss, return X/y for training.

    Important: this uses the *exact same rule engine* that will run live. Anything the
    engine wouldn't have produced (because of HTF bias, day filters, etc.) is also not
    in the training set. So the scorer learns to rank only setups the engine emits."""
    feature_cols = feature_cols or FEATURE_COLUMNS

    bt = Backtester(cfg)  # no scorer → take every approved rule setup
    result = bt.run(bars)

    rows: list[dict] = []
    labels: list[int] = []
    for t in result.trades:
        if not t.setup.features:
            continue
        rows.append({c: t.setup.features.get(c, 0.0) for c in feature_cols})
        labels.append(1 if _r_multiple(t) > 0 else 0)

    if not rows:
        return ScorerTrainingData(X=pd.DataFrame(columns=feature_cols),
                                   y=np.array([], dtype=int))
    X = pd.DataFrame(rows, columns=feature_cols).fillna(0.0)
    y = np.asarray(labels, dtype=int)
    log.info("Scorer training data: %d setups, %.1f%% winners", len(y), 100*y.mean())
    return ScorerTrainingData(X=X, y=y)


@dataclass
class SetupScorer:
    """Wrapper exposing a callable that the Backtester can use as `scorer`."""
    model: object
    feature_cols: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    backend: str = "sklearn"

    def predict_proba(self, features: dict[str, float]) -> float:
        """Return probability that this setup is a winner (0..1)."""
        x = np.array([[features.get(c, 0.0) for c in self.feature_cols]], dtype=float)
        proba = self.model.predict_proba(x)
        return float(proba[0, 1])

    def __call__(self, features: dict[str, float]) -> float:
        return self.predict_proba(features)

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self.model,
            "feature_cols": self.feature_cols,
            "backend": self.backend,
        }, path)

    @classmethod
    def load(cls, path: Path | str) -> "SetupScorer":
        d = joblib.load(path)
        return cls(model=d["model"], feature_cols=d["feature_cols"],
                   backend=d.get("backend", "sklearn"))


def _xgboost_available() -> bool:
    try:
        from xgboost import XGBClassifier
        XGBClassifier(n_estimators=2, max_depth=2)
        return True
    except Exception:
        return False


def train_scorer(data: ScorerTrainingData,
                  backend: str = "auto",
                  calibrate: bool = True,
                  random_state: int = 42) -> SetupScorer:
    """Fit a gradient-boosted classifier on (X, y). Calibrated by default.

    Backend choice mirrors the discoverer:
      - 'xgboost' if libomp is installed and `xgboost` imports cleanly
      - 'sklearn' (HistGradientBoostingClassifier) otherwise — pure-pip, no native deps
      - 'auto' picks xgboost when available, else sklearn"""
    if len(data) < 50:
        raise ValueError(f"Not enough training samples ({len(data)}); need >= 50")

    if backend == "auto":
        backend = "xgboost" if _xgboost_available() else "sklearn"

    pos = float(data.y.sum())
    neg = float(len(data) - pos)
    spw = (neg / pos) if pos > 0 else 1.0

    if backend == "xgboost":
        from xgboost import XGBClassifier
        model = XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
            scale_pos_weight=spw, eval_metric="logloss", tree_method="hist",
            random_state=random_state,
        )
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier
        model = HistGradientBoostingClassifier(
            max_iter=300, max_depth=4, learning_rate=0.05,
            l2_regularization=1.0, random_state=random_state,
            class_weight={0: 1.0, 1: spw} if spw != 1.0 else None,
        )

    if calibrate and len(data) >= 100:
        from sklearn.calibration import CalibratedClassifierCV
        model = CalibratedClassifierCV(model, method="isotonic", cv=3)

    model.fit(data.X, data.y)
    log.info("Scorer trained: backend=%s, calibrated=%s, n=%d", backend, calibrate, len(data))
    return SetupScorer(model=model, feature_cols=list(data.X.columns), backend=backend)


def load_lzi_scorer(path: Path | str) -> SetupScorer | None:
    """Load the LZI-specific scorer from a joblib file.

    Returns None if the file doesn't exist (scorer is optional).
    """
    path = Path(path)
    if not path.exists():
        log.warning("LZI scorer not found at %s", path)
        return None
    d = joblib.load(path)
    return SetupScorer(
        model=d["model"],
        feature_cols=d["feature_cols"],
        backend=d.get("backend", "xgboost_calibrated"),
    )
