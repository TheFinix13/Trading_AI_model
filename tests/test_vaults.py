"""Near-miss / loss vault contracts: the observation hooks must observe and
NEVER trade differently.

Covers:
(a) SupplyDemandAlpha emits a near-miss via the hook exactly when the HTF
    gate (and only it) rejects, and emits nothing when the hook is unset;
(b) trading output is byte-identical with and without the recorder attached
    (the zero-behaviour-change regression guard);
(c) VaultRecorder writes valid JSONL (+ snapshot PNG);
(d) the resolver scores synthetic events correctly (TP hit, SL hit, the
    conservative same-bar tie-break, and still-open);
(e) the chart renderer produces a PNG from synthetic bars (smoke).

No real brokers, no live folders: everything runs on synthetic bars and
tmp_path. Fakes follow tests/test_live_router_wiring.py conventions.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent.alphas.backtest import run_alpha
from agent.alphas.base import AlphaContext, AlphaSignal
from agent.alphas.concepts.zone_alpha import SupplyDemandAlpha
from agent.config import load_config
from agent.journal.chart_snapshot import render_snapshot
from agent.journal.resolver import (
    load_events,
    resolve_event,
    summarize_by_reason,
    write_events,
)
from agent.journal.vault import VaultRecorder
from agent.live.config import LiveConfig
from agent.live.signal_loop import SignalLoop, _RoutedSignal
from agent.types import Bar, Direction, Timeframe

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(n: int = 400, start: float = 1.1000) -> list[Bar]:
    """Synthetic zig-zag (same shape as tests/test_concept_alphas.py)."""
    out = []
    price = start
    for i in range(n):
        spike = 0.0008 if i % 47 == 0 else 0.0003
        drift = spike * (1 if (i // 17) % 2 == 0 else -1)
        o = price
        c = price + drift
        h = max(o, c) + 0.0002
        lo = min(o, c) - 0.0002
        out.append(Bar(time=T0 + timedelta(hours=i), open=o, high=h, low=lo,
                       close=c, volume=100.0, timeframe=Timeframe.H1))
        price = c
    return out


def _flat_bar(i: int, price: float, *, high=None, low=None) -> Bar:
    return Bar(time=T0 + timedelta(hours=4 * i), open=price,
               high=high if high is not None else price + 0.0002,
               low=low if low is not None else price - 0.0002,
               close=price, volume=100.0, timeframe=Timeframe.H4)


# ----------------------------------------------------------------------
# (a) alpha-level near-miss hook
# ----------------------------------------------------------------------

def test_hook_fires_only_on_htf_gate_rejection():
    """Where the unfiltered alpha signals but the HTF-filtered one returns
    None, the hook must have captured the exact hypothetical the gate
    blocked (reason=htf_gate, identical entry/SL/TP)."""
    from agent.rules.engine import precompute
    cfg = load_config()
    bars = _bars(600)
    ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)

    plain = SupplyDemandAlpha(cfg)
    events: list[dict] = []
    hooked = SupplyDemandAlpha(
        cfg, htf_align="D1",
        near_miss_hook=lambda evt, bars_: events.append(evt),
    )

    checked = 0
    for i in range(50, 600):
        base_sig = plain.signal(actx, i)
        events.clear()
        gated_sig = hooked.signal(actx, i)
        if base_sig is None:
            # No would-be trade -> the gate had nothing to block.
            assert events == []
            continue
        if gated_sig is not None:
            continue  # gate let something through; nothing to assert here
        # Trade existed, gate killed it: the first near-miss must mirror it.
        assert events, f"htf gate rejected at bar {i} but hook never fired"
        evt = events[0]
        assert evt["reason"] == "htf_gate"
        assert evt["direction"] == base_sig.direction.value
        assert evt["entry"] == pytest.approx(base_sig.entry)
        assert evt["stop"] == pytest.approx(base_sig.stop)
        assert evt["take_profit"] == pytest.approx(base_sig.take_profit)
        assert evt["conviction"] == pytest.approx(base_sig.conviction)
        assert {"top", "bottom", "direction"} <= set(evt["zone"])
        checked += 1
    assert checked > 0, "synthetic series produced no htf-gate rejections"


def test_hook_unset_means_no_emission_and_no_attribute_surprises():
    """Default alpha has near_miss_hook=None and signal() behaves as before
    (the hook seam is dormant)."""
    from agent.rules.engine import precompute
    cfg = load_config()
    bars = _bars(300)
    ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)
    alpha = SupplyDemandAlpha(cfg, htf_align="D1")
    assert alpha.near_miss_hook is None
    for i in range(50, 300):
        alpha.signal(actx, i)  # must not raise


def test_hook_never_fires_without_htf_filter():
    """With htf_align=None the gate doesn't exist, so the hook must stay
    silent even when attached."""
    from agent.rules.engine import precompute
    cfg = load_config()
    bars = _bars(400)
    ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)
    events: list[dict] = []
    alpha = SupplyDemandAlpha(
        cfg, near_miss_hook=lambda evt, bars_: events.append(evt))
    for i in range(50, 400):
        alpha.signal(actx, i)
    assert events == []


def test_hook_exception_never_breaks_signal():
    """A crashing hook is swallowed; signal() still works."""
    from agent.rules.engine import precompute
    cfg = load_config()
    bars = _bars(400)
    ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)

    def boom(evt, bars_):
        raise RuntimeError("hook exploded")

    alpha = SupplyDemandAlpha(cfg, htf_align="D1", near_miss_hook=boom)
    for i in range(50, 400):
        alpha.signal(actx, i)  # must not raise


# ----------------------------------------------------------------------
# (b) zero-behaviour-change regression guard
# ----------------------------------------------------------------------

def test_trading_output_identical_with_and_without_recorder():
    cfg = load_config()
    bars = _bars(600)

    def fingerprint(trades):
        return [
            (t.entry_time, t.direction, round(t.entry_price, 6),
             round(t.stop_price, 6), round(t.tp_price, 6),
             t.exit_time, round(t.pnl, 6))
            for t in trades
        ]

    captured: list[dict] = []
    bare = run_alpha(
        SupplyDemandAlpha(cfg, htf_align="D1", htf_align_mode="against"),
        bars, cfg, start_index=50)
    hooked = run_alpha(
        SupplyDemandAlpha(
            cfg, htf_align="D1", htf_align_mode="against",
            near_miss_hook=lambda evt, bars_: captured.append(evt)),
        bars, cfg, start_index=50)

    assert fingerprint(bare) == fingerprint(hooked)
    # The recorder really observed (otherwise the guard proves nothing).
    assert captured, "expected the hook to capture at least one near-miss"


# ----------------------------------------------------------------------
# (c) recorder writes valid JSONL (+ snapshot)
# ----------------------------------------------------------------------

def test_vault_recorder_writes_valid_jsonl_and_png(tmp_path):
    vault = VaultRecorder("EURUSD", root=tmp_path)
    bars = _bars(120)
    event = {
        "ts": bars[100].time.isoformat(),
        "tf": "H1",
        "reason": "htf_gate",
        "direction": "long",
        "entry": 1.1000,
        "stop": 1.0950,
        "take_profit": 1.1100,
        "conviction": 0.65,
        "zone": {"direction": "long", "top": 1.1010, "bottom": 1.0990},
    }
    vault.record_near_miss(event, bars)

    jsonl = tmp_path / "EURUSD" / "near_misses" / "events.jsonl"
    assert jsonl.exists()
    lines = jsonl.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["symbol"] == "EURUSD"
    assert rec["reason"] == "htf_gate"
    assert rec["resolved"] is False
    assert rec["entry"] == pytest.approx(1.1000)

    pngs = list((tmp_path / "EURUSD" / "near_misses").glob("*.png"))
    assert len(pngs) == 1 and pngs[0].stat().st_size > 0
    assert "htf_gate" in pngs[0].name


def test_vault_recorder_loss_event(tmp_path):
    vault = VaultRecorder("GBPUSD", root=tmp_path)
    bars = _bars(120)
    vault.record_loss({
        "ts": bars[110].time.isoformat(),
        "tf": "H1",
        "ticket": 42,
        "direction": "short",
        "entry_time": bars[80].time.isoformat(),
        "entry": 1.1030,
        "exit_time": bars[110].time.isoformat(),
        "exit_price": 1.1070,
        "stop": 1.1070,
        "take_profit": 1.0970,
        "pnl": -40.0,
        "pnl_pips": -40.0,
        "r_multiple": -1.0,
        "exit_reason": "sl",
    }, bars)

    jsonl = tmp_path / "GBPUSD" / "losses" / "events.jsonl"
    assert jsonl.exists()
    rec = json.loads(jsonl.read_text().strip())
    assert rec["ticket"] == 42 and rec["pnl"] == -40.0
    pngs = list((tmp_path / "GBPUSD" / "losses").glob("*.png"))
    assert len(pngs) == 1 and pngs[0].stat().st_size > 0


def test_vault_recorder_never_raises_on_bad_event(tmp_path):
    vault = VaultRecorder("EURUSD", root=tmp_path)
    vault.record_near_miss({"ts": object()}, None)  # unserialisable-ish
    vault.record_loss({}, None)  # minimal — must not raise


# ----------------------------------------------------------------------
# SignalLoop downstream rejection seam
# ----------------------------------------------------------------------

class _FakeBroker:
    async def get_account_info(self):
        return SimpleNamespace(balance=10_000.0, leverage=500,
                               free_margin=10_000.0)

    async def get_open_positions(self, symbol):
        return []


def test_signal_loop_records_post_loss_guard_near_miss(tmp_path):
    cfg = load_config()
    live = LiveConfig(symbol="EURUSD", timeframes=["H4"],
                      telegram_enabled=False, revenge_guard_enabled=True)
    vault = VaultRecorder("EURUSD", root=tmp_path)
    loop = SignalLoop(
        [SupplyDemandAlpha(cfg, name="zone_h4_all")],
        config=cfg, live_config=live, broker=_FakeBroker(), vault=vault,
    )
    loop.post_loss_guard.pre_trade_check = lambda **kw: SimpleNamespace(
        allowed=False, reason="cooldown")

    signal = AlphaSignal(direction=Direction.LONG, entry=1.1000,
                         stop=1.0950, take_profit=1.1100, conviction=0.8)
    last_closed = SimpleNamespace(
        time=datetime(2026, 6, 10, tzinfo=timezone.utc))
    routed = _RoutedSignal(loop.alphas[0], signal, "H4")
    asyncio.run(loop._route_signal(routed, last_closed, bars=None))

    jsonl = tmp_path / "EURUSD" / "near_misses" / "events.jsonl"
    assert jsonl.exists()
    rec = json.loads(jsonl.read_text().strip())
    assert rec["reason"] == "post_loss_guard"
    assert rec["alpha"] == "zone_h4_all"
    assert rec["direction"] == "long"
    assert rec["detail"] == "cooldown"


class _RejectingBroker:
    """FakeBroker whose place_order always reports failure — models the
    Jun 11 retcode=10027 / 'AutoTrading disabled by client' incident."""

    def __init__(self, message: str = "retcode=10027 'AutoTrading disabled by client'"):
        self.message = message

    async def get_account_info(self):
        return SimpleNamespace(balance=10_000.0, leverage=500,
                               free_margin=10_000.0)

    async def get_open_positions(self, symbol):
        return []

    async def place_order(self, **kwargs):
        from agent.live.broker import OrderResult
        return OrderResult(success=False, message=self.message)


def test_signal_loop_records_broker_reject_near_miss(tmp_path):
    """A broker rejection (autotrading-off, no margin, retcode 10027, …)
    must vault a ``reason=broker_reject`` event so the rejected setup is
    visible to the near-miss resolver instead of silently disappearing."""
    cfg = load_config()
    live = LiveConfig(symbol="USDCAD", timeframes=["H4"],
                      telegram_enabled=False, revenge_guard_enabled=False)
    vault = VaultRecorder("USDCAD", root=tmp_path)
    loop = SignalLoop(
        [SupplyDemandAlpha(cfg, name="zone_h4_all")],
        config=cfg, live_config=live, broker=_RejectingBroker(), vault=vault,
    )

    signal = AlphaSignal(
        direction=Direction.SHORT, entry=1.39585,
        stop=1.39977, take_profit=1.39020, conviction=0.65,
        meta={"htf_bias": "up", "htf_align": "D1",
              "htf_align_mode": "against"},
    )
    last_closed = SimpleNamespace(
        time=datetime(2026, 6, 11, 20, 0, tzinfo=timezone.utc))
    routed = _RoutedSignal(loop.alphas[0], signal, "H4")
    asyncio.run(loop._route_signal(routed, last_closed, bars=None))

    jsonl = tmp_path / "USDCAD" / "near_misses" / "events.jsonl"
    assert jsonl.exists()
    rec = json.loads(jsonl.read_text().strip())
    assert rec["reason"] == "broker_reject"
    assert rec["alpha"] == "zone_h4_all"
    assert rec["direction"] == "short"
    assert "retcode=10027" in rec["detail"]
    # Decision metadata carries through so the resolver can group rejects
    # by HTF regime later.
    assert rec["htf_bias"] == "up"
    assert rec["htf_align"] == "D1"
    assert rec["htf_align_mode"] == "against"


def test_signal_loop_without_vault_unchanged(tmp_path):
    """vault=None (every existing caller/test) leaves the seam dormant."""
    cfg = load_config()
    live = LiveConfig(symbol="EURUSD", timeframes=["H4"],
                      telegram_enabled=False, revenge_guard_enabled=True)
    loop = SignalLoop([SupplyDemandAlpha(cfg, name="zone_h4_all")],
                      config=cfg, live_config=live, broker=_FakeBroker())
    assert loop.vault is None
    loop.post_loss_guard.pre_trade_check = lambda **kw: SimpleNamespace(
        allowed=False, reason="cooldown")
    signal = AlphaSignal(direction=Direction.LONG, entry=1.1000,
                         stop=1.0950, take_profit=1.1100, conviction=0.8)
    last_closed = SimpleNamespace(
        time=datetime(2026, 6, 10, tzinfo=timezone.utc))
    asyncio.run(loop._route_signal(
        _RoutedSignal(loop.alphas[0], signal, "H4"), last_closed))


# ----------------------------------------------------------------------
# (d) resolver scoring
# ----------------------------------------------------------------------

def _near_miss(direction="long", entry=1.1000, stop=1.0950, tp=1.1100,
               event_idx=5) -> dict:
    return {
        "ts": (T0 + timedelta(hours=4 * event_idx)).isoformat(),
        "tf": "H4",
        "reason": "htf_gate",
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "take_profit": tp,
        "resolved": False,
    }


def test_resolver_scores_tp_hit_as_win():
    bars = [_flat_bar(i, 1.1000) for i in range(10)]
    bars.append(_flat_bar(10, 1.1000, high=1.1105))  # TP touched, SL never
    bars.extend(_flat_bar(i, 1.1000) for i in range(11, 14))

    out = resolve_event(_near_miss(), bars)
    assert out["outcome"] == "win"
    assert out["resolved"] is True
    assert out["outcome_pips"] == pytest.approx(100.0)
    assert out["outcome_r"] == pytest.approx(2.0)  # 100p / 50p stop
    assert out["bars_to_outcome"] == 5


def test_resolver_scores_sl_hit_as_loss():
    bars = [_flat_bar(i, 1.1000) for i in range(8)]
    bars.append(_flat_bar(8, 1.0960, low=1.0945))  # SL touched first
    bars.append(_flat_bar(9, 1.1000, high=1.1105))  # TP later — too late

    out = resolve_event(_near_miss(), bars)
    assert out["outcome"] == "loss"
    assert out["outcome_pips"] == pytest.approx(-50.0)
    assert out["outcome_r"] == pytest.approx(-1.0)


def test_resolver_same_bar_counts_as_sl_conservative():
    bars = [_flat_bar(i, 1.1000) for i in range(7)]
    # One giant bar spans BOTH the stop and the target.
    bars.append(_flat_bar(7, 1.1000, low=1.0940, high=1.1110))

    out = resolve_event(_near_miss(), bars)
    assert out["outcome"] == "loss"


def test_resolver_short_direction_mirrors():
    evt = _near_miss(direction="short", entry=1.1000, stop=1.1050, tp=1.0900)
    bars = [_flat_bar(i, 1.1000) for i in range(9)]
    bars.append(_flat_bar(9, 1.0950, low=1.0895))  # short TP touched
    out = resolve_event(evt, bars)
    assert out["outcome"] == "win"
    assert out["outcome_r"] == pytest.approx(2.0)


def test_resolver_leaves_unhit_event_open():
    bars = [_flat_bar(i, 1.1000) for i in range(12)]  # never reaches either
    out = resolve_event(_near_miss(), bars)
    assert out["outcome"] == "open"
    assert out["resolved"] is False
    assert out["outcome_r"] == 0.0
    # Forward window was real (7 bars after event); not a stale-cache miss.
    assert out["forward_bars_available"] == 6


def test_resolver_reports_forward_bars_available_when_cache_too_short():
    """An event at the very end of the cache leaves zero forward bars —
    that's a stale-cache signal, distinct from 'still pending'."""
    bars = [_flat_bar(i, 1.1000) for i in range(6)]  # event at idx 5 = last
    out = resolve_event(_near_miss(event_idx=5), bars)
    assert out["outcome"] == "open"
    assert out["forward_bars_available"] == 0


