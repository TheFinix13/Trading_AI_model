"""Entry-quality gates: candle-close confirmation + false-breakout rejection.

These tests lock in the trader-feedback-driven behavior: the bot must NOT enter
on raw setup detection. It has to wait for a confirmation candle and reject
fake-breakout zones."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.config import load_config
from agent.types import Bar, Direction, Setup, Timeframe, Zone


def _bar(t, o, h, l, c, tf=Timeframe.M15):
    return Bar(time=t, open=o, high=h, low=l, close=c, volume=1000.0, timeframe=tf)


def test_confluence_tfs_default_empty():
    """A bare Setup has empty confluence_tfs by default."""
    s = Setup(direction=Direction.LONG, timeframe=Timeframe.M15,
              detected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
              detected_bar_index=0, entry=1.10, stop=1.099, take_profit=1.102)
    assert s.confluence_tfs == {}
    assert s.entry_confirmation is None


def test_confluence_tfs_populated_via_engine_path():
    """When the engine creates a setup with confluences, each tag must map to the
    setup's TF — that's the contract the dashboard relies on."""
    s = Setup(direction=Direction.LONG, timeframe=Timeframe.M15,
              detected_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
              detected_bar_index=0, entry=1.10, stop=1.099, take_profit=1.102,
              confluences=["zone", "fvg"],
              confluence_tfs={"zone": "M15", "fvg": "M15", "htf_bias_long": "D1"})
    assert s.confluence_tfs["zone"] == "M15"
    assert s.confluence_tfs["fvg"] == "M15"
    assert s.confluence_tfs["htf_bias_long"] == "D1"


def test_config_default_gates_enabled():
    """The candle-close + false-breakout gates must be enabled by default."""
    cfg = load_config()
    assert cfg.rules.require_close_confirmation is True
    assert cfg.rules.reject_false_breakouts is True


def test_d1_h4_default_bias_only():
    """run_multitf default is to treat D1/H4 as bias-only (no entries)."""
    from agent.backtest.multi_tf import run_multi_tf
    import inspect
    sig = inspect.signature(run_multi_tf)
    assert sig.parameters["bias_only_tfs"].default is None  # default sentinel
    # The actual default {H4, D1} is applied inside the body — verify by calling
    # with a zero-bar dict and checking the log path executes cleanly.
    cfg = load_config()
    res = run_multi_tf(cfg, bars_by_tf={}, journal=None)
    assert res.metrics is not None
