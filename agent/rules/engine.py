"""Confluence rule engine. Combines detector outputs into Setups gated by confluence count.

Two evaluation modes:
  - evaluate(bars, i):       slow path. Runs all detectors on bars[:i+1] from scratch.
  - evaluate_precomputed():  fast path. Uses structures detected ONCE on the full series,
                              filtering them to "as-of" decision bar i. Use this in backtests."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from agent.config import Config
from agent.detectors.atr import atr
from agent.detectors.bos import detect_bos, latest_bos
from agent.detectors.fib import auto_fib
from agent.detectors.fvg import detect_fvgs
from agent.detectors.liquidity import detect_liquidity_wicks
from agent.detectors.swings import detect_swings, last_swing
from agent.detectors.trendlines import fit_trendlines
from agent.detectors.zones import detect_zones, fresh_zones
from agent.rules.filters import in_no_trade_window, is_no_trade_day
from agent.rules.htf_bias import HTFBias, HTFBiasComputer
from agent.types import Bar, BreakOfStructure, Direction, FVG, FibLevel, LiquidityWick, Setup, Trendline, Zone
from agent.utils import to_pips

log = logging.getLogger(__name__)


@dataclass
class PrecomputedContext:
    """Detector outputs computed once over the full bar series. Slice by index at decision time."""
    bars: list[Bar]
    zones: list[Zone] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    bos_list: list[BreakOfStructure] = field(default_factory=list)
    trendlines: list[Trendline] = field(default_factory=list)
    wicks: list[LiquidityWick] = field(default_factory=list)
    fib_by_index: dict[int, FibLevel] = field(default_factory=dict)
    atr_by_index: dict[int, float] = field(default_factory=dict)


def _tf_scale(bars: list[Bar]) -> float:
    """Scale absolute pip thresholds by timeframe.
    Config defaults are calibrated for D1 (~80 pip ATR). Lower timeframes have proportionally
    smaller bar ranges, so detectors set to D1 thresholds find almost nothing on H1/M15."""
    if not bars:
        return 1.0
    tf = bars[0].timeframe.value
    return {"D1": 1.0, "H4": 0.5, "H1": 0.25, "M15": 0.12, "M5": 0.08, "M1": 0.04}.get(tf, 1.0)


def precompute(bars: list[Bar], cfg: Config, fib_recompute_every: int = 25) -> PrecomputedContext:
    """Compute all detectors once over the full bar series.
    Fib is recomputed every N bars (it depends on the most recent swings, which change)."""
    ctx = PrecomputedContext(bars=bars)
    scale = _tf_scale(bars)
    ctx.zones = detect_zones(
        bars,
        min_impulse_pips=cfg.detectors.zone_min_impulse_pips * scale,
        max_age_bars=cfg.detectors.zone_max_age_bars,
    )
    ctx.fvgs = detect_fvgs(bars, min_size_pips=cfg.detectors.fvg_min_size_pips * scale)
    ctx.bos_list = detect_bos(bars, swing_lookback=cfg.detectors.swing_lookback)
    ctx.trendlines = fit_trendlines(bars, swing_lookback=cfg.detectors.swing_lookback)
    ctx.wicks = detect_liquidity_wicks(bars, min_wick_ratio=cfg.detectors.liquidity_wick_min_ratio,
                                       swing_lookback=cfg.detectors.swing_lookback)

    # Fib needs to be "as of" each bar; recompute periodically to balance accuracy vs cost
    last_fib = None
    for i in range(0, len(bars), fib_recompute_every):
        last_fib = auto_fib(bars[: i + 1], swing_lookback=cfg.detectors.swing_lookback,
                            levels=tuple(cfg.detectors.fib_levels))
        ctx.fib_by_index[i] = last_fib

    # ATR rolling
    if len(bars) > 14:
        trs = [0.0]
        for i in range(1, len(bars)):
            h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        running = 0.0
        for i in range(len(bars)):
            window = trs[max(0, i - 13): i + 1]
            running = sum(window) / max(len(window), 1)
            ctx.atr_by_index[i] = running

    return ctx


class RuleEngine:
    def __init__(self, cfg: Config, htf_biases: list[HTFBiasComputer] | None = None):
        """`htf_biases` is an optional list of higher-timeframe bias computers (typically
        one for D1 and one for H4). They're only consulted when cfg.rules.htf_bias_mode
        is 'advisory' or 'strict'. Pass None for pure LTF-only evaluation."""
        self.cfg = cfg
        self.htf_biases = htf_biases or []

    def evaluate_precomputed(self, ctx: PrecomputedContext, at_index: int) -> Setup | None:
        if at_index < 50 or at_index >= len(ctx.bars):
            return None
        cur = ctx.bars[at_index]
        if in_no_trade_window(cur.time, self.cfg.session.no_trade_windows, self.cfg.session.timezone):
            return None
        if is_no_trade_day(cur.time, self.cfg.session.no_trade_days, self.cfg.session.timezone):
            return None

        zones = [z for z in ctx.zones if z.created_bar_index <= at_index]
        fvgs = [f for f in ctx.fvgs if f.created_bar_index <= at_index]
        bos_list = [b for b in ctx.bos_list if b.broken_bar_index <= at_index]
        wicks = [w for w in ctx.wicks if w.bar_index <= at_index]
        trendlines = [tl for tl in ctx.trendlines if tl.anchors[-1].bar_index <= at_index]

        # nearest precomputed fib at or before at_index
        keys = [k for k in ctx.fib_by_index.keys() if k <= at_index]
        fib = ctx.fib_by_index[max(keys)] if keys else None

        a = ctx.atr_by_index.get(at_index, 0.0)

        return self._build_best(ctx.bars, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a)

    def evaluate(self, bars: list[Bar], at_index: int) -> Setup | None:
        """Slow path: detect from scratch on bars[:at_index+1]. Use precompute() + evaluate_precomputed()
        for backtests."""
        if at_index < 50:
            return None

        window = bars[: at_index + 1]
        cur = window[-1]

        if in_no_trade_window(cur.time, self.cfg.session.no_trade_windows, self.cfg.session.timezone):
            return None
        if is_no_trade_day(cur.time, self.cfg.session.no_trade_days, self.cfg.session.timezone):
            return None

        scale = _tf_scale(window)
        zones = detect_zones(
            window,
            min_impulse_pips=self.cfg.detectors.zone_min_impulse_pips * scale,
            max_age_bars=self.cfg.detectors.zone_max_age_bars,
        )
        fvgs = detect_fvgs(window, min_size_pips=self.cfg.detectors.fvg_min_size_pips * scale)
        bos_list = detect_bos(window, swing_lookback=self.cfg.detectors.swing_lookback)
        fib = auto_fib(window, swing_lookback=self.cfg.detectors.swing_lookback,
                       levels=tuple(self.cfg.detectors.fib_levels))
        trendlines = fit_trendlines(window, swing_lookback=self.cfg.detectors.swing_lookback)
        wicks = detect_liquidity_wicks(window, min_wick_ratio=self.cfg.detectors.liquidity_wick_min_ratio,
                                       swing_lookback=self.cfg.detectors.swing_lookback)
        a = atr(window, period=14)
        return self._build_best(window, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a)

    def _build_best(self, bars, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a):
        long_setup = self._build(Direction.LONG, bars, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a)
        short_setup = self._build(Direction.SHORT, bars, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a)

        candidates = [s for s in (long_setup, short_setup) if s is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda s: len(s.confluences))

    def _build(
        self,
        direction: Direction,
        bars: list[Bar],
        at_index: int,
        zones,
        fvgs,
        bos_list,
        fib,
        trendlines,
        wicks,
        atr_value: float,
    ) -> Setup | None:
        cur = bars[at_index]
        confluences: list[str] = []

        # Volatility-aware tolerance (especially important on D1/H4).
        # Use max(15 pips, 0.2 * ATR) with a small floor.
        atr_pips = max(0.0, atr_value * 10000.0)
        tol_pips = max(15.0, 0.2 * atr_pips)
        tol = tol_pips * 0.0001

        bos = latest_bos([b for b in bos_list if b.direction == direction])
        if bos and (at_index - bos.broken_bar_index) <= 50:
            confluences.append("bos")

        fresh = fresh_zones([z for z in zones if z.direction == direction], at_index)
        zone = None
        for z in fresh[-5:]:
            # Trigger when price RANGE overlaps the zone, not only the close.
            if (cur.low <= z.top + tol) and (cur.high >= z.bottom - tol):
                zone = z
                confluences.append("zone")
                break

        active_fvg = None
        for f in fvgs[-20:]:
            if f.direction != direction or f.filled:
                continue
            if (cur.low <= f.top + tol) and (cur.high >= f.bottom - tol):
                active_fvg = f
                confluences.append("fvg")
                break

        active_fib = None
        if fib is not None and fib.direction == direction:
            for lvl, price in fib.levels.items():
                # Consider the fib "hit" if the bar range tagged it within tolerance.
                if (cur.low - tol) <= price <= (cur.high + tol):
                    active_fib = fib
                    confluences.append(f"fib_{int(lvl*1000)}")
                    break

        active_tl = None
        for tl in trendlines:
            if tl.direction != direction or not tl.valid:
                continue
            line_price = tl.price_at(at_index)
            if (cur.low - tol) <= line_price <= (cur.high + tol):
                active_tl = tl
                confluences.append("trendline")
                break

        active_wick = None
        for w in wicks[-10:]:
            if w.direction != direction:
                continue
            if (at_index - w.bar_index) > 30:
                continue
            wick_low = min(w.wick_top, w.wick_bottom)
            wick_high = max(w.wick_top, w.wick_bottom)
            if (cur.low <= wick_high + tol) and (cur.high >= wick_low - tol):
                active_wick = w
                confluences.append("liquidity_wick")
                break

        required = self.cfg.rules.required_factors
        for r in required:
            if r == "zone" and zone is None:
                return None
            if r == "fib" and active_fib is None:
                return None
            if r == "bos" and bos is None:
                return None

        if len(confluences) < self.cfg.rules.min_confluences:
            return None

        if atr_value <= 0:
            return None

        if direction == Direction.LONG:
            stop_anchor = min(zone.bottom if zone else cur.low, cur.low)
            stop = stop_anchor - self.cfg.rules.stop_buffer_pips * 0.0001
            # For backtests, we fill on next bar open anyway; entry is a signal price.
            entry = cur.close
            tp = entry + (entry - stop) * self.cfg.rules.rr_min
        else:
            stop_anchor = max(zone.top if zone else cur.high, cur.high)
            stop = stop_anchor + self.cfg.rules.stop_buffer_pips * 0.0001
            entry = cur.close
            tp = entry - (stop - entry) * self.cfg.rules.rr_min

        setup = Setup(
            direction=direction,
            timeframe=cur.timeframe,
            detected_at=cur.time,
            detected_bar_index=at_index,
            entry=entry,
            stop=stop,
            take_profit=tp,
            confluences=confluences,
            zone=zone,
            fvg=active_fvg,
            fib=active_fib,
            bos=bos,
            trendline=active_tl,
            liquidity_wick=active_wick,
        )

        # Stop size bounds: D1/H4 structural stops can be much wider than intraday.
        # Use ATR-aware bounds rather than a hard-coded 200 pips.
        min_stop_pips = max(5.0, 0.05 * atr_pips)
        max_stop_pips = max(200.0, 5.0 * atr_pips)

        # Risk-aligned cap: optionally reject anything that wouldn't fit the live account.
        # Math: max_stop_pips_live = (live_min_balance * pct_floor) / (lot_min * pip_value).
        if self.cfg.rules.enforce_live_stop_cap:
            risk_cap = (
                self.cfg.rules.live_min_balance * self.cfg.risk.pct_floor
            ) / (self.cfg.risk.lot_min * self.cfg.backtest.pip_value_per_lot)
            max_stop_pips = min(max_stop_pips, risk_cap)

        if setup.stop_pips < min_stop_pips or setup.stop_pips > max_stop_pips:
            return None
        if setup.rr < self.cfg.rules.rr_min:
            return None

        # Higher-timeframe bias check. Either annotate (advisory) or reject (strict).
        # Skipped entirely on D1/H4 timeframes — they ARE the HTF, no point self-checking.
        mode = self.cfg.rules.htf_bias_mode
        if mode != "off" and self.htf_biases and cur.timeframe.value in ("M1", "M5", "M15", "H1"):
            agrees = True
            tags: list[str] = []
            for hb in self.htf_biases:
                bias = hb.bias_at(cur.time, current_price=cur.close)
                if bias.direction is not None:
                    if bias.direction == direction:
                        tags.append(f"htf_bias_{'long' if direction == Direction.LONG else 'short'}")
                    else:
                        agrees = False
                if direction == Direction.LONG and bias.in_demand_zone:
                    tags.append("htf_zone_long")
                if direction == Direction.SHORT and bias.in_supply_zone:
                    tags.append("htf_zone_short")
            if mode == "strict" and not agrees:
                return None
            for t in tags:
                if t not in setup.confluences:
                    setup.confluences.append(t)

        return setup
