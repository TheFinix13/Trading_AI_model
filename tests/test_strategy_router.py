"""Tests for `agent.strategy.registry` (registry + router) and the
phase-1 strategy shims.

Covers:
    * Registry: register / unregister / unique-name enforcement.
    * StrategyStats: WR / PF arithmetic + score thresholds.
    * StrategyRouter.route: only compatible strategies are run.
    * StrategyRouter.select_best: highest-score wins; under-sampled cells
      use the neutral prior; below-min-score returns None.
    * default_registry imports + registers all 5 phase-1 strategies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.regime.detector import RegimeLabel
from agent.strategy.base import Strategy
from agent.strategy.registry import (
    MIN_SAMPLES_FOR_PRIOR_OVERRIDE,
    MIN_SELECTION_SCORE,
    StatsHistory,
    StrategyRegistry,
    StrategyRouter,
    StrategyStats,
    default_registry,
)
from agent.types import Bar, Direction, Setup, Timeframe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bar(t: datetime, c: float = 1.1) -> Bar:
    return Bar(time=t, open=c, high=c + 0.0005, low=c - 0.0005, close=c, volume=0.0, timeframe=Timeframe.H1)


def _setup(strategy_name: str, direction: Direction = Direction.LONG, idx: int = 0) -> Setup:
    bar = _bar(datetime(2026, 5, 14, tzinfo=timezone.utc))
    return Setup(
        direction=direction,
        timeframe=bar.timeframe,
        detected_at=bar.time,
        detected_bar_index=idx,
        entry=bar.close,
        stop=bar.close - 0.001,
        take_profit=bar.close + 0.0015,
        confluences=[strategy_name],
        strategy_name=strategy_name,
    )


class _StubStrategy(Strategy):
    """Records calls and returns a configurable Setup-or-None."""

    def __init__(
        self,
        name: str,
        compatible: frozenset[str] = frozenset({"chop", "trending_up", "trending_down", "low_vol", "high_vol"}),
        result: Setup | None = "default",
    ):
        self.name = name
        self.compatible_regimes = compatible
        self._result = result
        self.calls = 0

    def evaluate(self, ctx, at_index: int) -> Setup | None:
        self.calls += 1
        if self._result == "default":
            return _setup(self.name, idx=at_index)
        return self._result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_register_and_get():
    reg = StrategyRegistry()
    s = _StubStrategy("A")
    reg.register(s)
    assert "A" in reg
    assert reg.get("A") is s
    assert reg.get("missing") is None
    assert reg.names() == ["A"]
    assert len(reg) == 1


def test_registry_rejects_duplicate_names():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("A"))
    with pytest.raises(ValueError):
        reg.register(_StubStrategy("A"))


def test_registry_unregister():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("A"))
    reg.unregister("A")
    assert "A" not in reg
    # Unregistering missing name is a no-op.
    reg.unregister("nope")


def test_registry_compatible_filters_by_regime():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("trend_only", compatible=frozenset({"trending_up", "trending_down"})))
    reg.register(_StubStrategy("chop_only", compatible=frozenset({"chop"})))
    out = [s.name for s in reg.compatible("chop")]
    assert out == ["chop_only"]
    out2 = [s.name for s in reg.compatible("trending_up")]
    assert out2 == ["trend_only"]


def test_registry_default_loads_all_phase1_strategies():
    reg = default_registry()
    expected = {
        "LiquidityGrabReversal", "FVGRetest", "BOSContinuation",
        "FibRetracement", "SDZoneRetest",
    }
    assert set(reg.names()) == expected


# ---------------------------------------------------------------------------
# StrategyStats arithmetic
# ---------------------------------------------------------------------------


def test_stats_n_wr_pf_basics():
    s = StrategyStats()
    assert s.n == 0
    assert s.wr == 0.0
    s.record(10.0)
    s.record(20.0)
    s.record(-5.0)
    assert s.n == 3
    assert s.wins == 2
    assert s.losses == 1
    assert s.wr == pytest.approx(2 / 3)
    # PF = (10+20) / 5 = 6.0
    assert s.pf == pytest.approx(6.0)


def test_stats_pf_handles_zero_loss():
    s = StrategyStats()
    s.record(10.0)
    s.record(20.0)
    # No losses recorded -> PF is +inf.
    import math
    assert math.isinf(s.pf)


def test_stats_score_uses_neutral_prior_below_threshold():
    s = StrategyStats()
    # 1 trade -> still uses the prior.
    s.record(50.0)
    assert s.score() == pytest.approx(0.5)


def test_stats_score_real_after_threshold():
    s = StrategyStats()
    # 35 wins, 5 losses -> well above threshold (default 30).
    for _ in range(35):
        s.record(10.0)
    for _ in range(5):
        s.record(-5.0)
    score = s.score()
    # WR = 0.875, PF = (35*10) / (5*5) = 14, capped to 3 -> 1.0.
    # score = 0.875 * 1.0 = 0.875.
    assert score == pytest.approx(0.875, rel=1e-3)


def test_stats_score_for_terrible_strategy():
    s = StrategyStats()
    for _ in range(40):
        s.record(-5.0)
    # Zero wins -> score = 0.0.
    assert s.score() == 0.0


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class _FakeCtx:
    bars = [_bar(datetime(2026, 5, 14, h, tzinfo=timezone.utc)) for h in range(20)]


def _regime(primary: str = "chop") -> RegimeLabel:
    return RegimeLabel(primary, "ny", True, 0.0, 1.0, 0.5)


def test_router_routes_only_compatible_strategies():
    reg = StrategyRegistry()
    a = _StubStrategy("A", compatible=frozenset({"chop"}))
    b = _StubStrategy("B", compatible=frozenset({"trending_up"}))
    reg.register(a)
    reg.register(b)
    router = StrategyRouter(reg)

    cands = router.route(_FakeCtx(), 5, regime=_regime("chop"))
    names = [c.strategy_name for c in cands]
    assert names == ["A"]
    assert a.calls == 1
    assert b.calls == 0


def test_router_runs_all_when_regime_none():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("A"))
    reg.register(_StubStrategy("B"))
    router = StrategyRouter(reg)
    cands = router.route(_FakeCtx(), 5, regime=None)
    assert {c.strategy_name for c in cands} == {"A", "B"}


def test_router_ignores_strategy_returning_none():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("A"))
    reg.register(_StubStrategy("B", result=None))
    router = StrategyRouter(reg)
    cands = router.route(_FakeCtx(), 5, regime=_regime("chop"))
    assert len(cands) == 1
    assert cands[0].strategy_name == "A"


def test_router_continues_after_strategy_exception():
    class _ExplodingStrategy(Strategy):
        name = "Explodes"
        compatible_regimes = frozenset({"chop"})

        def evaluate(self, ctx, at_index):
            raise RuntimeError("kaboom")

    reg = StrategyRegistry()
    reg.register(_ExplodingStrategy())
    reg.register(_StubStrategy("Survivor", compatible=frozenset({"chop"})))
    router = StrategyRouter(reg)
    cands = router.route(_FakeCtx(), 5, regime=_regime("chop"))
    assert {c.strategy_name for c in cands} == {"Survivor"}


def test_router_select_best_picks_highest_score():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("A", compatible=frozenset({"chop"})))
    reg.register(_StubStrategy("B", compatible=frozenset({"chop"})))
    history = StatsHistory()
    # B has a strong track record in chop, A is mediocre.
    for _ in range(35):
        history.record("B", "chop", 10.0)
    for _ in range(5):
        history.record("B", "chop", -3.0)
    for _ in range(35):
        history.record("A", "chop", 5.0)
    for _ in range(20):
        history.record("A", "chop", -10.0)
    router = StrategyRouter(reg, history=history)
    cands = router.route(_FakeCtx(), 5, regime=_regime("chop"))
    chosen = router.select_best(cands, _regime("chop"))
    assert chosen is not None
    assert chosen.strategy_name == "B"


def test_router_select_best_returns_none_when_below_min_score():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("Bad", compatible=frozenset({"chop"})))
    history = StatsHistory()
    for _ in range(40):
        history.record("Bad", "chop", -5.0)  # zero wins
    router = StrategyRouter(reg, history=history)
    cands = router.route(_FakeCtx(), 5, regime=_regime("chop"))
    chosen = router.select_best(cands, _regime("chop"))
    assert chosen is None


def test_router_select_best_uses_prior_for_undersampled_cells():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("New", compatible=frozenset({"chop"})))
    history = StatsHistory()
    history.record("New", "chop", 50.0)  # 1 sample -> neutral prior 0.5
    router = StrategyRouter(reg, history=history)
    cands = router.route(_FakeCtx(), 5, regime=_regime("chop"))
    chosen = router.select_best(cands, _regime("chop"))
    # Neutral prior 0.5 >= min_score 0.45, so it passes.
    assert chosen is not None
    assert chosen.strategy_name == "New"


def test_router_select_best_returns_none_for_empty_candidates():
    router = StrategyRouter(StrategyRegistry())
    assert router.select_best([], _regime("chop")) is None


def test_router_decide_returns_diagnostic_record():
    reg = StrategyRegistry()
    reg.register(_StubStrategy("A", compatible=frozenset({"chop"})))
    router = StrategyRouter(reg)
    decision = router.decide(_FakeCtx(), 5, _regime("chop"))
    assert decision.regime is not None
    assert "A" in decision.scores
    # Neutral prior with no history -> chosen.
    assert decision.chosen is not None


def test_min_selection_score_constant_is_below_neutral_prior():
    # Sanity: under-sampled cells (prior 0.5) must survive the cut.
    assert MIN_SELECTION_SCORE <= 0.5


def test_min_samples_constant_documented():
    assert MIN_SAMPLES_FOR_PRIOR_OVERRIDE == 30


# ---------------------------------------------------------------------------
# Setup.strategy_name field default
# ---------------------------------------------------------------------------


def test_setup_strategy_name_default_is_none():
    s = Setup(
        direction=Direction.LONG,
        timeframe=Timeframe.H1,
        detected_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        detected_bar_index=0,
        entry=1.1,
        stop=1.099,
        take_profit=1.1015,
    )
    assert s.strategy_name is None


def test_setup_strategy_name_can_be_set():
    s = Setup(
        direction=Direction.LONG,
        timeframe=Timeframe.H1,
        detected_at=datetime(2026, 5, 14, tzinfo=timezone.utc),
        detected_bar_index=0,
        entry=1.1,
        stop=1.099,
        take_profit=1.1015,
        strategy_name="FVGRetest",
    )
    assert s.strategy_name == "FVGRetest"


# ---------------------------------------------------------------------------
# Phase-1 shim smoke tests (each runs without raising on a minimal ctx)
# ---------------------------------------------------------------------------


class _MinimalCtx:
    """The smallest precomputed-like context the shims accept. Mirrors the
    shape of `agent.rules.engine.PrecomputedContext` but with empty fields,
    so each strategy just returns None."""

    def __init__(self, n_bars: int = 60):
        self.bars = [_bar(datetime(2026, 5, 14, tzinfo=timezone.utc) + timedelta(hours=i),
                          c=1.1 + 0.0001 * i)
                     for i in range(n_bars)]
        self.zones = []
        self.fvgs = []
        self.bos_list = []
        self.fib_by_index = {}
        self.atr_by_index = {i: 0.0010 for i in range(n_bars)}
        self.liquidity_sweeps = []


def test_all_phase1_strategies_return_none_on_empty_ctx():
    reg = default_registry()
    ctx = _MinimalCtx()
    for s in reg:
        out = s.evaluate(ctx, len(ctx.bars) - 1)
        assert out is None, f"{s.name} should return None on empty ctx"


def test_all_phase1_strategies_have_unique_names():
    reg = default_registry()
    names = [s.name for s in reg]
    assert len(names) == len(set(names))
