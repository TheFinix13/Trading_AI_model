"""Isolated, identical fill model for measuring a single alpha (docs/10 §10.4).

Every alpha is run through *this same* simulator so their scorecards are
comparable: one position at a time, entry on the next bar's open with
spread+slippage, intra-bar SL/TP (worst-case = SL when a bar straddles both),
fixed lot. No gates, no ML, no BE migration — we measure the alpha's *raw*
signal edge, not the rule-engine's gated behaviour.
"""
from __future__ import annotations

from agent.alphas.base import Alpha, AlphaContext
from agent.config import Config
from agent.rules.engine import precompute
from agent.types import Bar, Direction, Trade
from agent.utils import to_pips

FIXED_LOT = 0.1


class _CausalFVGTracker:
    """Rebuilds FVG fill state CAUSALLY as the backtest walks forward.

    `precompute` marks each FVG's fill_pct / is_fully_filled / revisit_count by
    scanning the whole series — which leaks the future into any fill-state filter
    applied at an earlier bar (see docs/10 §10.5). This tracker resets that state
    and re-derives it one bar at a time, so a strategy reading `ctx.fvgs` at bar i
    sees only what was knowable at bar i. Mutates the FVG objects in place; call
    `reset()` before reusing a shared context for another alpha."""

    def __init__(self, fvgs):
        self._fvgs = sorted(fvgs, key=lambda f: f.created_bar_index)
        self._maxpen: dict[int, float] = {}
        self._active: list = []
        self._ptr = 0
        self.reset()

    def reset(self) -> None:
        for f in self._fvgs:
            f.fill_pct = 0.0
            f.is_fully_filled = False
            f.filled = False
            f.filled_at = None
            f.revisit_count = 0
            self._maxpen[id(f)] = 0.0
        self._active = []
        self._ptr = 0

    def advance_to(self, i: int, bars: list[Bar]) -> None:
        while self._ptr < len(self._fvgs) and self._fvgs[self._ptr].created_bar_index < i:
            self._active.append(self._fvgs[self._ptr])
            self._ptr += 1
        if not self._active:
            return
        b = bars[i]
        still = []
        for f in self._active:
            rng = f.top - f.bottom
            if rng <= 0:
                continue
            mp = self._maxpen[id(f)]
            if f.direction == Direction.LONG:
                if b.low <= f.top:
                    pen = f.top - max(b.low, f.bottom)
                    if pen > 0:
                        if mp == 0.0 or b.low < (f.top - mp):
                            f.revisit_count += 1
                        mp = max(mp, pen)
                    if b.low <= f.bottom:
                        f.filled = True
                        f.filled_at = b.time
                        f.is_fully_filled = True
                        f.fill_pct = 1.0
                        self._maxpen[id(f)] = mp
                        continue
            else:
                if b.high >= f.bottom:
                    pen = min(b.high, f.top) - f.bottom
                    if pen > 0:
                        if mp == 0.0 or b.high > (f.bottom + mp):
                            f.revisit_count += 1
                        mp = max(mp, pen)
                    if b.high >= f.top:
                        f.filled = True
                        f.filled_at = b.time
                        f.is_fully_filled = True
                        f.fill_pct = 1.0
                        self._maxpen[id(f)] = mp
                        continue
            self._maxpen[id(f)] = mp
            if mp > 0:
                f.fill_pct = min(1.0, mp / rng)
            still.append(f)
        self._active = still


def _open(signal, entry_bar: Bar, cfg: Config) -> Trade:
    """Market entry on the next bar's open. Stop/TP are RE-ANCHORED to the actual
    fill using the signal's own risk geometry (its stop distance and reward:risk).

    This is critical: an alpha may propose a limit entry *inside* a zone/FVG with
    stop/TP measured from that limit. If we filled at next-open but kept the
    limit-relative TP, a setup whose price had already run toward target would win
    almost for free — a look-ahead-like artifact, not edge. Re-anchoring to the
    fill makes every alpha pay the same honest risk for the same reward.

    Costs are pulled per-TF via :meth:`BacktestConfig.cost_for` so cells on M1
    don't get charged D1's spread."""
    spread_p, slip_p, commission = cfg.backtest.cost_for(entry_bar.timeframe.value)
    spread = spread_p * 0.0001
    slip = slip_p * 0.0001
    if signal.direction == Direction.LONG:
        fill = entry_bar.open + spread / 2 + slip
    else:
        fill = entry_bar.open - spread / 2 - slip

    stop_dist = abs(signal.entry - signal.stop)
    tp_dist = abs(signal.take_profit - signal.entry)
    if signal.direction == Direction.LONG:
        stop_price = fill - stop_dist
        tp_price = fill + tp_dist
    else:
        stop_price = fill + stop_dist
        tp_price = fill - tp_dist

    from agent.types import Setup

    setup = Setup(
        direction=signal.direction, timeframe=entry_bar.timeframe,
        detected_at=entry_bar.time, detected_bar_index=0,
        entry=fill, stop=stop_price, take_profit=tp_price,
    )
    return Trade(
        setup=setup, direction=signal.direction, entry_time=entry_bar.time,
        entry_price=fill, stop_price=stop_price, tp_price=tp_price,
        lot_size=FIXED_LOT, commission=FIXED_LOT * commission,
    )


