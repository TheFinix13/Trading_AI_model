"""Headless candlestick snapshots for the near-miss / loss vaults.

Renders ~80 candles ending at an event time with the zone rectangle,
entry/SL/TP horizontal lines (green/red/blue) and a vertical marker at the
event bar. Pure observation tooling: a failed render must never propagate —
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

import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from agent.types import Bar  # noqa: E402

log = logging.getLogger(__name__)


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
    entry_time: datetime | None = None,
    extra_levels: Sequence[float] | None = None,
    lookback: int = 80,
    lookahead: int = 0,
) -> Path | None:
    """Render a candle snapshot PNG. Returns the path, or None on any failure.

    The window is ``lookback`` bars ending at ``event_time`` plus up to
    ``lookahead`` bars after it (the resolver's aftermath view). When
    ``entry_time`` is given (loss vault: trade lifetime), the window is
    stretched back so the entry bar is always visible.
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

        hlines: list[float] = []
        hcolors: list[str] = []
        for level, color in ((entry, "green"), (stop, "red"), (take_profit, "blue")):
            if level is not None and level > 0:
                hlines.append(float(level))
                hcolors.append(color)
        # Extension-ladder rungs (observation-only structural targets).
        for level in extra_levels or []:
            if level is not None and level > 0:
                hlines.append(float(level))
                hcolors.append("purple")

        vlines = []
        for vt in (entry_time, event_time):
            if vt is not None and window[0].time <= vt <= window[-1].time:
                vlines.append(vt)

        kwargs: dict = {
            "type": "candle",
            "style": "yahoo",
            "title": title,
            "ylabel": "",
            "figsize": (12, 7),
            "tight_layout": True,
            "savefig": {"fname": str(out_path), "dpi": 110},
        }
        if hlines:
            kwargs["hlines"] = {
                "hlines": hlines, "colors": hcolors,
                "linestyle": "--", "linewidths": 1.2,
            }
        if vlines:
            kwargs["vlines"] = {
                "vlines": vlines, "colors": ["gray"] * len(vlines),
                "linestyle": ":", "linewidths": 1.0, "alpha": 0.7,
            }
        if zone_top is not None and zone_bottom is not None and zone_top > zone_bottom:
            kwargs["fill_between"] = {
                "y1": float(zone_bottom), "y2": float(zone_top),
                "alpha": 0.15, "color": "orange",
            }

        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        mpf.plot(df, **kwargs)
        return out
    except Exception as e:  # never let a chart kill the caller
        log.warning("chart snapshot render failed for %s: %s", out_path, e)
        return None
