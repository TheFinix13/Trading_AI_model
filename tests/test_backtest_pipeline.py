"""End-to-end smoke test: synthetic data -> detectors -> rules -> backtester -> features -> ML training."""
from agent.backtest.engine import Backtester
from agent.config import load_config
from agent.data.loader import df_to_bars
from agent.data.synthetic import generate
from agent.types import Timeframe


def test_pipeline_runs_on_synthetic():
    cfg = load_config()
    df = generate(timeframe=Timeframe.H1, n_bars=2000, seed=11)
    bars = df_to_bars(df, Timeframe.H1)
    assert len(bars) == 2000

    bt = Backtester(cfg)
    result = bt.run(bars)
    assert result.metrics is not None
    assert result.equity_curve
    # Trades may be 0 on synthetic since structures are unrealistic;
    # we just verify the pipeline doesn't crash.


def test_precompute_then_evaluate():
    from agent.rules.engine import RuleEngine, precompute

    cfg = load_config()
    df = generate(timeframe=Timeframe.H1, n_bars=1000, seed=3)
    bars = df_to_bars(df, Timeframe.H1)
    ctx = precompute(bars, cfg)
    engine = RuleEngine(cfg)
    for i in range(60, 100):
        engine.evaluate_precomputed(ctx, i)  # should not raise
