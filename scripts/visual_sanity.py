"""Render detector output over recent EURUSD bars to visually verify against your hand-drawn analysis.

Produces a candlestick chart with overlays:
  - Swing highs/lows (markers)
  - Supply zones (red rectangles)
  - Demand zones (green rectangles)
  - Fair Value Gaps (translucent boxes)
  - BOS markers
  - Fib retracement of last impulse
  - Trendlines
  - Liquidity wick markers
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Use a non-interactive backend by default so this works headless (VPS, CI, sandbox).
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.patches as patches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from agent.config import load_config
from agent.data.loader import BarLoader, df_to_bars
from agent.detectors.bos import detect_bos
from agent.detectors.fib import auto_fib
from agent.detectors.fvg import detect_fvgs
from agent.detectors.liquidity import detect_liquidity_wicks
from agent.detectors.swings import detect_swings
from agent.detectors.trendlines import fit_trendlines
from agent.detectors.zones import detect_zones
from agent.types import Direction, Timeframe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("visual_sanity")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default="D1")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--out", default="reports/sanity_check.png")
    args = parser.parse_args()

    cfg = load_config()
    symbol = args.symbol or cfg.symbol
    tf = Timeframe(args.timeframe)
    loader = BarLoader(cache_root=cfg.data_dir)

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=args.days)
    df = loader.get(symbol, tf, start, end)
    if df.empty:
        log.error("No bars. Run scripts/download_data.py first.")
        return

    bars = df_to_bars(df, tf)
    log.info("Rendering %d bars of %s %s", len(bars), symbol, tf.value)

    swings = detect_swings(bars, lookback=cfg.detectors.swing_lookback)
    zones = detect_zones(bars, min_impulse_pips=cfg.detectors.zone_min_impulse_pips)
    fvgs = detect_fvgs(bars, min_size_pips=cfg.detectors.fvg_min_size_pips)
    bos_list = detect_bos(bars, swing_lookback=cfg.detectors.swing_lookback)
    fib = auto_fib(bars, swing_lookback=cfg.detectors.swing_lookback)
    trendlines = fit_trendlines(bars, swing_lookback=cfg.detectors.swing_lookback)
    wicks = detect_liquidity_wicks(bars, min_wick_ratio=cfg.detectors.liquidity_wick_min_ratio)

    fig, ax = plt.subplots(figsize=(20, 10))
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")

    df_plot = df.copy()
    df_plot.index = pd.to_datetime(df_plot.index)

    width = 0.6 / max(1, len(bars))
    for i, b in enumerate(bars):
        x = mdates.date2num(b.time)
        color = "#2ea043" if b.is_bullish else "#cf222e"
        bar_w = (mdates.date2num(bars[1].time) - mdates.date2num(bars[0].time)) * 0.7 if len(bars) > 1 else 0.5
        ax.plot([x, x], [b.low, b.high], color=color, linewidth=1, zorder=2)
        rect = patches.Rectangle(
            (x - bar_w / 2, min(b.open, b.close)),
            bar_w,
            max(b.body, 1e-6),
            facecolor=color, edgecolor=color, alpha=0.9, zorder=3,
        )
        ax.add_patch(rect)

    times = [b.time for b in bars]
    x_left = mdates.date2num(times[0])
    x_right = mdates.date2num(times[-1])

    for z in zones:
        if z.created_bar_index >= len(bars):
            continue
        zx = mdates.date2num(bars[z.created_bar_index].time)
        face = "#cf222e22" if z.direction == Direction.SHORT else "#2ea04322"
        edge = "#cf222e" if z.direction == Direction.SHORT else "#2ea043"
        rect = patches.Rectangle(
            (zx, z.bottom),
            x_right - zx,
            z.top - z.bottom,
            facecolor=face, edgecolor=edge, linewidth=1, zorder=1, alpha=0.5,
        )
        ax.add_patch(rect)

    for f in fvgs[-30:]:
        if f.filled:
            continue
        fx = mdates.date2num(bars[f.created_bar_index].time)
        face = "#1f6feb22"
        rect = patches.Rectangle(
            (fx, f.bottom),
            x_right - fx,
            f.top - f.bottom,
            facecolor=face, edgecolor="#1f6feb", linewidth=0.5, zorder=1, alpha=0.6,
        )
        ax.add_patch(rect)

    for s in swings:
        x = mdates.date2num(s.time)
        marker = "^" if not s.is_high else "v"
        color = "#2ea043" if not s.is_high else "#cf222e"
        ax.scatter([x], [s.price], marker=marker, color=color, s=40, zorder=5)

    for b in bos_list:
        x = mdates.date2num(b.broken_at)
        ax.axhline(b.broken_swing_price, xmin=0, xmax=1, color="#d29922", linewidth=0.5, alpha=0.4, zorder=1)
        ax.text(x, b.broken_swing_price, "BOS", fontsize=8, color="#d29922")

    if fib is not None:
        for lvl, price in fib.levels.items():
            ax.axhline(price, color="#8a939e", linewidth=0.4, linestyle="--", alpha=0.7, zorder=1)
            ax.text(x_right, price, f"  {lvl*100:.1f}%", fontsize=8, color="#8a939e", verticalalignment="center")

    for tl in trendlines:
        if not tl.valid:
            continue
        x_start = tl.anchors[0].bar_index
        x_end = len(bars) - 1
        if x_start >= len(bars) or x_end >= len(bars):
            continue
        xs = [mdates.date2num(bars[x_start].time), mdates.date2num(bars[x_end].time)]
        ys = [tl.price_at(x_start), tl.price_at(x_end)]
        color = "#2ea043" if tl.direction == Direction.LONG else "#cf222e"
        ax.plot(xs, ys, color=color, linewidth=1.2, linestyle="-", alpha=0.8, zorder=4)

    for w in wicks:
        x = mdates.date2num(w.time)
        ax.scatter([x], [w.wick_top if w.direction == Direction.LONG else w.wick_bottom],
                   marker="o", color="#d29922", s=80, zorder=6, edgecolors="white", linewidths=0.5)

    ax.tick_params(colors="#d6dde6")
    for spine in ax.spines.values():
        spine.set_color("#2a3038")
    ax.grid(True, color="#2a3038", linewidth=0.3, alpha=0.5)
    ax.set_title(f"{symbol} {tf.value} - detector sanity check", color="#d6dde6", fontsize=14)
    ax.xaxis_date()
    fig.autofmt_xdate()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, facecolor=fig.get_facecolor())
    log.info("Saved chart to %s", out_path)
    log.info("Detector counts: swings=%d zones=%d fvgs=%d bos=%d trendlines=%d wicks=%d",
             len(swings), len(zones), len(fvgs), len(bos_list), len(trendlines), len(wicks))


if __name__ == "__main__":
    main()
