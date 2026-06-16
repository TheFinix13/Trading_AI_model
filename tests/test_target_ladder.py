"""Extension-target ladder contracts: the ladder must OPINE and never trade.

Covers:
(a) rung computation from a synthetic perception context — source filtering
    (beyond-TP only, correct side per direction), nearest-first ordering,
    dedupe, max-rung cap and R math;
(b) MFE scoring of journaled rungs (reached / distance);
(c) VaultRecorder.record_ladder writes valid JSONL (+ snapshot PNG with the
    rung levels);
(d) SignalLoop seam: a filled order journals the entry-phase ladder and a
    close journals the scored rungs — and the placed order is byte-identical
    whether the ladder computes, crashes, or has no context at all (the
    zero-behaviour-change regression guard);

No real brokers, no live folders: synthetic bars and tmp_path throughout.
Fakes follow tests/test_vaults.py conventions.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent.alphas.base import AlphaSignal
from agent.config import load_config
from agent.detectors.daily_levels import DailyLevels
from agent.journal.target_ladder import (
    TargetRung,
    compute_target_ladder,
    ladder_summary,
    ladder_summary_from_dicts,
    score_rungs,
)
from agent.journal.vault import VaultRecorder
from agent.live.broker import OrderResult
from agent.live.config import LiveConfig
from agent.live.signal_loop import SignalLoop, _RoutedSignal
from agent.types import Bar, Direction, FibLevel, Swing, Timeframe, Trendline, Zone

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(n: int = 120, start: float = 1.1000) -> list[Bar]:
    out = []
    price = start
    for i in range(n):
        drift = 0.0003 * (1 if (i // 17) % 2 == 0 else -1)
        o = price
        c = price + drift
        out.append(Bar(time=T0 + timedelta(hours=4 * i), open=o,
                       high=max(o, c) + 0.0002, low=min(o, c) - 0.0002,
                       close=c, volume=100.0, timeframe=Timeframe.H4))
        price = c
    return out


def _swing(price: float, bar_index: int, is_high: bool = True) -> Swing:
    return Swing(time=T0 + timedelta(hours=4 * bar_index), price=price,
                 is_high=is_high, bar_index=bar_index)


def _zone(direction: Direction, top: float, bottom: float,
          bar_index: int = 50, mitigated: bool = False) -> Zone:
    return Zone(direction=direction, top=top, bottom=bottom,
                created_at=T0 + timedelta(hours=4 * bar_index),
                created_bar_index=bar_index, impulse_pips=30.0,
                mitigated=mitigated)


def _ctx(**overrides) -> SimpleNamespace:
    base = dict(swings=[], zones=[], trendlines=[], fib_by_index={},
                daily_levels=[])
    base.update(overrides)
    return SimpleNamespace(**base)


# Long trade used throughout: 50-pip soft stop, mechanical TP at 1.5R.
ENTRY, STOP, TP = 1.1000, 1.0950, 1.1075


# ----------------------------------------------------------------------
# (a) rung computation
# ----------------------------------------------------------------------

def test_swing_rungs_only_beyond_tp_and_correct_side():
    ctx = _ctx(swings=[
        _swing(1.1050, 80),          # below TP — excluded
        _swing(1.1100, 70),          # beyond TP — included (2.0R)
        _swing(1.1150, 60),          # beyond TP — included (3.0R)
        _swing(1.1200, 90, is_high=False),  # swing LOW — wrong side for a long
        _swing(1.1300, 99),          # at_index or later — not yet formed
    ])
    rungs = compute_target_ladder(
        ctx, 99, direction=Direction.LONG, entry=ENTRY, stop=STOP,
        take_profit=TP)
    assert [r.source for r in rungs] == ["swing", "swing"]
    assert [r.price for r in rungs] == [1.1100, 1.1150]  # nearest first
    assert rungs[0].r_multiple == pytest.approx(2.0)
    assert rungs[1].r_multiple == pytest.approx(3.0)


def test_zone_edge_uses_opposite_side_near_edge():
    ctx = _ctx(zones=[
        _zone(Direction.SHORT, top=1.1140, bottom=1.1120),  # supply overhead
        _zone(Direction.LONG, top=1.1190, bottom=1.1180),   # demand — ignored
        _zone(Direction.SHORT, top=1.1300, bottom=1.1250, mitigated=True),
    ])
    rungs = compute_target_ladder(
        ctx, 99, direction=Direction.LONG, entry=ENTRY, stop=STOP,
        take_profit=TP)
    assert len(rungs) == 1
    assert rungs[0].source == "zone_edge"
    assert rungs[0].price == pytest.approx(1.1120)  # bottom = near edge


def test_trendline_fib_and_daily_levels():
    tl = Trendline(slope=0.00001, intercept=1.1100, anchors=[],
                   direction=Direction.SHORT)
    # projection at bar 99+20: 1.1100 + 0.00001*119 = 1.11119
    fib = FibLevel(impulse_start=1.0900, impulse_end=1.1060,
                   direction=Direction.LONG, levels={}, created_at=T0)
    # extensions: 1.272 -> 1.110352, 1.618 -> 1.115888
    daily = [None] * 99 + [DailyLevels(pdh=1.1130, pdl=1.0900)]
    ctx = _ctx(trendlines=[tl], fib_by_index={75: fib}, daily_levels=daily)

    rungs = compute_target_ladder(
        ctx, 99, direction=Direction.LONG, entry=ENTRY, stop=STOP,
        take_profit=TP)
    by_source = {r.source: r for r in rungs}
    assert by_source["trendline"].price == pytest.approx(1.11119, abs=1e-5)
    assert by_source["daily_level"].price == pytest.approx(1.1130)
    assert by_source["daily_level"].detail == "PDH"
    fib_prices = sorted(r.price for r in rungs if r.source == "fib_ext")
    assert fib_prices == [pytest.approx(1.11035, abs=1e-5),
                          pytest.approx(1.11589, abs=1e-5)]
    # PDL (1.0900) is below TP for a long — must not appear.
    assert all(r.price > TP for r in rungs)


def test_short_direction_mirrors():
    ctx = _ctx(
        swings=[_swing(1.0850, 70, is_high=False),  # swing low below short TP
                _swing(1.0990, 80, is_high=False)],  # inside TP — excluded
        zones=[_zone(Direction.LONG, top=1.0830, bottom=1.0800)],
    )
    rungs = compute_target_ladder(
        ctx, 99, direction=Direction.SHORT, entry=1.1000, stop=1.1050,
        take_profit=1.0925)
    assert [(r.source, r.price) for r in rungs] == [
        ("swing", 1.0850), ("zone_edge", 1.0830)]
    assert rungs[0].r_multiple == pytest.approx(3.0)


def test_dedupe_and_max_rungs_cap():
    swings = [_swing(1.1100, 70), _swing(1.11005, 60)]  # 0.5 pips apart
    swings += [_swing(1.1100 + 0.0010 * k, 50 + k) for k in range(1, 10)]
    ctx = _ctx(swings=swings)
    rungs = compute_target_ladder(
        ctx, 99, direction=Direction.LONG, entry=ENTRY, stop=STOP,
        take_profit=TP, max_rungs=4)
    assert len(rungs) == 4
    prices = [r.price for r in rungs]
    assert prices == sorted(prices)
    # The 0.5-pip duplicate must have been collapsed into one rung.
    assert sum(1 for p in prices if abs(p - 1.1100) < 0.0003) == 1


def test_invalid_inputs_return_empty():
    ctx = _ctx(swings=[_swing(1.1100, 70)])
    common = dict(direction=Direction.LONG, take_profit=TP)
    assert compute_target_ladder(ctx, 99, entry=ENTRY, stop=ENTRY, **common) == []
    assert compute_target_ladder(ctx, 99, entry=0.0, stop=STOP, **common) == []
    assert compute_target_ladder(_ctx(), 99, entry=ENTRY, stop=STOP, **common) == []


def test_malformed_detector_output_is_skipped_not_raised():
    ctx = _ctx(swings=[object()], zones=[object()], trendlines=[object()],
               fib_by_index={50: object()}, daily_levels=[object()] * 100)
    assert compute_target_ladder(
        ctx, 99, direction=Direction.LONG, entry=ENTRY, stop=STOP,
        take_profit=TP) == []


# ----------------------------------------------------------------------
# (b) MFE scoring + summaries
# ----------------------------------------------------------------------

def test_score_rungs_marks_reached_by_mfe():
    rungs = [
        TargetRung(price=1.1100, source="swing", r_multiple=2.0).to_dict(),
        TargetRung(price=1.1150, source="zone_edge", r_multiple=3.0).to_dict(),
    ]
    scored = score_rungs(rungs, entry=ENTRY, mfe_pips=120.0)
    assert scored[0]["reached"] is True
    assert scored[0]["distance_pips"] == pytest.approx(100.0)
    assert scored[1]["reached"] is False
    assert scored[1]["distance_pips"] == pytest.approx(150.0)


def test_summaries_render():
    rung = TargetRung(price=1.1100, source="swing", r_multiple=2.0)
    assert ladder_summary([rung]) == "swing 1.11000 (2.0R)"
    assert ladder_summary_from_dicts([rung.to_dict(), {"bad": 1}]) == \
        "swing 1.11000 (2.0R)"


# ----------------------------------------------------------------------
# (c) vault recorder
# ----------------------------------------------------------------------

def test_vault_record_ladder_writes_jsonl_and_png(tmp_path):
    vault = VaultRecorder("EURUSD", root=tmp_path)
    bars = _bars(120)
    vault.record_ladder({
        "ts": bars[100].time.isoformat(),
        "tf": "H4",
        "phase": "entry",
        "ticket": 777,
        "direction": "long",
        "entry": ENTRY, "stop": STOP, "take_profit": TP,
        "rungs": [TargetRung(price=1.1100, source="swing",
                             r_multiple=2.0).to_dict()],
    }, bars)

    jsonl = tmp_path / "EURUSD" / "ladders" / "events.jsonl"
    assert jsonl.exists()
    rec = json.loads(jsonl.read_text().strip())
    assert rec["phase"] == "entry" and rec["ticket"] == 777
    assert rec["rungs"][0]["source"] == "swing"
    pngs = list((tmp_path / "EURUSD" / "ladders").glob("*.png"))
    assert len(pngs) == 1 and pngs[0].stat().st_size > 0
    assert "ladder_entry" in pngs[0].name


def test_vault_record_ladder_never_raises(tmp_path):
    vault = VaultRecorder("EURUSD", root=tmp_path)
    vault.record_ladder({"ts": object(), "rungs": object()}, None)


# ----------------------------------------------------------------------
# (d) SignalLoop seam — journal yes, trade-change never
# ----------------------------------------------------------------------

class _FakeBroker:
    """Accepts every order and records the exact request it received."""

    def __init__(self):
        self.orders: list[tuple] = []

    async def get_account_info(self):
        return SimpleNamespace(balance=10_000.0, equity=10_000.0,
                               leverage=500, free_margin=10_000.0)

    async def get_open_positions(self, symbol):
        return []

    async def place_order(self, symbol, direction, lot, stop, tp, comment=""):
        self.orders.append((symbol, direction.value, round(lot, 2),
                            round(stop, 6), round(tp, 6), comment))
        return OrderResult(success=True, ticket=777, fill_price=ENTRY,
                           fill_time=datetime.now(tz=timezone.utc))


def _make_loop(broker, vault=None):
    cfg = load_config()
    live = LiveConfig(symbol="EURUSD", timeframes=["H4"],
                      telegram_enabled=False)
    return SignalLoop(
        [SimpleNamespace(name="zone_h4_all",
                         signal=lambda actx, i: None)],
        config=cfg, live_config=live, broker=broker, vault=vault,
    )


def _routed(loop) -> _RoutedSignal:
    signal = AlphaSignal(direction=Direction.LONG, entry=ENTRY, stop=STOP,
                         take_profit=TP, conviction=0.65)
    return _RoutedSignal(loop.alphas[0], signal, "H4")


_LAST_CLOSED = SimpleNamespace(time=datetime(2026, 6, 10, tzinfo=timezone.utc))


def test_filled_order_journals_entry_ladder(tmp_path):
    broker = _FakeBroker()
    vault = VaultRecorder("EURUSD", root=tmp_path)
    loop = _make_loop(broker, vault)
    bars = _bars(120)
    ctx = _ctx(swings=[_swing(1.1100, 70), _swing(1.1150, 60)])

    asyncio.run(loop._route_signal(_routed(loop), _LAST_CLOSED,
                                   bars=bars, ctx=ctx))

    assert len(broker.orders) == 1
    # Ladder reached the monitor's entry context for close-time scoring…
    entry_ctx = loop.monitor._entry_ctx[777]
    assert [r["price"] for r in entry_ctx["target_ladder"]] == [1.1100, 1.1150]
    # …and the entry-phase opinion was vaulted.
    jsonl = tmp_path / "EURUSD" / "ladders" / "events.jsonl"
    rec = json.loads(jsonl.read_text().strip())
    assert rec["phase"] == "entry" and rec["ticket"] == 777
    assert len(rec["rungs"]) == 2


def test_order_identical_with_crashing_ladder_and_without_ctx(monkeypatch,
                                                              tmp_path):
    """The zero-behaviour-change guard: the placed order must be identical
    whether the ladder computes fine, explodes, or has no context."""
    bars = _bars(120)
    ctx = _ctx(swings=[_swing(1.1100, 70)])

    broker_ok = _FakeBroker()
    loop_ok = _make_loop(broker_ok, VaultRecorder("EURUSD", root=tmp_path))
    asyncio.run(loop_ok._route_signal(_routed(loop_ok), _LAST_CLOSED,
                                      bars=bars, ctx=ctx))

    import agent.live.signal_loop as sl

    def boom(*a, **kw):
        raise RuntimeError("ladder exploded")

    monkeypatch.setattr(sl, "compute_target_ladder", boom)
    broker_boom = _FakeBroker()
    loop_boom = _make_loop(broker_boom, VaultRecorder("EURUSD", root=tmp_path))
    asyncio.run(loop_boom._route_signal(_routed(loop_boom), _LAST_CLOSED,
                                        bars=bars, ctx=ctx))
    monkeypatch.undo()

    broker_none = _FakeBroker()
    loop_none = _make_loop(broker_none)
    asyncio.run(loop_none._route_signal(_routed(loop_none), _LAST_CLOSED))

    assert broker_ok.orders == broker_boom.orders == broker_none.orders
    assert len(broker_ok.orders) == 1
    # The crashing ladder still registered the trade (with an empty ladder).
    assert loop_boom.monitor._entry_ctx[777]["target_ladder"] == []


def test_close_scores_rungs_against_mfe(tmp_path):
    broker = _FakeBroker()
    vault = VaultRecorder("EURUSD", root=tmp_path)
    loop = _make_loop(broker, vault)

    entry_ctx = {
        "alpha": "zone_h4_all", "timeframe": "H4", "direction": "long",
        "entry": ENTRY, "entry_time": T0.isoformat(),
        "soft_stop": STOP, "take_profit": TP, "conviction": 0.65,
        "target_ladder": [
            TargetRung(price=1.1100, source="swing", r_multiple=2.0).to_dict(),
            TargetRung(price=1.1150, source="zone_edge",
                       r_multiple=3.0).to_dict(),
        ],
    }
    info = {"pnl": 75.0, "pnl_pips": 75.0, "r_multiple": 1.5,
            "mae_pips": 10.0, "mfe_pips": 110.0, "exit_price": TP,
            "exit_reason": "tp", "entry_ctx": entry_ctx}
    loop._on_trade_closed(777, info)

    jsonl = tmp_path / "EURUSD" / "ladders" / "events.jsonl"
    rec = json.loads(jsonl.read_text().strip())
    assert rec["phase"] == "close" and rec["ticket"] == 777
    by_source = {r["source"]: r for r in rec["rungs"]}
    assert by_source["swing"]["reached"] is True      # 100p <= 110p MFE
    assert by_source["zone_edge"]["reached"] is False  # 150p > 110p MFE


def test_close_without_ladder_or_vault_is_silent():
    loop = _make_loop(_FakeBroker())  # vault=None
    info = {"pnl": 75.0, "pnl_pips": 75.0, "r_multiple": 1.5,
            "mfe_pips": 110.0, "exit_reason": "tp",
            "entry_ctx": {"direction": "long", "entry": ENTRY}}
    loop._on_trade_closed(777, info)  # must not raise


def test_filled_order_emits_ladder_log_line(caplog, tmp_path):
    """The [LADDER] daily-log line must mirror the journaled ladder.

    Regression guard for the operability requirement: when a fill computes
    structural rungs, those same rungs land on a single grep-able log line
    so an operator tailing the daily log sees what the JSONL records.
    """
    import logging as _logging
    broker = _FakeBroker()
    loop = _make_loop(broker, VaultRecorder("EURUSD", root=tmp_path))
    bars = _bars(120)
    ctx = _ctx(swings=[_swing(1.1100, 70), _swing(1.1150, 60)])

    with caplog.at_level(_logging.INFO, logger="agent.live.signal_loop"):
        asyncio.run(loop._route_signal(_routed(loop), _LAST_CLOSED,
                                       bars=bars, ctx=ctx))

    ladder_lines = [r.message for r in caplog.records
                    if r.message.startswith("[LADDER]")]
    assert len(ladder_lines) == 1, ladder_lines
    msg = ladder_lines[0]
    assert "ticket=777" in msg
    assert "n=2" in msg
    assert "swing=1.11000" in msg
    assert "swing=1.11500" in msg


def test_filled_order_emits_ladder_line_even_when_empty(monkeypatch, tmp_path,
                                                       caplog):
    """No rungs → still log a [LADDER] n=0 line so every fill has a marker."""
    import logging as _logging
    import agent.live.signal_loop as sl

    monkeypatch.setattr(sl, "compute_target_ladder", lambda *a, **kw: [])
    loop = _make_loop(_FakeBroker(), VaultRecorder("EURUSD", root=tmp_path))
    bars = _bars(120)
    ctx = _ctx()

    with caplog.at_level(_logging.INFO, logger="agent.live.signal_loop"):
        asyncio.run(loop._route_signal(_routed(loop), _LAST_CLOSED,
                                       bars=bars, ctx=ctx))
    ladder_lines = [r.message for r in caplog.records
                    if r.message.startswith("[LADDER]")]
    assert len(ladder_lines) == 1
    assert "n=0" in ladder_lines[0]
    assert "no structural rungs" in ladder_lines[0]
