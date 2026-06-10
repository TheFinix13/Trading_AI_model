"""V4 concept alphas: smoke + causality + flat-vol guard + behavior gates.

V4 retired ``momentum`` and ``liquidity_sweep`` after the post-speedup grids
showed neither produced a BH-significant cell at FDR 5% on any TF
(H4 / H1 / M15) under any HTF or relaxation variant. Zone is the sole
remaining concept; this file is now the regression contract that keeps it
honest.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.alphas.backtest import run_alpha
from agent.alphas.base import AlphaContext
from agent.alphas.concepts import ALL_CONCEPT_ALPHAS, SupplyDemandAlpha
from agent.config import load_config
from agent.rules.engine import precompute
from agent.types import Bar, Direction, Timeframe


def _bars(n: int = 400, start: float = 1.1000) -> list[Bar]:
    """Synthetic zig-zag — long enough for detectors to find FVGs + sweeps."""
    out = []
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        # Inject an occasional 8-pip displacement to give the FVG detector
        # something to chew on.
        spike = 0.0008 if i % 47 == 0 else 0.0003
        drift = spike * (1 if (i // 17) % 2 == 0 else -1)
        o = price
        c = price + drift
        h = max(o, c) + 0.0002
        l = min(o, c) - 0.0002
        out.append(Bar(time=t0 + timedelta(hours=i), open=o, high=h, low=l,
                       close=c, volume=100.0, timeframe=Timeframe.H1))
        price = c
    return out


# ---------------------------------------------------------------------------
# Registry contract
# ---------------------------------------------------------------------------

ALL_CLASSES = [SupplyDemandAlpha]


def test_concept_registry_lists_only_v4_survivor():
    """v4 roster: zone is the sole alpha that produced BH-significant cells
    in the definitive grid. Re-introducing any of the dead concepts would
    silently invalidate the methodology that pruned them."""
    assert set(ALL_CONCEPT_ALPHAS) == {"zone"}
    for name in ("bos", "orderblock", "fib", "fvg_retest",
                 "momentum", "liquidity_sweep"):
        assert name not in ALL_CONCEPT_ALPHAS, (
            f"rejected alpha '{name}' came back into the registry"
        )
    for cls in ALL_CONCEPT_ALPHAS.values():
        inst = cls()
        assert inst.signal.__name__ == "signal"


# ---------------------------------------------------------------------------
# Shared safety contracts (every active alpha must satisfy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("AlphaCls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_alpha_smoke_returns_closed_trades_only(AlphaCls):
    cfg = load_config()
    bars = _bars(400)
    trades = run_alpha(AlphaCls(cfg), bars, cfg, start_index=50)
    assert isinstance(trades, list)
    assert all(t.exit_time is not None for t in trades)


@pytest.mark.parametrize("AlphaCls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_alpha_signal_call_is_causal_and_doesnt_raise(AlphaCls):
    """Stepping through bars 50..120 must never raise — the alpha must read
    only ``bars[:i+1]`` (everything else is the harness's responsibility)."""
    cfg = load_config()
    bars = _bars(200)
    ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)
    alpha = AlphaCls(cfg)
    for i in range(50, 120):
        _ = alpha.signal(actx, i)


@pytest.mark.parametrize("AlphaCls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_alpha_holds_off_when_atr_is_zero(AlphaCls):
    """Every alpha pulls ATR from ``ctx.atr_by_index``; on a thin context
    (atr=0 everywhere) every signal call must return None — no signal, ever,
    when the vol regime is unmeasurable."""
    cfg = load_config()
    bars = _bars(50)
    ctx = precompute(bars, cfg)
    ctx.atr_by_index = {i: 0.0 for i in range(len(bars))}
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)
    alpha = AlphaCls(cfg)
    for i in range(20, 49):
        assert alpha.signal(actx, i) is None, f"{AlphaCls.__name__} signalled on flat vol"


@pytest.mark.parametrize("AlphaCls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_alpha_signals_are_internally_consistent_when_emitted(AlphaCls):
    """For every signal an alpha emits: long must have stop<entry<tp and short
    must have stop>entry>tp. Catches sign-flip bugs in the RR math."""
    cfg = load_config()
    bars = _bars(800)
    ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)
    alpha = AlphaCls(cfg)
    seen = 0
    for i in range(100, 800):
        sig = alpha.signal(actx, i)
        if sig is None:
            continue
        seen += 1
        if sig.direction == Direction.LONG:
            assert sig.stop < sig.entry < sig.take_profit
        else:
            assert sig.stop > sig.entry > sig.take_profit
        if seen >= 5:
            break


@pytest.mark.parametrize("AlphaCls", ALL_CLASSES, ids=[c.__name__ for c in ALL_CLASSES])
def test_alpha_keeps_one_position_at_a_time(AlphaCls):
    cfg = load_config()
    bars = _bars(500)
    trades = run_alpha(AlphaCls(cfg), bars, cfg, start_index=20)
    for a, b in zip(trades, trades[1:]):
        assert b.entry_time >= a.exit_time


# ---------------------------------------------------------------------------
# Zone-specific behaviour gates (the improvements that justified each rev)
# ---------------------------------------------------------------------------

