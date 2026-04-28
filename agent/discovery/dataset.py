"""Build the training dataset:

  1. Run the candidate enumerator at every bar
  2. Extract feature vector at each candidate
  3. Label each candidate with its outcome (walk forward)
  4. Return aligned (X, y, meta) for ML training
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from agent.config import Config
from agent.discovery.labeler import Outcome, label_all
from agent.features.extractor import FEATURE_COLUMNS, extract_features
from agent.rules.engine import RuleEngine, precompute
from agent.types import Bar

log = logging.getLogger(__name__)


@dataclass
class TrainingDataset:
    X: pd.DataFrame
    y: pd.Series                 # binary win/loss labels
    rr_realized: pd.Series       # continuous R-multiples (for RR-aware model variants)
    times: pd.DatetimeIndex      # candidate detection times
    outcomes: list[Outcome]


def build_dataset(
    cfg: Config, bars: list[Bar], horizon_bars: int = 200, log_every: int = 5000
) -> TrainingDataset:
    """Single pass over all bars. Generates candidates with the rule engine, labels each
    by walking price forward up to `horizon_bars`, and packages everything into a DataFrame."""
    if len(bars) < 100:
        log.warning("Not enough bars (%d) to build a dataset", len(bars))
        return _empty_dataset()

    log.info("Precomputing detector context for %d bars...", len(bars))
    ctx = precompute(bars, cfg)
    log.info("  zones=%d fvgs=%d bos=%d trendlines=%d wicks=%d",
             len(ctx.zones), len(ctx.fvgs), len(ctx.bos_list),
             len(ctx.trendlines), len(ctx.wicks))

    engine = RuleEngine(cfg)
    candidates = []
    for i in range(50, len(bars) - 1):
        cs = engine.enumerate_candidates(ctx, i)
        candidates.extend(cs)
        if log_every and (i % log_every == 0):
            log.info("  scanned %d/%d bars, %d candidates so far", i, len(bars), len(candidates))

    log.info("Total raw candidates: %d", len(candidates))
    if not candidates:
        return _empty_dataset()

    log.info("Labeling candidates with %d-bar horizon...", horizon_bars)
    outcomes = label_all(candidates, bars, horizon_bars=horizon_bars)
    log.info("  labeled %d outcomes (%d wins, %d losses, %d unresolved)",
             len(outcomes),
             sum(1 for o in outcomes if o.hit_tp),
             sum(1 for o in outcomes if o.hit_sl),
             sum(1 for o in outcomes if not o.resolved))

    feat_rows = []
    labels = []
    rrs = []
    times = []
    for o in outcomes:
        feats = extract_features(o.candidate, bars, o.candidate.detected_bar_index)
        if not feats:
            continue
        row = [feats.get(c, 0.0) for c in FEATURE_COLUMNS]
        feat_rows.append(row)
        labels.append(o.label)
        rrs.append(o.rr_realized)
        times.append(o.candidate.detected_at)

    X = pd.DataFrame(feat_rows, columns=FEATURE_COLUMNS)
    y = pd.Series(labels, name="label", dtype=int)
    rr = pd.Series(rrs, name="rr_realized", dtype=float)
    t = pd.DatetimeIndex(times, name="time")
    return TrainingDataset(X=X, y=y, rr_realized=rr, times=t, outcomes=outcomes)


def _empty_dataset() -> TrainingDataset:
    return TrainingDataset(
        X=pd.DataFrame(columns=FEATURE_COLUMNS),
        y=pd.Series(dtype=int, name="label"),
        rr_realized=pd.Series(dtype=float, name="rr_realized"),
        times=pd.DatetimeIndex([], name="time"),
        outcomes=[],
    )
