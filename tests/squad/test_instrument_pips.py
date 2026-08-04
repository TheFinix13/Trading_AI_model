"""I030 regression tests -- symbol-aware pip semantics in the squad path.

Before 2026-08-04 every pip conversion in the squad layer hardcoded the
4-digit major pip (1e-4). Sentinel R1 read a 0.50-yen USDJPY stop as
5,000 pips and blocked 100% of JPY proposals (Phase AL: 0 trades on
1,553 proposal ticks), and the paper broker would have logged pnl_pips
100x too small had anything filled. These tests pin the fix.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.squad.provenance_pips import (
    pip_size_for,
    pip_value_per_min_lot_for,
)
from agent.squad.sentinel import SentinelContext, evaluate_proposal
from agent.squad.types import SCHEMA_VERSION, AgentProposal, LadderRung


def _ts() -> datetime:
    return datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)


def _proposal(symbol: str, entry: float, stop: float, tp: float,
              direction: str = "long") -> AgentProposal:
    return AgentProposal(
        agent_id="test_agent",
        tick_id=1,
        source_thought_id=f"test:1:{symbol}",
        timestamp=_ts(),
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry=entry,
        stop=stop,
        ladder=[LadderRung(price=tp, fraction=1.0)],
        conviction=0.8,
        regime_fit=0.5,
        valid_until=_ts() + timedelta(hours=24),
        rationale={"signal_reason": "test"},
        agent_tier=2,
    )


# ---------------------------------------------------------------------------
# pip-size table
# ---------------------------------------------------------------------------


def test_pip_size_majors_unchanged():
    for sym in ("EURUSD", "GBPUSD", "USDCAD", "AUDUSD", "NZDUSD", "USDCHF"):
        assert pip_size_for(sym) == pytest.approx(1e-4)


def test_pip_size_jpy_quotes():
    for sym in ("USDJPY", "EURJPY", "GBPJPY", "usdjpy"):
        assert pip_size_for(sym) == pytest.approx(1e-2)


def test_pip_size_non_fx_fields():
    assert pip_size_for("XAUUSD") == pytest.approx(0.1)
    assert pip_size_for("XAGUSD") == pytest.approx(0.01)
    assert pip_size_for("USOIL") == pytest.approx(0.01)
    assert pip_size_for("USTEC") == pytest.approx(1.0)
    assert pip_size_for("BTCUSD") == pytest.approx(1.0)


def test_pip_value_per_min_lot():
    assert pip_value_per_min_lot_for("EURUSD") == pytest.approx(0.10)
    assert pip_value_per_min_lot_for("USDJPY") == pytest.approx(0.07)
    assert pip_value_per_min_lot_for("XAUUSD") == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Sentinel R1 -- the exact Phase AL failure mode
# ---------------------------------------------------------------------------


def _ctx(symbol: str) -> SentinelContext:
    return SentinelContext(
        equity=100.0,
        pip_value_per_min_lot=pip_value_per_min_lot_for(symbol),
    )


def test_r1_passes_normal_usdjpy_stop():
    # 0.50-yen stop = 50 JPY pips; implied risk 50 * $0.07 = $3.50,
    # under the 5% x $100 = $5 cap. Pre-fix this read as 5,000 pips
    # ($500 implied risk) and was blocked -- the I030 bug.
    p = _proposal("USDJPY", entry=145.00, stop=144.50, tp=145.75)
    decision = evaluate_proposal(p, _ctx("USDJPY"))
    assert decision.allowed, decision.reason


def test_r1_still_blocks_oversized_usdjpy_stop():
    # 1.20-yen stop = 120 pips -> $8.40 implied risk > $5 cap.
    p = _proposal("USDJPY", entry=145.00, stop=143.80, tp=146.80)
    decision = evaluate_proposal(p, _ctx("USDJPY"))
    assert not decision.allowed
    assert decision.rule == "R1"


def test_r1_major_behaviour_identical_to_pre_fix():
    # 20-pip EURUSD stop passes (as before the fix)...
    p = _proposal("EURUSD", entry=1.1000, stop=1.0980, tp=1.1030)
    assert evaluate_proposal(p, _ctx("EURUSD")).allowed
    # ...and a 60-pip stop is still an R1 refusal ($6 > $5 cap).
    p = _proposal("EURUSD", entry=1.1000, stop=1.0940, tp=1.1090)
    decision = evaluate_proposal(p, _ctx("EURUSD"))
    assert not decision.allowed
    assert decision.rule == "R1"


def test_r1_passes_gold_stop():
    # $3.00 gold stop = 30 pips at 0.1 pip size -> $3 implied risk.
    p = _proposal("XAUUSD", entry=2400.0, stop=2397.0, tp=2404.5)
    assert evaluate_proposal(p, _ctx("XAUUSD")).allowed


# ---------------------------------------------------------------------------
# Paper broker KPI math
# ---------------------------------------------------------------------------


def test_paper_broker_pnl_pips_symbol_aware():
    from agent.squad.paper_broker import PaperBroker
    from agent.types import Bar, Timeframe

    broker = PaperBroker()
    p = _proposal("USDJPY", entry=145.00, stop=144.50, tp=145.75)
    next_bar = Bar(
        time=_ts(), open=145.00, high=145.10, low=144.95, close=145.05,
        volume=1000, timeframe=Timeframe.H4,
    )
    ot = broker.open_from_proposal(p, next_bar)

    # source_sl_pips must be ~50 JPY pips, not 5,000.
    assert ot.source_sl_pips == pytest.approx(50.0, abs=0.5)

    # Excursion tracking in JPY pips: a bar 0.30 yen above entry = 30 pips.
    fill = ot.trade.entry_price
    bar2 = Bar(
        time=_ts() + timedelta(hours=4), open=fill, high=fill + 0.30,
        low=fill - 0.10, close=fill + 0.20, volume=1000,
        timeframe=Timeframe.H4,
    )
    broker.update_excursion(ot, bar2)
    assert ot.trade.mfe_pips == pytest.approx(30.0, abs=0.1)
    assert ot.trade.mae_pips == pytest.approx(10.0, abs=0.1)

    # Force a TP exit: pnl_pips ~ +75 JPY pips, r_multiple ~ +1.5.
    tp_bar = Bar(
        time=_ts() + timedelta(hours=8), open=fill + 0.40,
        high=ot.trade.tp_price + 0.05, low=fill + 0.35,
        close=ot.trade.tp_price, volume=1000, timeframe=Timeframe.H4,
    )
    assert broker.check_exit(ot, tp_bar)
    record = broker.score(ot)
    assert record.pnl_pips == pytest.approx(75.0, abs=1.0)
    assert record.r_multiple == pytest.approx(1.5, abs=0.05)


def test_paper_broker_major_pnl_unchanged():
    from agent.squad.paper_broker import PaperBroker
    from agent.types import Bar, Timeframe

    broker = PaperBroker()
    p = _proposal("EURUSD", entry=1.1000, stop=1.0980, tp=1.1030)
    next_bar = Bar(
        time=_ts(), open=1.1000, high=1.1005, low=1.0998, close=1.1002,
        volume=1000, timeframe=Timeframe.H4,
    )
    ot = broker.open_from_proposal(p, next_bar)
    assert ot.source_sl_pips == pytest.approx(20.0, abs=0.5)
    fill = ot.trade.entry_price
    sl_bar = Bar(
        time=_ts() + timedelta(hours=4), open=fill,
        high=fill + 0.0002, low=ot.trade.stop_price - 0.0001,
        close=ot.trade.stop_price, volume=1000, timeframe=Timeframe.H4,
    )
    assert broker.check_exit(ot, sl_bar)
    record = broker.score(ot)
    assert record.pnl_pips == pytest.approx(-20.0, abs=0.5)
    assert record.r_multiple == pytest.approx(-1.0, abs=0.05)