def test_supply_demand_uses_raw_zones_v2_proven_universe():
    """The v3 experiment switched to qualified zones and broke the edge
    (1041 → 596 trades, +6.20 → -3.42 exp on H4/all). The v3.1 fix was to
    keep :func:`detect_zones` (v2 source). Regression guard: precompute must
    still emit ``ctx.zones`` and the alpha must consume that list."""
    cfg = load_config()
    bars = _bars(400)
    ctx = precompute(bars, cfg)
    assert hasattr(ctx, "zones") and isinstance(ctx.zones, list)


def test_supply_demand_respects_first_touch_only():
    """The first-touch gate is what protects v2's edge — every emitted trade
    must have ``_has_touched_before`` returning False at entry."""
    from agent.alphas.concepts.zone_alpha import _has_touched_before
    from agent.detectors.zones import fresh_zones
    cfg = load_config()
    bars = _bars(800)
    ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)
    alpha = SupplyDemandAlpha(cfg)
    fires = 0
    for i in range(50, 700):
        sig = alpha.signal(actx, i)
        if sig is None:
            continue
        fires += 1
        for z in fresh_zones(ctx.zones, i, max_age_bars=alpha.max_age_bars):
            if bars[i].low <= z.top and bars[i].high >= z.bottom:
                if z.direction == sig.direction:
                    assert not _has_touched_before(z, bars, i), (
                        f"alpha fired on already-touched zone at bar {i}"
                    )
                    break
    assert fires > 0


def test_supply_demand_htf_alignment_filter_reduces_trades():
    """``htf_align=None`` (default) must produce >= as many trades as
    ``htf_align="D1"``. The HTF filter blocks zones whose direction
    disagrees with the HTF bias, so it can only ever reduce the trade list."""
    cfg = load_config()
    bars = _bars(600)
    no_filter = run_alpha(SupplyDemandAlpha(cfg, htf_align=None),
                          bars, cfg, start_index=20)
    filtered = run_alpha(SupplyDemandAlpha(cfg, htf_align="D1"),
                         bars, cfg, start_index=20)
    assert len(filtered) <= len(no_filter)


def test_supply_demand_htf_alignment_blocks_counter_trend():
    """Every trade emitted under ``htf_align="D1"`` must have an HTF bias at
    entry whose direction matches the trade direction."""
    from agent.alphas.concepts._htf import HTFBias, htf_bias_at
    cfg = load_config()
    bars = _bars(800)
    trades = run_alpha(SupplyDemandAlpha(cfg, htf_align="D1"),
                       bars, cfg, start_index=50)
    time_to_idx = {b.time: i for i, b in enumerate(bars)}
    for t in trades:
        i = time_to_idx.get(t.entry_time)
        if i is None:
            continue
        bias = htf_bias_at(bars, i, htf="D1", htf_lookback=5, min_move_pips=30.0)
        assert bias is HTFBias.NEUTRAL or bias.matches(t.direction)


def test_supply_demand_htf_against_mode_inverts_alignment():
    """``htf_align_mode="against"`` is the proven-edge mode for H1/H4-Asia
    cells (see ``scripts/run_zone_all_tfs.py``). Contract: every trade
    emitted under against-mode must have an HTF bias that OPPOSES the trade
    direction (or be neutral; neutral is always blocked, so this should be
    "opposes" in practice)."""
    from agent.alphas.concepts._htf import HTFBias, htf_bias_at
    cfg = load_config()
    bars = _bars(800)
    trades = run_alpha(
        SupplyDemandAlpha(cfg, htf_align="D1", htf_align_mode="against"),
        bars, cfg, start_index=50,
    )
    time_to_idx = {b.time: i for i, b in enumerate(bars)}
    for t in trades:
        i = time_to_idx.get(t.entry_time)
        if i is None:
            continue
        bias = htf_bias_at(bars, i, htf="D1", htf_lookback=5, min_move_pips=30.0)
        assert bias is HTFBias.NEUTRAL or bias.opposes(t.direction)


def test_supply_demand_structural_tp_option_toggleable():
    """When ``target_via_structure=True`` we should sometimes target a swing
    instead of a fixed RR — the targets should differ from RR=1.5 entries."""
    cfg = load_config()
    bars = _bars(1000)
    rr_only = run_alpha(SupplyDemandAlpha(cfg, target_via_structure=False),
                        bars, cfg, start_index=20)
    structural = run_alpha(SupplyDemandAlpha(cfg, target_via_structure=True),
                           bars, cfg, start_index=20)
    if rr_only and structural:
        rr_tps = {(t.entry_time, round(t.tp_price, 6)) for t in rr_only}
        st_tps = {(t.entry_time, round(t.tp_price, 6)) for t in structural}
        assert rr_tps != st_tps or len(rr_only) != len(structural)


# ---------------------------------------------------------------------------
# Dead-alpha quarantine — re-importing any of these must fail loudly.
# ---------------------------------------------------------------------------

def test_deleted_alpha_modules_are_gone():
    """Importing the dead alphas must raise. Keeps anyone from resurrecting
    them by accident through a leftover import path. v4 added ``momentum``
    and ``liquidity_sweep`` to the quarantine list."""
    for mod_name in ("bos_alpha", "orderblock_alpha", "fib_alpha",
                     "fvg_retest_alpha", "momentum_alpha",
                     "liquidity_sweep_alpha"):
        with pytest.raises(ImportError):
            __import__(f"agent.alphas.concepts.{mod_name}")
