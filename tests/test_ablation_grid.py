"""Ablation grid: isolation, session bucketing, BH wiring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


from agent.alphas.base import Alpha, AlphaContext, AlphaSignal
from agent.alphas.grid import (
    ALL_SESSIONS,
    AblationCell,
    _filter_by_session,
    run_cell,
    run_grid,
)
from agent.config import load_config
from agent.detectors.sessions import label_session
from agent.types import Bar, Direction, Setup, Timeframe, Trade


def _bars(n: int = 400, start: float = 1.1000, step: float = 0.0004) -> list[Bar]:
    """Synthetic H1 zig-zag with at least 2-3 days of coverage so every session
    bucket gets some bars."""
    out = []
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        drift = step * (1 if (i // 24) % 2 == 0 else -1)
        o = price
        c = price + drift
        h = max(o, c) + step
        l = min(o, c) - step
        out.append(Bar(time=t0 + timedelta(hours=i), open=o, high=h, low=l,
                       close=c, volume=100.0, timeframe=Timeframe.H1))
        price = c
    return out


class _AlwaysLong(Alpha):
    name = "always_long"

    def __init__(self, cfg=None):
        self.cfg = cfg

    def signal(self, actx: AlphaContext, i: int):
        b = actx.bars[i]
        return AlphaSignal(
            direction=Direction.LONG, entry=b.close,
            stop=b.close - 0.0020, take_profit=b.close + 0.0030, reason="t",
        )


def _trade_at(hour_utc: int, day: int = 0) -> Trade:
    t = datetime(2024, 6, 3, hour_utc, 0, tzinfo=timezone.utc) + timedelta(days=day)
    setup = Setup(direction=Direction.LONG, timeframe=Timeframe.H1, detected_at=t,
                  detected_bar_index=0, entry=1.1, stop=1.099, take_profit=1.102)
    return Trade(setup=setup, direction=Direction.LONG, entry_time=t,
                 entry_price=1.1, stop_price=1.099, tp_price=1.102, lot_size=0.1,
                 exit_time=t + timedelta(hours=1), exit_price=1.101,
                 exit_reason="tp", pnl=1.0, pnl_pips=10.0)


# --- session filter ---------------------------------------------------------

def test_filter_all_keeps_every_closed_trade():
    trades = [_trade_at(h) for h in range(0, 24)]
    out = _filter_by_session(trades, "all")
    assert len(out) == len(trades)


def test_filter_by_specific_session_only_keeps_matching_entries():
    trades = [_trade_at(h) for h in range(0, 24)]
    for sess in ("london", "ny", "asia", "london_ny_overlap"):
        kept = _filter_by_session(trades, sess)
        # Every kept trade's entry must label to the requested session.
        for t in kept:
            assert label_session(t.entry_time) == sess


def test_filter_drops_open_trades():
    t = _trade_at(9)
    t.exit_time = None
    assert _filter_by_session([t], "all") == []


# --- isolation --------------------------------------------------------------

def test_run_cell_uses_a_fresh_alpha_factory_per_call():
    """Two cells calling the same factory must each get their *own* instance —
    if the factory returned a shared object, internal state could leak."""
    seen = []

    class _Counter(Alpha):
        name = "counter"

        def __init__(self, cfg=None):
            self.cfg = cfg
            self.calls = 0
            seen.append(self)

        def signal(self, actx, i):
            self.calls += 1
            return None

    cfg = load_config()
    bars = _bars(120)
    cell = AblationCell(alpha_name="counter", timeframe="H1",
                        session="all", alpha_factory=lambda c: _Counter(c))
    run_cell(cell, bars, cfg, start_index=10, n_resamples=50)
    run_cell(cell, bars, cfg, start_index=10, n_resamples=50)
    assert len(seen) == 2
    assert seen[0] is not seen[1]


def test_run_cell_does_not_share_precomputed_context_across_cells():
    """The grid's isolation contract: two cells must not see each other's
    mutations on detector outputs. We keep a strong reference to the first
    context (so Python's allocator can't reuse its address) and verify the
    second context is a distinct object."""
    captured: list = []

    class _Recorder(Alpha):
        name = "recorder"

        def __init__(self, cfg=None):
            self.cfg = cfg

        def signal(self, actx, i):
            captured.append(actx.ctx)
            return None

    cfg = load_config()
    bars = _bars(200)
    cell = AblationCell(alpha_name="recorder", timeframe="H1",
                        session="all", alpha_factory=lambda c: _Recorder(c))
    run_cell(cell, bars, cfg, start_index=20, n_resamples=50)
    first_ctx = captured[-1]  # holds a strong reference past the run
    run_cell(cell, bars, cfg, start_index=20, n_resamples=50)
    second_ctx = captured[-1]
    assert first_ctx is not second_ctx, (
        "Two cells received the same PrecomputedContext object — "
        "the isolation contract is broken (shared mutable detector state)."
    )
    # And the underlying detector lists must not be the same Python list either.
    assert first_ctx.zones is not second_ctx.zones
    assert first_ctx.fvgs is not second_ctx.fvgs


def test_run_grid_memoizes_precompute_across_alpha_variants_on_same_tf():
    """``run_grid`` must call ``precompute`` once per TF, not once per
    (alpha, TF) group. Otherwise running N alpha variants on H1 pays the
    detector cost N times for zero extra information.

    We assert the contract by stashing a unique tag on the first ctx the
    recorder sees, then checking the second alpha-group on the same TF sees
    the *same* tag — proving the same ctx object was reused."""
    seen: list = []

    class _Recorder(Alpha):
        name = "recorder"

        def __init__(self, cfg=None, *, tag=""):
            self.cfg = cfg
            self.tag = tag

        def signal(self, actx, i):
            seen.append((self.tag, actx.ctx))
            return None

    cfg = load_config()
    bars = _bars(200)
    cells = [
        AblationCell(alpha_name=f"rec_{t}", timeframe="H1", session="all",
                     alpha_factory=lambda c, t=t: _Recorder(c, tag=t))
        for t in ("A", "B")
    ]
    run_grid(cells, {"H1": bars}, cfg, n_resamples=10, start_index=20)
    tag_to_ctx = {t: ctx for t, ctx in seen}
    assert tag_to_ctx["A"] is tag_to_ctx["B"], (
        "run_grid called precompute twice for the same TF — caching is "
        "broken and detector work is being duplicated."
    )


# --- end-to-end -------------------------------------------------------------

def test_run_grid_produces_one_result_per_cell_and_fills_q_values():
    cfg = load_config()
    bars = _bars(400)
    cells = [
        AblationCell(alpha_name="always_long", timeframe="H1",
                     session=s, alpha_factory=lambda c: _AlwaysLong(c))
        for s in ("all", "london", "ny")
    ]
    grid = run_grid(cells, {"H1": bars}, cfg, n_resamples=100)
    assert len(grid.cells) == 3
    for r in grid.cells:
        assert 0.0 <= r.p_value <= 1.0
        assert 0.0 <= r.q_value <= 1.0
        assert isinstance(r.rejected, bool)


def test_run_grid_skips_missing_timeframe_gracefully():
    cfg = load_config()
    bars = _bars(200)
    cells = [
        AblationCell(alpha_name="always_long", timeframe="H1",
                     session="all", alpha_factory=lambda c: _AlwaysLong(c)),
        AblationCell(alpha_name="always_long", timeframe="D1",  # not in map
                     session="all", alpha_factory=lambda c: _AlwaysLong(c)),
    ]
    grid = run_grid(cells, {"H1": bars}, cfg, n_resamples=50)
    assert len(grid.cells) == 2
    assert grid.cells[1].scorecard.n_trades == 0


def test_all_sessions_constant_matches_session_label_buckets():
    assert "all" in ALL_SESSIONS
    for sess in ALL_SESSIONS:
        assert sess in ("all", "london", "london_ny_overlap", "ny", "asia")