def test_summary_counts_stale_separately_from_open():
    """Stale = unresolved with < 6 forward H4 bars (~1 day). The summary
    row exposes it so the script can warn the operator about a stale
    parquet cache before they read 'all open' as 'edge absent'."""
    stale = _near_miss()
    stale.update({"outcome": "open", "resolved": False,
                  "forward_bars_available": 1})
    pending = _near_miss()
    pending.update({"outcome": "open", "resolved": False,
                    "forward_bars_available": 50})
    win = _near_miss()
    win.update({"outcome": "win", "outcome_r": 2.0, "resolved": True,
                "forward_bars_available": 8})

    rows = summarize_by_reason([stale, pending, win])
    row = next(r for r in rows if r["reason"] == "htf_gate")
    assert row["n"] == 3
    assert row["wins"] == 1
    assert row["losses"] == 0
    assert row["open"] == 2
    assert row["stale"] == 1  # only the 1-forward-bar event counts as stale


def test_resolver_roundtrip_and_summary(tmp_path):
    path = tmp_path / "events.jsonl"
    win = _near_miss()
    win.update({"outcome": "win", "outcome_r": 2.0, "resolved": True})
    loss = _near_miss()
    loss.update({"outcome": "loss", "outcome_r": -1.0, "resolved": True,
                 "reason": "sizing_skip"})
    write_events(path, [win, loss])

    events = load_events(path)
    assert len(events) == 2
    rows = summarize_by_reason(events)
    by_reason = {r["reason"]: r for r in rows}
    assert by_reason["htf_gate"]["wins"] == 1
    assert by_reason["htf_gate"]["win_rate"] == 1.0
    assert by_reason["htf_gate"]["avg_r"] == pytest.approx(2.0)
    assert by_reason["sizing_skip"]["losses"] == 1
    assert by_reason["sizing_skip"]["avg_r"] == pytest.approx(-1.0)


