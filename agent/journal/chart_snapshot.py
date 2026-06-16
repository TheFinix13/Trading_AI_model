"""Headless candlestick snapshots for the near-miss / loss vaults.

Renders ~80 candles ending at an event time with:
  * a coloured rectangle for the supply/demand zone (red = supply, green
    = demand, amber = unknown direction)
  * solid blue entry line, dashed red SL line, dashed green TP line, each
    with the price annotated on the right margin
  * vertical markers at ``entry_time`` (when supplied) and ``event_time``
  * a title that calls out the rejection reason and direction
  * a small bottom-right caption with the rejection detail (e.g. the HTF
    bias or risk-manager message) so a reviewer can see WHY the chart
    is in the vault without opening the JSONL

Pure observation tooling: a failed render must never propagate —
:func:`render_snapshot` swallows every exception, logs a warning and returns
``None``, so the live loop and the resolver are immune to plotting issues.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")  # before any pyplot import — must work headless

import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from agent.types import Bar  # noqa: E402

log = logging.getLogger(__name__)


# Zone-direction → (fill colour, edge colour). Supply zones (price comes DOWN
# off them on a long) read as a red ceiling; demand zones read as a green
# floor; anything else falls back to amber so the rectangle is still visible.
_ZONE_PALETTE: dict[str, tuple[str, str]] = {
    "short": ("#E53935", "#B71C1C"),   # supply
    "long":  ("#43A047", "#1B5E20"),   # demand
}


def _bars_to_df(bars: Sequence[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [b.open for b in bars],
            "High": [b.high for b in bars],
            "Low": [b.low for b in bars],
            "Close": [b.close for b in bars],
            "Volume": [b.volume for b in bars],
        },
        index=pd.DatetimeIndex([b.time for b in bars]),
    )


def _index_at_or_before(bars: Sequence[Bar], when: datetime | None) -> int:
    """Index of the last bar whose time is <= ``when`` (last bar if None /
    out of range)."""
    if when is None:
        return len(bars) - 1
    idx = len(bars) - 1
    for i, b in enumerate(bars):
        if b.time > when:
            idx = max(0, i - 1)
            break
    return idx


def render_snapshot(
    bars: Sequence[Bar],
    out_path: Path | str,
    *,
    title: str,
    event_time: datetime | None = None,
    entry: float | None = None,
    stop: float | None = None,
    take_profit: float | None = None,
    zone_top: float | None = None,
    zone_bottom: float | None = None,
    zone_direction: str | None = None,
    entry_time: datetime | None = None,
    extra_levels: Sequence[float] | None = None,
    reason: str | None = None,
    direction: str | None = None,
    detail: str | None = None,
    lookback: int = 80,
    lookahead: int = 0,
) -> Path | None:
    """Render a candle snapshot PNG. Returns the path, or None on any failure.

    The window is ``lookback`` bars ending at ``event_time`` plus up to
    ``lookahead`` bars after it. When ``entry_time`` is given, the window is
    stretched back so the entry bar is always visible.

    ``reason`` / ``direction`` are folded into the title (so a glance at a
    PNG filename or window header tells the operator what gate fired and on
    which side); ``detail`` is rendered as a small bottom-right caption.
    ``zone_direction`` colours the zone rectangle by side (long=demand=green,
    short=supply=red); anything else falls back to amber.
    """
    try:
        if not bars:
            return None
        end_idx = _index_at_or_before(bars, event_time)
        start_idx = max(0, end_idx - lookback + 1)
        if entry_time is not None:
            entry_idx = _index_at_or_before(bars, entry_time)
            start_idx = min(start_idx, max(0, entry_idx - 20))
        stop_idx = min(len(bars), end_idx + 1 + lookahead)
        window = list(bars[start_idx:stop_idx])
        if len(window) < 2:
            return None
        df = _bars_to_df(window)

        full_title = title
        bits: list[str] = []
        if reason:
            bits.append(str(reason))
        if direction:
            bits.append(str(direction).upper())
        if bits:
            full_title = f"{title}  [{' | '.join(bits)}]"

        # Horizontal price levels. Entry stays solid (the price you'd have
        # been filled at); SL/TP dashed because they're conditional outcomes.
        # Each level is captured separately so we can annotate it after
        # mplfinance hands the figure back.
        level_specs: list[tuple[str, float, str, str]] = []
        if entry is not None and entry > 0:
            level_specs.append(("entry", float(entry), "#1565C0", "-"))
        if stop is not None and stop > 0:
            level_specs.append(("SL", float(stop), "#C62828", "--"))
        if take_profit is not None and take_profit > 0:
            level_specs.append(("TP", float(take_profit), "#2E7D32", "--"))
        for level in extra_levels or []:
            if level is not None and level > 0:
                level_specs.append(("rung", float(level), "#7E57C2", ":"))

        vlines = []
        for vt in (entry_time, event_time):
            if vt is not None and window[0].time <= vt <= window[-1].time:
                vlines.append(vt)

        # mplfinance's per-style hline/vline support is fine, but we want
        # the figure back so we can annotate prices + caption afterwards.
        kwargs: dict = {
            "type": "candle",
            "style": "yahoo",
            "title": full_title,
            "ylabel": "",
            "figsize": (12, 7),
            "tight_layout": True,
            "returnfig": True,
        }
        if level_specs:
            kwargs["hlines"] = {
                "hlines": [p for _, p, _, _ in level_specs],
                "colors": [c for _, _, c, _ in level_specs],
                "linestyle": [s for _, _, _, s in level_specs],
                "linewidths": [1.4 if t == "entry" else 1.2
                               for t, _, _, _ in level_specs],
            }
        if vlines:
            kwargs["vlines"] = {
                "vlines": vlines, "colors": ["gray"] * len(vlines),
                "linestyle": ":", "linewidths": 1.0, "alpha": 0.7,
            }
        if zone_top is not None and zone_bottom is not None and zone_top > zone_bottom:
            zone_dir = (zone_direction or "").lower()
            face, _ = _ZONE_PALETTE.get(zone_dir, ("#FFB300", "#FF6F00"))
            kwargs["fill_between"] = {
                "y1": float(zone_bottom), "y2": float(zone_top),
                "alpha": 0.18, "color": face,
            }

        fig, axes = mpf.plot(df, **kwargs)
        price_ax = axes[0] if isinstance(axes, (list, tuple)) else axes

        # Right-margin labels for entry / SL / TP. We annotate in axes
        # coords so the label hugs the right edge regardless of zoom.
        for tag, price, color, _ in level_specs:
            price_ax.annotate(
                f"{tag} {price:.5f}",
                xy=(1.0, price), xycoords=("axes fraction", "data"),
                xytext=(4, 0), textcoords="offset points",
                color=color, fontsize=9, va="center",
                annotation_clip=False,
            )

        if detail:
            price_ax.text(
                0.99, 0.02, str(detail),
                transform=price_ax.transAxes,
                ha="right", va="bottom", fontsize=8,
                color="#37474F",
                bbox={"facecolor": "white", "alpha": 0.7,
                      "edgecolor": "#B0BEC5", "boxstyle": "round,pad=0.3"},
            )

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=110, bbox_inches="tight")
        plt.close(fig)
        return out
    except Exception as e:  # never let a chart kill the caller
        log.warning("chart snapshot render failed for %s: %s", out_path, e)
        return None
