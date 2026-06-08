"""Tests for the reaction engine: measured commitment components + ReactionEngine."""
from datetime import datetime, timedelta, timezone

from agent.config import ReactionConfig
from agent.reaction.components import (
    compute_components,
    displacement_score,
    imbalance_score,
    momentum_score,
    range_expansion_score,
)
from agent.reaction.engine import LevelOfInterest, ReactionEngine
from agent.types import Bar, Direction, Timeframe

PIP = 0.0001
T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bar(o, h, l, c, i=0, v=1000.0):
    return Bar(
        time=T0 + timedelta(hours=i), open=o, high=h, low=l, close=c,
        volume=v, timeframe=Timeframe.H1,
    )


def flat_series(n, price=1.1000, rng=0.0010):
    """n quiet bars oscillating in a tight range around `price`."""
    bars = []
    for i in range(n):
        o = price
        c = price + (0.0001 if i % 2 else -0.0001)
        h = max(o, c) + rng / 4
        l = min(o, c) - rng / 4
        bars.append(bar(o, h, l, c, i=i))
    return bars


def test_displacement_strong_bullish():
    cfg = ReactionConfig()
    # Big bullish body closing on the high. ATR small -> big body/ATR ratio.
    b = bar(1.1000, 1.1052, 1.0999, 1.1050, i=1)
    score, direction = displacement_score([b], atr=0.0020, cfg=cfg)
    assert direction == Direction.LONG
    assert score > 0.6


def test_displacement_weak_close_halved():
    cfg = ReactionConfig()
    # Same body size but closes mid-range (weak close) -> score halved.
    strong = bar(1.1000, 1.1050, 1.1000, 1.1050, i=1)
    weak = bar(1.1000, 1.1100, 1.1000, 1.1050, i=1)
    s_strong, _ = displacement_score([strong], atr=0.0020, cfg=cfg)
    s_weak, _ = displacement_score([weak], atr=0.0020, cfg=cfg)
    assert s_weak < s_strong


def test_range_expansion_detects_ignition():
    cfg = ReactionConfig()
    bars = flat_series(25, rng=0.0010)
    # Append an explosive bar with a much larger range.
    bars.append(bar(1.1000, 1.1080, 1.0995, 1.1075, i=25))
    score = range_expansion_score(bars, cfg)
    assert score > 0.5


def test_momentum_consecutive_up_closes():
    cfg = ReactionConfig()
    bars = flat_series(10, rng=0.0006)
    px = 1.1000
    for k in range(5):
        px += 0.0020
        bars.append(bar(px - 0.0020, px + 0.0002, px - 0.0021, px, i=10 + k))
    score, direction = momentum_score(bars, atr=0.0020, cfg=cfg)
    assert direction == Direction.LONG
    assert score > 0.4


def test_imbalance_buy_pressure():
    cfg = ReactionConfig()
    # Close near the high, long lower wick, tiny upper wick = buy pressure.
    b = bar(1.1010, 1.1052, 1.0990, 1.1050, i=1)
    score, direction = imbalance_score([b], cfg)
    assert direction == Direction.LONG
    assert score > 0.5


def test_compute_components_votes_direction():
    cfg = ReactionConfig()
    bars = flat_series(20, rng=0.0006)
    bars.append(bar(1.1000, 1.1062, 1.0999, 1.1060, i=20))
    comp = compute_components(bars, atr=0.0020, cfg=cfg)
    assert comp.direction == Direction.LONG
    assert 0.0 <= comp.displacement <= 1.0


def _ignition_series():
    """Quiet base then a strong bullish commitment bar closing at 1.1080."""
    bars = flat_series(25, rng=0.0008)
    bars.append(bar(1.1000, 1.1082, 1.0999, 1.1080, i=25))
    return bars


def test_engine_fires_on_commitment_at_level():
    cfg = ReactionConfig(require_level=True)
    engine = ReactionEngine(cfg)
    bars = _ignition_series()
    # A marked level right at the close so the level gate passes.
    level = LevelOfInterest(price=1.1080, label="PDH", kind="daily")
    assess = engine.assess(bars, atr=0.0020, levels=[level])
    assert assess.fired
    assert assess.signal is not None
    assert assess.signal.direction == Direction.LONG
    assert assess.signal.stop < assess.signal.entry < assess.signal.take_profit
    assert assess.signal.rr >= cfg.min_rr


def test_engine_holds_off_without_level_when_required():
    cfg = ReactionConfig(require_level=True)
    engine = ReactionEngine(cfg)
    bars = _ignition_series()
    # Level far away -> no level context -> should not fire.
    far = LevelOfInterest(price=1.2000, label="far", kind="daily")
    assess = engine.assess(bars, atr=0.0020, levels=[far])
    assert not assess.fired
    assert assess.signal is None
    assert "level" in assess.rejection.lower()


def test_engine_low_conviction_no_fire():
    cfg = ReactionConfig()
    engine = ReactionEngine(cfg)
    bars = flat_series(25, rng=0.0006)  # quiet, no commitment
    assess = engine.assess(bars, atr=0.0020, levels=[
        LevelOfInterest(1.1000, "x", "daily"),
    ])
    assert not assess.fired
    assert assess.conviction < cfg.conviction_threshold


def test_engine_disabled_returns_diagnostic():
    cfg = ReactionConfig(enabled=False)
    engine = ReactionEngine(cfg)
    assess = engine.assess(_ignition_series(), atr=0.0020, levels=[])
    assert not assess.fired
    assert assess.rejection == "insufficient data"


def test_assessment_always_has_components_dict():
    cfg = ReactionConfig()
    engine = ReactionEngine(cfg)
    assess = engine.assess(_ignition_series(), atr=0.0020, levels=[
        LevelOfInterest(1.1080, "PDH", "daily"),
    ])
    d = assess.components.as_dict()
    assert set(d) == {"displacement", "expansion", "momentum", "imbalance"}