# ----------------------------------------------------------------------
# (e) chart renderer smoke
# ----------------------------------------------------------------------

def test_render_snapshot_produces_png(tmp_path):
    bars = _bars(120)
    out = render_snapshot(
        bars, tmp_path / "snap.png",
        title="EURUSD H1 — htf_gate test",
        event_time=bars[100].time,
        entry=1.1000, stop=1.0950, take_profit=1.1100,
        zone_top=1.1010, zone_bottom=1.0990,
    )
    assert out is not None
    assert out.exists() and out.stat().st_size > 0


def test_render_snapshot_failure_returns_none(tmp_path):
    assert render_snapshot([], tmp_path / "x.png", title="empty") is None
    one = _bars(1)
    assert render_snapshot(one, tmp_path / "y.png", title="one bar") is None


def test_render_snapshot_annotates_levels_reason_and_caption(tmp_path,
                                                             monkeypatch):
    """The new vault chart contract: every render must (a) carry the reason
    + direction in the title, (b) draw a horizontal line per level, (c)
    annotate each level's price next to the right edge, and (d) print the
    rejection detail caption in the bottom-right.

    We intercept ``mpf.plot`` to grab the figure before save, then assert on
    the matplotlib objects directly — no PNG pixel-peeping required.
    """
    import agent.journal.chart_snapshot as cs
    real_plot = cs.mpf.plot
    captured: dict = {}

    def spy(df, **kwargs):
        fig, axes = real_plot(df, **kwargs)
        captured["fig"] = fig
        captured["axes"] = axes
        captured["kwargs"] = kwargs
        return fig, axes

    monkeypatch.setattr(cs.mpf, "plot", spy)
    bars = _bars(120)
    out = cs.render_snapshot(
        bars, tmp_path / "snap.png",
        title="EURUSD H1 — htf_gate",
        event_time=bars[100].time,
        entry=1.1000, stop=1.0950, take_profit=1.1100,
        zone_top=1.1010, zone_bottom=1.0990, zone_direction="short",
        reason="htf_gate", direction="long",
        detail="htf_bias=up · htf=D1(against) · conviction=0.65",
    )
    assert out is not None
    fig = captured["fig"]
    kwargs = captured["kwargs"]
    # (a) title carries reason + direction
    assert "htf_gate" in kwargs["title"]
    assert "LONG" in kwargs["title"]
    # (b) one horizontal line per supplied level
    hlines_block = kwargs.get("hlines") or {}
    levels = list(hlines_block.get("hlines", []))
    assert pytest.approx(1.1000) in levels
    assert pytest.approx(1.0950) in levels
    assert pytest.approx(1.1100) in levels
    # (c) right-edge annotations for entry / SL / TP
    price_ax = captured["axes"][0]
    label_texts = [t.get_text() for t in price_ax.texts]
    assert any("entry" in t and "1.10000" in t for t in label_texts)
    assert any("SL" in t and "1.09500" in t for t in label_texts)
    assert any("TP" in t and "1.11000" in t for t in label_texts)
    # (d) detail caption present
    assert any("htf_bias=up" in t for t in label_texts)