def _check_exit(trade: Trade, bar: Bar, cfg: Config) -> bool:
    if trade.direction == Direction.LONG:
        hit_sl = bar.low <= trade.stop_price
        hit_tp = bar.high >= trade.tp_price
    else:
        hit_sl = bar.high >= trade.stop_price
        hit_tp = bar.low <= trade.tp_price
    if hit_sl:
        exit_price, reason = trade.stop_price, "sl"  # worst-case on straddle
    elif hit_tp:
        exit_price, reason = trade.tp_price, "tp"
    else:
        return False
    trade.exit_time = bar.time
    trade.exit_price = exit_price
    trade.exit_reason = reason
    pip = (to_pips(exit_price - trade.entry_price) if trade.direction == Direction.LONG
           else to_pips(trade.entry_price - exit_price))
    trade.pnl_pips = pip
    trade.pnl = pip * trade.lot_size * cfg.backtest.pip_value_per_lot - trade.commission
    return True


def run_alpha(
    alpha: Alpha,
    bars: list[Bar],
    cfg: Config,
    *,
    ctx=None,
    start_index: int = 0,
) -> list[Trade]:
    """Backtest one alpha in isolation. ``ctx`` (precomputed context) may be
    passed in to avoid recomputing it for every alpha over the same bars.
    ``start_index`` skips a warm-up region (detectors need history).

    Single SL/TP path only — the v1 *managed exit* (partial scale-out + BE
    runner) was burned in the v2 reset because per-alpha measurement is more
    honest with a fixed exit, and the Phase-C A/B had shipped default-off
    anyway.
    """
    if ctx is None:
        ctx = precompute(bars, cfg)
    actx = AlphaContext(bars=bars, ctx=ctx, cfg=cfg)

    # Re-derive FVG fill state causally so strategies can't see the future.
    fvg_tracker = _CausalFVGTracker(ctx.fvgs) if getattr(ctx, "fvgs", None) else None

    trades: list[Trade] = []
    open_trade: Trade | None = None

    for i, bar in enumerate(bars):
        if fvg_tracker is not None:
            fvg_tracker.advance_to(i, bars)

        if open_trade is not None:
            if _check_exit(open_trade, bar, cfg):
                trades.append(open_trade)
                open_trade = None
        if open_trade is None and start_index <= i < len(bars) - 1:
            sig = alpha.signal(actx, i)
            if sig is not None and sig.stop_pips > 0:
                open_trade = _open(sig, bars[i + 1], cfg)

    if open_trade is not None and open_trade.exit_time is None:
        last = bars[-1]
        open_trade.exit_time = last.time
        open_trade.exit_price = last.close
        open_trade.exit_reason = "end_of_data"
        pip = (to_pips(last.close - open_trade.entry_price)
               if open_trade.direction == Direction.LONG
               else to_pips(open_trade.entry_price - last.close))
        open_trade.pnl_pips = pip
        open_trade.pnl = pip * open_trade.lot_size * cfg.backtest.pip_value_per_lot - open_trade.commission
        trades.append(open_trade)

    return trades


def run_alpha_chunked(
    alpha: Alpha,
    bars: list[Bar],
    cfg: Config,
    *,
    chunk: int = 8000,
    warmup: int = 300,
    tail: int = 800,
    start_index: int = 300,
) -> list[Trade]:
    """Backtest one alpha over a long span without the O(N²) cost of a single
    giant `precompute`. The series is tiled into chunks, each precomputed with a
    ``warmup`` lead-in (so detectors have history) and a ``tail`` buffer (so a
    trade opened near the seam can resolve). Only entries inside the chunk's
    scored window are kept, so trades are never double-counted across seams."""
    n = len(bars)
    if n <= chunk + warmup + tail:
        return run_alpha(alpha, bars, cfg, start_index=start_index)

    return run_alphas_chunked([alpha], bars, cfg, chunk=chunk, warmup=warmup,
                              tail=tail, start_index=start_index)[alpha.name]


def run_alphas_chunked(
    alphas: list[Alpha],
    bars: list[Bar],
    cfg: Config,
    *,
    chunk: int = 8000,
    warmup: int = 300,
    tail: int = 800,
    start_index: int = 300,
    progress=None,
) -> dict[str, list[Trade]]:
    """Backtest several alphas over a long span, precomputing each chunk's
    detector context **once** and reusing it for every alpha. Returns
    ``{alpha_name: [Trade, ...]}``. ``progress`` is an optional callback
    ``(chunk_idx, n_chunks)`` for logging."""
    n = len(bars)
    out: dict[str, list[Trade]] = {a.name: [] for a in alphas}

    if n <= chunk + warmup + tail:
        ctx = precompute(bars, cfg)
        for a in alphas:
            out[a.name] = run_alpha(a, bars, cfg, ctx=ctx, start_index=start_index)
        return out

    starts = list(range(max(start_index, 0), n - 1, chunk))
    for idx, pos in enumerate(starts):
        seg_start = pos
        seg_end = min(pos + chunk, n)
        lo = max(0, seg_start - warmup)
        hi = min(n, seg_end + tail)
        sub = bars[lo:hi]
        seg_lo_time = bars[seg_start].time
        seg_hi_time = bars[seg_end - 1].time
        ctx = precompute(sub, cfg)
        if progress is not None:
            progress(idx + 1, len(starts))
        for a in alphas:
            for t in run_alpha(a, sub, cfg, ctx=ctx, start_index=seg_start - lo):
                if seg_lo_time <= t.entry_time <= seg_hi_time:
                    out[a.name].append(t)
    return out
