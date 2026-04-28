"""Pattern-discovery ML.

Unlike the rule-engine scorer (which rates rule-generated setups), the discoverer learns
its own trade signals directly from raw bar features. The pipeline:

  1. At every bar, build a rich feature vector (returns, ATR percentile, RSI, EMA
     distances, candle morphology, time-of-day, microstructure proxies).
  2. Label each bar with: "if we entered LONG with a 1.5R target and 1R stop, did TP
     hit before SL within K bars?"  Same for SHORT. Two binary heads.
  3. Train XGBoost classifier per direction on a walk-forward window.
  4. At inference, predict (long_prob, short_prob); emit a Setup when prob > threshold.

This gives us ML-discovered setups *in addition* to the rule engine's. The two streams
can run side-by-side; downstream code merges them by entry time. Iterating means:
re-train weekly on the latest history; auto-rollback if validation worsens."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from agent.types import Bar, Direction, Setup, Timeframe
from agent.utils import to_pips

log = logging.getLogger(__name__)


# Discoverer features. Kept separate from FEATURE_COLUMNS (rule-engine scorer features)
# because they're computed at every bar, not just at confluence-detected setups.
DISCOVERY_FEATURES: list[str] = [
    "ret_1", "ret_5", "ret_15", "ret_50",
    "vol_5", "vol_20",
    "atr_14", "atr_pct_50", "atr_pct_200",
    "rsi_14",
    "ema_dist_20", "ema_dist_50", "ema_dist_200",
    "ema_slope_50",
    "body_pct", "upper_wick_pct", "lower_wick_pct",
    "range_pct_atr",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "consec_up", "consec_down",
    "high_break_50", "low_break_50",
    "dist_to_recent_high_20", "dist_to_recent_low_20",
]


@dataclass
class DiscoveredSetup:
    """A setup proposed by the discoverer model rather than the rule engine."""
    direction: Direction
    timeframe: Timeframe
    detected_at: datetime
    bar_index: int
    entry: float
    stop: float
    take_profit: float
    long_prob: float
    short_prob: float
    features: dict[str, float] = field(default_factory=dict)


def _safe(x: float, default: float = 0.0) -> float:
    if not np.isfinite(x):
        return default
    return float(x)


def _build_feature_frame(bars: list[Bar], atr_period: int = 14) -> pd.DataFrame:
    """Vectorized feature extraction for the entire bar series.

    All features at index i depend ONLY on bars[:i+1] (no lookahead). pandas rolling
    windows respect this by default (no `center=True`)."""
    if len(bars) < 250:
        return pd.DataFrame(columns=DISCOVERY_FEATURES)

    o = np.array([b.open for b in bars], dtype=float)
    h = np.array([b.high for b in bars], dtype=float)
    l = np.array([b.low for b in bars], dtype=float)
    c = np.array([b.close for b in bars], dtype=float)
    times = pd.DatetimeIndex([b.time for b in bars])

    s_close = pd.Series(c, index=times)
    s_high = pd.Series(h, index=times)
    s_low = pd.Series(l, index=times)
    s_open = pd.Series(o, index=times)

    log_ret = np.log(s_close).diff()

    df = pd.DataFrame(index=times)
    df["ret_1"] = log_ret
    df["ret_5"] = log_ret.rolling(5).sum()
    df["ret_15"] = log_ret.rolling(15).sum()
    df["ret_50"] = log_ret.rolling(50).sum()
    df["vol_5"] = log_ret.rolling(5).std()
    df["vol_20"] = log_ret.rolling(20).std()

    tr = pd.concat([
        s_high - s_low,
        (s_high - s_close.shift(1)).abs(),
        (s_low - s_close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    df["atr_14"] = atr
    df["atr_pct_50"] = atr.rolling(50).rank(pct=True)
    df["atr_pct_200"] = atr.rolling(200).rank(pct=True)

    delta = s_close.diff()
    up = delta.clip(lower=0).rolling(14).mean()
    down = (-delta.clip(upper=0)).rolling(14).mean()
    rs = up / down.replace(0, np.nan)
    df["rsi_14"] = 100 - 100 / (1 + rs)

    ema20 = s_close.ewm(span=20, adjust=False).mean()
    ema50 = s_close.ewm(span=50, adjust=False).mean()
    ema200 = s_close.ewm(span=200, adjust=False).mean()
    df["ema_dist_20"] = (s_close - ema20) / atr
    df["ema_dist_50"] = (s_close - ema50) / atr
    df["ema_dist_200"] = (s_close - ema200) / atr
    df["ema_slope_50"] = ema50.diff(20) / atr

    bar_range = (s_high - s_low).replace(0, np.nan)
    body = (s_close - s_open).abs()
    df["body_pct"] = body / bar_range
    df["upper_wick_pct"] = (s_high - pd.concat([s_open, s_close], axis=1).max(axis=1)) / bar_range
    df["lower_wick_pct"] = (pd.concat([s_open, s_close], axis=1).min(axis=1) - s_low) / bar_range
    df["range_pct_atr"] = bar_range / atr

    hours = times.hour.to_numpy()
    dow = times.dayofweek.to_numpy()
    df["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    df["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    df["dow_cos"] = np.cos(2 * np.pi * dow / 7)

    sign = np.sign(delta.fillna(0))
    consec_up = np.zeros(len(sign), dtype=int)
    consec_down = np.zeros(len(sign), dtype=int)
    for i in range(1, len(sign)):
        if sign.iloc[i] > 0:
            consec_up[i] = consec_up[i - 1] + 1
        elif sign.iloc[i] < 0:
            consec_down[i] = consec_down[i - 1] + 1
    df["consec_up"] = consec_up
    df["consec_down"] = consec_down

    high_50 = s_high.rolling(50).max().shift(1)
    low_50 = s_low.rolling(50).min().shift(1)
    df["high_break_50"] = (s_close > high_50).astype(float)
    df["low_break_50"] = (s_close < low_50).astype(float)

    high_20 = s_high.rolling(20).max()
    low_20 = s_low.rolling(20).min()
    df["dist_to_recent_high_20"] = (s_close - high_20) / atr
    df["dist_to_recent_low_20"] = (s_close - low_20) / atr

    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return df[DISCOVERY_FEATURES]


def _label_forward(
    bars: list[Bar],
    horizon: int = 50,
    stop_atr_mult: float = 1.0,
    tp_atr_mult: float = 1.5,
    atr_period: int = 14,
) -> pd.DataFrame:
    """Generate forward-looking labels.

    For each bar i: simulate "what if we entered LONG with stop = close - 1*ATR and
    target = close + 1.5*ATR. Within `horizon` bars, did TP hit before SL?"
    Same for SHORT. Two binary columns: y_long, y_short.

    Note: this peeks `horizon` bars into the future to *generate the label*. That's
    fine for training (the label is what we WANT to predict), but the model only sees
    bar-i features. At inference time, no future info is used."""
    n = len(bars)
    h = np.array([b.high for b in bars], dtype=float)
    l = np.array([b.low for b in bars], dtype=float)
    c = np.array([b.close for b in bars], dtype=float)

    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    atr = pd.Series(tr).rolling(atr_period).mean().to_numpy()

    y_long = np.zeros(n, dtype=int)
    y_short = np.zeros(n, dtype=int)
    for i in range(atr_period, n - horizon):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        entry = c[i]
        long_sl = entry - stop_atr_mult * a
        long_tp = entry + tp_atr_mult * a
        short_sl = entry + stop_atr_mult * a
        short_tp = entry - tp_atr_mult * a

        for j in range(i + 1, min(i + 1 + horizon, n)):
            hit_long_sl = l[j] <= long_sl
            hit_long_tp = h[j] >= long_tp
            if hit_long_tp and not hit_long_sl:
                y_long[i] = 1
                break
            if hit_long_sl:
                break

        for j in range(i + 1, min(i + 1 + horizon, n)):
            hit_short_sl = h[j] >= short_sl
            hit_short_tp = l[j] <= short_tp
            if hit_short_tp and not hit_short_sl:
                y_short[i] = 1
                break
            if hit_short_sl:
                break

    return pd.DataFrame({"y_long": y_long, "y_short": y_short})


@dataclass
class DiscovererConfig:
    horizon: int = 50            # how far forward we look for label resolution
    stop_atr_mult: float = 1.0   # 1 ATR stop
    tp_atr_mult: float = 1.5     # 1.5 ATR target (matches default rr_min)
    prob_threshold: float = 0.55
    min_train_samples: int = 500
    backend: str = "auto"        # 'xgboost' | 'sklearn' | 'auto'
    # Probability calibration: when True, wraps the trained classifier in
    # CalibratedClassifierCV (isotonic regression on a held-out CV split). This
    # post-hoc adjustment maps the raw model output to actual observed win rates,
    # eliminating the "model says 0.85 but only wins 0.55" hallucination.
    calibrate: bool = True
    calibration_cv: int = 3      # CV folds for isotonic calibration


def _xgboost_available() -> bool:
    """True iff xgboost imports AND its native lib loads (libomp present)."""
    try:
        import xgboost  # noqa: F401
        from xgboost import XGBClassifier
        # actually instantiate — that's what triggers the libomp load on macOS
        XGBClassifier(n_estimators=2, max_depth=2)
        return True
    except Exception:
        return False


class Discoverer:
    """Wraps two gradient-boosted classifiers (long head + short head).

    Backend is XGBoost when available; otherwise falls back to sklearn's
    HistGradientBoostingClassifier (same algorithm family, no libomp dependency).
    Both produce calibrated probability outputs and are SHAP-explainable."""

    def __init__(
        self,
        long_model=None,
        short_model=None,
        cfg: DiscovererConfig | None = None,
        feature_cols: list[str] | None = None,
        backend: str = "sklearn",
    ):
        self.long_model = long_model
        self.short_model = short_model
        self.cfg = cfg or DiscovererConfig()
        self.feature_cols = feature_cols or DISCOVERY_FEATURES
        self.backend = backend

    @classmethod
    def train(cls, bars: list[Bar], cfg: DiscovererConfig | None = None) -> "Discoverer | None":
        cfg = cfg or DiscovererConfig()
        if len(bars) < cfg.min_train_samples + cfg.horizon + 250:
            log.warning("Discoverer.train: too few bars (%d) for horizon %d", len(bars), cfg.horizon)
            return None

        X = _build_feature_frame(bars)
        y = _label_forward(bars, horizon=cfg.horizon,
                           stop_atr_mult=cfg.stop_atr_mult, tp_atr_mult=cfg.tp_atr_mult)

        valid = X.notna().all(axis=1).to_numpy().copy()
        valid[: 250] = False  # warm-up (long EMA 200)
        valid[-cfg.horizon:] = False  # labels not resolved at the tail
        X_v = X.loc[valid].reset_index(drop=True)
        y_v = y.loc[valid].reset_index(drop=True)
        if len(X_v) < cfg.min_train_samples:
            log.warning("Discoverer.train: insufficient valid rows (%d < %d)",
                        len(X_v), cfg.min_train_samples)
            return None

        # Pick backend
        backend = cfg.backend
        if backend == "auto":
            backend = "xgboost" if _xgboost_available() else "sklearn"
        if backend == "xgboost" and not _xgboost_available():
            log.warning("xgboost requested but native lib won't load; falling back to sklearn")
            backend = "sklearn"

        if backend == "xgboost":
            from xgboost import XGBClassifier
            def _new_clf(spw: float):
                return XGBClassifier(
                    n_estimators=300, max_depth=4, learning_rate=0.05,
                    subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
                    scale_pos_weight=spw, eval_metric="logloss", tree_method="hist",
                    random_state=42,
                )
        else:
            from sklearn.ensemble import HistGradientBoostingClassifier
            def _new_clf(spw: float):
                # sklearn uses class_weight on fit() for imbalance, not scale_pos_weight
                return HistGradientBoostingClassifier(
                    max_iter=300, max_depth=4, learning_rate=0.05,
                    l2_regularization=1.0, random_state=42,
                    class_weight={0: 1.0, 1: spw} if spw != 1.0 else None,
                )

        def _fit(target):
            if target.nunique() < 2:
                return None
            pos = float(target.sum())
            neg = float(len(target) - pos)
            spw = (neg / pos) if pos > 0 else 1.0
            m = _new_clf(spw)
            # Probability calibration via isotonic regression on a held-out CV split.
            # Without this, gradient-boosted classifiers tend to be overconfident at
            # the extremes (predicting 0.9 when reality is 0.7). Calibration fixes that.
            if cfg.calibrate and len(X_v) >= 200:
                from sklearn.calibration import CalibratedClassifierCV
                m = CalibratedClassifierCV(m, method="isotonic", cv=cfg.calibration_cv)
            m.fit(X_v, target)
            return m

        long_model = _fit(y_v["y_long"])
        short_model = _fit(y_v["y_short"])
        if long_model is None and short_model is None:
            log.warning("Discoverer.train: no class balance for either direction")
            return None

        log.info("Discoverer trained (%s): rows=%d  long_pos=%.1f%%  short_pos=%.1f%%",
                 backend, len(X_v), 100*y_v["y_long"].mean(), 100*y_v["y_short"].mean())
        return cls(long_model=long_model, short_model=short_model, cfg=cfg,
                   feature_cols=DISCOVERY_FEATURES, backend=backend)

    def predict_bars(self, bars: list[Bar]) -> pd.DataFrame:
        """Predict (long_prob, short_prob) at every bar. Returns DataFrame with
        columns long_prob, short_prob indexed by bar time. NaN for warm-up bars."""
        X = _build_feature_frame(bars)
        out = pd.DataFrame(index=X.index, data={"long_prob": np.nan, "short_prob": np.nan})
        # Predict only on rows where every feature is finite — sklearn rejects all-NaN
        # rows and gives them no probability anyway. This also handles the 250-bar warm-up.
        finite = X.notna().all(axis=1)
        if not finite.any():
            return out
        X_valid = X.loc[finite]
        if self.long_model is not None:
            out.loc[finite, "long_prob"] = self.long_model.predict_proba(X_valid)[:, 1]
        if self.short_model is not None:
            out.loc[finite, "short_prob"] = self.short_model.predict_proba(X_valid)[:, 1]
        return out

    def emit_setups(self, bars: list[Bar], rr: float = 1.5) -> list[DiscoveredSetup]:
        """Walk the bar series and emit a DiscoveredSetup wherever long_prob or
        short_prob exceeds the threshold. Stops/targets sized at 1*ATR / rr*ATR."""
        if not bars:
            return []
        probs = self.predict_bars(bars)
        feats = _build_feature_frame(bars)

        atr = feats["atr_14"].to_numpy()
        thr = self.cfg.prob_threshold
        out: list[DiscoveredSetup] = []
        for i, b in enumerate(bars):
            if i < 250 or not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            long_p = probs["long_prob"].iloc[i] if "long_prob" in probs else 0.0
            short_p = probs["short_prob"].iloc[i] if "short_prob" in probs else 0.0
            long_p = _safe(long_p)
            short_p = _safe(short_p)
            row_feats = {c: _safe(feats[c].iloc[i]) for c in self.feature_cols}

            if long_p >= thr and long_p > short_p:
                stop = b.close - atr[i]
                tp = b.close + rr * atr[i]
                out.append(DiscoveredSetup(
                    direction=Direction.LONG, timeframe=b.timeframe,
                    detected_at=b.time, bar_index=i,
                    entry=b.close, stop=stop, take_profit=tp,
                    long_prob=long_p, short_prob=short_p, features=row_feats,
                ))
            elif short_p >= thr and short_p > long_p:
                stop = b.close + atr[i]
                tp = b.close - rr * atr[i]
                out.append(DiscoveredSetup(
                    direction=Direction.SHORT, timeframe=b.timeframe,
                    detected_at=b.time, bar_index=i,
                    entry=b.close, stop=stop, take_profit=tp,
                    long_prob=long_p, short_prob=short_p, features=row_feats,
                ))
        return out

    def save(self, dir_path: Path | str) -> None:
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        import json as _json
        if self.backend == "xgboost":
            if self.long_model is not None:
                self.long_model.save_model(str(dir_path / "long.json"))
            if self.short_model is not None:
                self.short_model.save_model(str(dir_path / "short.json"))
        else:
            import joblib
            if self.long_model is not None:
                joblib.dump(self.long_model, dir_path / "long.joblib")
            if self.short_model is not None:
                joblib.dump(self.short_model, dir_path / "short.joblib")
        meta = {
            "feature_cols": self.feature_cols,
            "horizon": self.cfg.horizon,
            "stop_atr_mult": self.cfg.stop_atr_mult,
            "tp_atr_mult": self.cfg.tp_atr_mult,
            "prob_threshold": self.cfg.prob_threshold,
            "backend": self.backend,
        }
        (dir_path / "meta.json").write_text(_json.dumps(meta, indent=2))

    @classmethod
    def load(cls, dir_path: Path | str) -> "Discoverer":
        import json as _json
        dir_path = Path(dir_path)
        meta = _json.loads((dir_path / "meta.json").read_text())
        cfg = DiscovererConfig(
            horizon=meta.get("horizon", 50),
            stop_atr_mult=meta.get("stop_atr_mult", 1.0),
            tp_atr_mult=meta.get("tp_atr_mult", 1.5),
            prob_threshold=meta.get("prob_threshold", 0.55),
        )
        backend = meta.get("backend", "xgboost")
        long_model = None
        short_model = None
        if backend == "xgboost":
            from xgboost import XGBClassifier
            if (dir_path / "long.json").exists():
                long_model = XGBClassifier()
                long_model.load_model(str(dir_path / "long.json"))
            if (dir_path / "short.json").exists():
                short_model = XGBClassifier()
                short_model.load_model(str(dir_path / "short.json"))
        else:
            import joblib
            if (dir_path / "long.joblib").exists():
                long_model = joblib.load(dir_path / "long.joblib")
            if (dir_path / "short.joblib").exists():
                short_model = joblib.load(dir_path / "short.joblib")
        return cls(long_model=long_model, short_model=short_model, cfg=cfg,
                   feature_cols=meta.get("feature_cols", DISCOVERY_FEATURES),
                   backend=backend)