def test_render_snapshot_zone_colours_by_direction(tmp_path, monkeypatch):
    """Demand zones (long) render green; supply zones (short) render red."""
    import agent.journal.chart_snapshot as cs
    real_plot = cs.mpf.plot
    captured: dict = {}

    def spy(df, **kwargs):
        captured["kwargs"] = kwargs
        return real_plot(df, **kwargs)

    monkeypatch.setattr(cs.mpf, "plot", spy)
    bars = _bars(120)
    cs.render_snapshot(bars, tmp_path / "demand.png", title="t",
                       zone_top=1.1010, zone_bottom=1.0990,
                       zone_direction="long")
    demand_color = captured["kwargs"]["fill_between"]["color"]
    cs.render_snapshot(bars, tmp_path / "supply.png", title="t",
                       zone_top=1.1010, zone_bottom=1.0990,
                       zone_direction="short")
    supply_color = captured["kwargs"]["fill_between"]["color"]
    assert demand_color != supply_color
    assert demand_color.lower().startswith("#43")  # green palette
    assert supply_color.lower().startswith("#e5")  # red palette


def test_vault_near_miss_render_includes_reason_and_detail(tmp_path,
                                                          monkeypatch):
    """End-to-end: vault.record_near_miss → chart_snapshot.render_snapshot
    must propagate reason / direction / htf detail."""
    import agent.journal.chart_snapshot as cs

    seen: dict = {}

    def spy(bars, out_path, **kwargs):
        seen.update(kwargs)
        # Still write a placeholder file so the vault path doesn't break
        # downstream assertions on PNG existence.
        from pathlib import Path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"")
        return Path(out_path)

    # Patch the *bound name* used by VaultRecorder (it imported the symbol).
    monkeypatch.setattr("agent.journal.vault.render_snapshot", spy)

    vault = VaultRecorder("EURUSD", root=tmp_path)
    bars = _bars(120)
    vault.record_near_miss({
        "ts": bars[100].time.isoformat(),
        "tf": "H4",
        "reason": "htf_gate",
        "direction": "long",
        "entry": 1.1000, "stop": 1.0950, "take_profit": 1.1100,
        "conviction": 0.65,
        "htf_bias": "up", "htf_align": "D1", "htf_align_mode": "against",
        "zone": {"direction": "long", "top": 1.1010, "bottom": 1.0990},
    }, bars)
    assert seen["reason"] == "htf_gate"
    assert seen["direction"] == "long"
    assert seen["zone_direction"] == "long"
    assert "htf_bias=up" in seen["detail"]
    assert "D1" in seen["detail"]
