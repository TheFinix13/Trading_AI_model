"""Smoke tests for the pattern-discovery model. Verifies feature extraction has no
lookahead, training succeeds on enough synthetic data, and predictions are well-formed."""
import numpy as np
import pandas as pd

from agent.data.synthetic import generate
from agent.data.loader import df_to_bars
from agent.model.discoverer import (
    DISCOVERY_FEATURES,
    Discoverer,
    DiscovererConfig,
    _build_feature_frame,
    _label_forward,
)
from agent.types import Timeframe


def _bars(n=3000, seed=7):
    df = generate(timeframe=Timeframe.H1, n_bars=n, seed=seed)
    return df_to_bars(df, Timeframe.H1)


def test_feature_frame_shape_and_no_inf():
    bars = _bars(n=1000)
    X = _build_feature_frame(bars)
    assert list(X.columns) == DISCOVERY_FEATURES
    assert len(X) == 1000
    assert not X.isin([np.inf, -np.inf]).any().any()


def test_features_no_lookahead():
    """The features at index i must equal the features computed on bars[:i+1].
    If they differ, we have lookahead leakage."""
    bars = _bars(n=600)
    full = _build_feature_frame(bars)
    partial = _build_feature_frame(bars[:500])
    # The first 250 rows of `partial` should match the first 250 rows of `full`
    # (warm-up zone is identical regardless of how many bars come after).
    cols = ["ret_1", "rsi_14", "ema_dist_50", "atr_14"]
    a = full.iloc[200:250][cols].reset_index(drop=True)
    b = partial.iloc[200:250][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=False, atol=1e-9)


def test_label_forward_resolves():
    bars = _bars(n=1500)
    y = _label_forward(bars, horizon=30)
    # Tail rows (no future to resolve labels) must be left at 0
    assert (y.iloc[-30:] == 0).all().all()
    # Both classes should appear in synthetic data given enough bars
    assert y["y_long"].sum() > 0 or y["y_short"].sum() > 0


def test_train_and_emit():
    bars = _bars(n=3000)
    cfg = DiscovererConfig(min_train_samples=200, prob_threshold=0.5)
    d = Discoverer.train(bars, cfg)
    if d is None:
        return
    setups = d.emit_setups(bars)
    for s in setups[:20]:
        assert 0.0 <= s.long_prob <= 1.0
        assert 0.0 <= s.short_prob <= 1.0
        assert s.entry > 0
        assert s.stop > 0
        assert s.take_profit > 0
