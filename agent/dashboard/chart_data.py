"""Load parquet price data and run detectors for the interactive chart API.

This module bridges the cached parquet files and the agent's detector suite,
returning JSON-serialisable dicts that the Lightweight Charts frontend can
render as candles, zones, levels, BOS markers, and FVG boxes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from agent.config import load_config
from agent.detectors.bos import detect_bos
from agent.detectors.daily_levels import DailyLevels, compute_daily_levels
from agent.detectors.fvg import detect_fvgs
from agent.detectors.zones import detect_zones, fresh_zones
from agent.types import Bar, Timeframe

log = logging.getLogger(__name__)
cfg = load_config()

SUPPORTED_TIMEFRAMES = {"M5", "M15", "H1", "H4", "D1"}


def _parquet_path(timeframe: str) -> Path:
    return cfg.data_dir / f"{cfg.symbol}_{timeframe}.parquet"


def _df_to_bars(df: pd.DataFrame, tf: Timeframe) -> list[Bar]:
    """Convert a pandas DataFrame (DatetimeIndex, OHLCV columns) to Bar list."""
    bars: list[Bar] = []
    for ts, row in df.iterrows():
        dt = ts.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        bars.append(Bar(
            time=dt,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            timeframe=tf,
        ))
    return bars


def load_candles(timeframe: str, limit: int = 500) -> list[dict]:
    """Return the last `limit` candles as JSON-friendly dicts for Lightweight Charts.

    Each dict: {time: <unix seconds>, open, high, low, close}.
    """
    path = _parquet_path(timeframe)
    if not path.exists():
        log.warning("parquet not found: %s", path)
        return []

    df = pd.read_parquet(path)
    df = df.sort_index().tail(limit)

    candles = []
    for ts, row in df.iterrows():
        dt = ts.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        candles.append({
            "time": int(dt.timestamp()),
            "open": round(float(row["open"]), 5),
            "high": round(float(row["high"]), 5),
            "low": round(float(row["low"]), 5),
            "close": round(float(row["close"]), 5),
        })
    return candles


def load_annotations(timeframe: str, limit: int = 500) -> dict:
    """Run detectors on the last `limit` bars and return structured annotations.

    Returns dict with keys: zones, levels, bos_markers, fvgs.
    """
    path = _parquet_path(timeframe)
    if not path.exists():
        return {"zones": [], "levels": [], "bos_markers": [], "fvgs": []}

    df = pd.read_parquet(path)
    df = df.sort_index()

    full_len = len(df)
    slice_start = max(0, full_len - limit - 500)
    df_extended = df.iloc[slice_start:]

    tf_enum = Timeframe(timeframe)
    bars = _df_to_bars(df_extended, tf_enum)

    offset = slice_start
    vis_start_idx = full_len - limit - offset
    vis_start_idx = max(0, vis_start_idx)

    zones_all = detect_zones(
        bars,
        min_impulse_pips=cfg.detectors.zone_min_impulse_pips,
        max_age_bars=cfg.detectors.zone_max_age_bars,
    )
    at_index = len(bars) - 1
    # No age cap for chart display — show all unmitigated zones in the visible window.
    active_zones = fresh_zones(zones_all, at_index, max_age_bars=None)

    levels_per_bar = compute_daily_levels(bars)

    bos_list = detect_bos(bars, swing_lookback=cfg.detectors.swing_lookback)

    fvg_list = detect_fvgs(bars, min_size_pips=cfg.detectors.fvg_min_size_pips)

    zone_dicts = []
    for z in active_zones:
        if z.created_bar_index < vis_start_idx:
            bar_time = int(bars[vis_start_idx].time.timestamp())
        else:
            bar_time = int(bars[z.created_bar_index].time.timestamp())

        end_time = int(bars[-1].time.timestamp())

        age_bars = at_index - z.created_bar_index
        label = "Demand" if z.direction.value == "long" else "Supply"
        zone_dicts.append({
            "type": "zone",
            "direction": z.direction.value,
            "top": round(z.top, 5),
            "bottom": round(z.bottom, 5),
            "time_start": bar_time,
            "time_end": end_time,
            "label": f"{label} Zone ({timeframe})",
            "tooltip": f"{label} Zone ({timeframe}) | Age: {age_bars} bars | Impulse: {z.impulse_pips:.1f} pips",
        })

    level_dicts = []
    if levels_per_bar:
        last_levels: DailyLevels = levels_per_bar[-1]
        for name, price in last_levels.levels_dict().items():
            level_dicts.append({
                "type": "level",
                "label": name,
                "price": round(price, 5),
                "tooltip": f"{name}: {price:.5f}",
            })

    bos_dicts = []
    for b in bos_list:
        if b.broken_bar_index < vis_start_idx:
            continue
        bar = bars[b.broken_bar_index]
        bos_dicts.append({
            "time": int(bar.time.timestamp()),
            "direction": b.direction.value,
            "price": round(b.broken_swing_price, 5),
            "position": "aboveBar" if b.direction.value == "long" else "belowBar",
            "shape": "arrowUp" if b.direction.value == "long" else "arrowDown",
            "color": "#26a69a" if b.direction.value == "long" else "#ef5350",
            "text": f"BOS {b.direction.value}",
            "tooltip": f"BOS {b.direction.value} | Broken swing: {b.broken_swing_price:.5f}",
        })

    fvg_dicts = []
    for f in fvg_list:
        if f.created_bar_index < vis_start_idx:
            continue
        if f.filled:
            continue
        bar_time = int(bars[f.created_bar_index].time.timestamp())
        end_idx = min(f.created_bar_index + 20, len(bars) - 1)
        end_time = int(bars[end_idx].time.timestamp())
        label = "Bullish FVG" if f.direction.value == "long" else "Bearish FVG"
        fvg_dicts.append({
            "type": "fvg",
            "direction": f.direction.value,
            "top": round(f.top, 5),
            "bottom": round(f.bottom, 5),
            "time_start": bar_time,
            "time_end": end_time,
            "label": label,
            "tooltip": f"{label} ({timeframe}) | Size: {f.size_pips:.1f} pips",
        })

    return {
        "zones": zone_dicts,
        "levels": level_dicts,
        "bos_markers": bos_dicts,
        "fvgs": fvg_dicts,
    }
