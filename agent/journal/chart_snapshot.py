"""Headless candlestick snapshots for the near-miss / loss vaults.

Renders ~80 candles ending at an event time with:
  * a coloured rectangle for the supply/demand zone (red = supply, green
    = demand, amber = unknown direction)
  * solid blue entry line, dashed red SL line, dashed green TP line, each
    with the price annotated on the right margin, plus a legend explaining
    what every line/rectangle means
  * a volume panel underneath (auto-hidden when the feed has no real tick
    volume in the visible window, so a data gap never renders a dead strip)
  * vertical markers at ``entry_time`` (when supplied) and ``event_time``
  * a title that calls out the rejection reason (in both its raw tag, for
    grep-ability, and a plain-English sentence) and direction
  * a small stats box (risk/reward in pips, R:R, zone width, zone age) so
    a reviewer can judge setup quality without doing mental arithmetic
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
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402

from agent.types import Bar  # noqa: E402

log = logging.getLogger(__name__)

PIP = 10000.0  # 4-decimal convention, matches agent.journal.resolver

# Zone-direction → (fill colour, edge colour). Supply zones (price comes DOWN
# off them on a long) read as a red ceiling; demand zones read as a green
# floor; anything else falls back to amber so the rectangle is still visible.
_ZONE_PALETTE: dict[str, tuple[str, str]] = {
    "short": ("#E53935", "#B71C1C"),   # supply
    "long":  ("#43A047", "#1B5E20"),   # demand
}

# Plain-English one-liners for the reason tags a vault event can carry, so a
# reviewer doesn't have to know the codebase to understand a title. Anything
# not in this table falls back to the raw tag untouched (never hides data).
REASON_LABELS: dict[str, str] = {
    "htf_gate": "Alpha fired, but rejected: direction agreed with the D1 "
                "trend instead of fading it",
    "post_loss_guard": "Alpha fired, but blocked: revenge-trade cooldown "
                        "active after a recent loss",
    "risk_manager": "Alpha fired, but skipped: portfolio risk manager "
                     "vetoed it (exposure / drawdown / position cap)",
    "sizing_skip": "Alpha fired, but skipped: computed position size was "
                    "below the broker's minimum",
    "portfolio_risk_cap": "Alpha fired, but skipped: combined portfolio "
                           "risk cap across symbols was already spent",
    "broker_reject": "Alpha fired, order was sent, but the broker refused "
                      "it (AutoTrading off, no margin, etc.)",
    "loss": "Live trade — closed at a loss",
    "manual": "Live trade — closed manually / cause unconfirmed",
}

# Custom TradingView-esque style: teal/coral candles instead of mplfinance's
# plain black-and-white "yahoo" default, softer grid, roomier fonts. Built
# once at import time — mplfinance styles are just dicts, cheap to keep live.
_MARKET_COLORS = mpf.make_marketcolors(
    up="#26A69A", down="#EF5350",
    edge={"up": "#1B7F76", "down": "#B23A38"},
    wick={"up": "#26A69A", "down": "#EF5350"},
    volume={"up": "#26A69A66", "down": "#EF535066"},
)
VAULT_STYLE = mpf.make_mpf_style(
    base_mpf_style="yahoo",  # light base — "nightclouds" etc. assume a
    # dark canvas and set white text, which turns invisible once we
    # override facecolor to something light. Keep the base light; only
    # swap its palette/grid for a TradingView-ish look.
    marketcolors=_MARKET_COLORS,
    facecolor="#FCFCFD",
    figcolor="#FFFFFF",
    gridcolor="#E3E6EA",
    gridstyle=":",
    edgecolor="#B0BEC5",
    rc={
        "font.size": 10,
        "font.family": "DejaVu Sans",
        "text.color": "#263238",
        "axes.labelcolor": "#37474F",
        "xtick.color": "#37474F",
        "ytick.color": "#37474F",
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
    },
)


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


def _fmt_pips(value: float) -> str:
    return f"{value:.1f}p"


def _build_stats_lines(
    *,
    entry: float | None,
    stop: float | None,
    take_profit: float | None,
    zone_top: float | None,
    zone_bottom: float | None,
    zone_created_at: datetime | None,
    event_time: datetime | None,
    zone_impulse_pips: float | None,
) -> list[str]:
    """Compose the top-left stats box: risk/reward/R:R, zone width, zone
    age, impulse strength — the numbers a reviewer needs to judge setup
    quality at a glance instead of doing mental subtraction on 5-decimal
    prices. Returns [] when there isn't enough to say anything useful."""
    lines: list[str] = []
    if entry and stop and entry > 0 and stop > 0:
        risk_pips = abs(entry - stop) * PIP
        line = f"Risk {_fmt_pips(risk_pips)}"
        if take_profit and take_profit > 0:
            reward_pips = abs(take_profit - entry) * PIP
            rr = reward_pips / risk_pips if risk_pips > 0 else 0.0
            line += f"  ·  Reward {_fmt_pips(reward_pips)}  ·  R:R 1:{rr:.2f}"
        lines.append(line)
    if zone_top is not None and zone_bottom is not None and zone_top > zone_bottom:
        width_pips = (zone_top - zone_bottom) * PIP
        line = f"Zone width {_fmt_pips(width_pips)}"
        if zone_impulse_pips is not None:
            line += f"  ·  formed by a {zone_impulse_pips:.0f}p impulse"
        lines.append(line)
    if zone_created_at is not None and event_time is not None:
        age = event_time - zone_created_at
        hours = age.total_seconds() / 3600.0
        if hours >= 0:
            lines.append(f"Zone age at touch: {hours:.0f}h")
    return lines


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
    zone_created_at: datetime | None = None,
    zone_impulse_pips: float | None = None,
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
    which side) using the raw tag (grep-able) plus a plain-English sentence
    from :data:`REASON_LABELS`; ``detail`` is rendered as a small
    bottom-right caption. ``zone_direction`` colours the zone rectangle by
    side (long=demand=green, short=supply=red); anything else falls back to
    amber. ``zone_created_at`` / ``zone_impulse_pips`` feed an optional
    stats box (risk/reward/R:R, zone width, zone age) — omitted fields are
    simply left out of the box rather than raising.
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
        friendly = REASON_LABELS.get(str(reason)) if reason else None
        # Stats (risk/reward/R:R/zone width/age) render as a bottom-left
        # caption instead of extra title lines — mplfinance's tight_layout
        # sizes the top margin for the title BEFORE we can add more lines
        # to it, so anything appended afterwards overlaps the plot instead
        # of pushing it down. The bottom corners are empty by construction.
        stats_lines = _build_stats_lines(
            entry=entry, stop=stop, take_profit=take_profit,
            zone_top=zone_top, zone_bottom=zone_bottom,
            zone_created_at=zone_created_at, event_time=event_time,
            zone_impulse_pips=zone_impulse_pips,
        )

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

        # Only show a volume panel when the visible window actually has
        # non-trivial tick volume — a stale/zero-filled feed would otherwise
        # render a dead grey strip that hurts readability more than it helps.
        show_volume = bool(df["Volume"].abs().sum() > 0 and df["Volume"].nunique() > 1)

        # mplfinance's per-style hline/vline support is fine, but we want
        # the figure back so we can annotate prices + caption afterwards.
        kwargs: dict = {
            "type": "candle",
            "style": VAULT_STYLE,
            "title": full_title,
            "ylabel": "",
            "figsize": (12, 7.5 if show_volume else 7),
            "tight_layout": True,
            "returnfig": True,
            "volume": show_volume,
        }
        if show_volume:
            kwargs["panel_ratios"] = (4, 1)
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
                color=color, fontsize=9, va="center", fontweight="bold",
                annotation_clip=False,
            )

        # Legend so a first-time viewer doesn't have to guess what the
        # lines/rectangle mean. Proxy artists only — nothing plotted twice.
        _LEVEL_LABELS = {"entry": "Entry", "SL": "Stop loss",
                          "TP": "Take profit", "rung": "Ladder rung"}
        seen_tags: set[str] = set()
        legend_handles = []
        for tag, _price, color, style in level_specs:
            if tag in seen_tags:
                continue
            seen_tags.add(tag)
            legend_handles.append(Line2D(
                [0], [0], color=color, lw=1.6, linestyle=style,
                label=_LEVEL_LABELS.get(tag, tag)))
        if zone_top is not None and zone_bottom is not None and zone_top > zone_bottom:
            zone_dir = (zone_direction or "").lower()
            face, _ = _ZONE_PALETTE.get(zone_dir, ("#FFB300", "#FF6F00"))
            zone_label = {"long": "Demand zone", "short": "Supply zone"}.get(
                zone_dir, "Zone")
            legend_handles.append(Patch(facecolor=face, alpha=0.35, label=zone_label))
        if legend_handles:
            # Figure-level (not axes-level) legend, in the strip between
            # mplfinance's title (anchored at fig y=0.89) and the figure's
            # top edge — an axes-anchored legend at "upper left" sits right
            # at the axes/title boundary and grazes the title text instead.
            fig.legend(
                handles=legend_handles, loc="upper center",
                bbox_to_anchor=(0.5, 1.0), ncol=len(legend_handles),
                fontsize=8, framealpha=0.9, facecolor="white",
                edgecolor="#B0BEC5",
            )

        # Plain-English reason + stats share one bottom-left box (rather
        # than a second title line, or a figure-level subtitle) — both of
        # those fight mplfinance's own fixed-position fig.suptitle() and
        # end up overlapping it instead of pushing it aside. The bottom
        # corners are empty by construction, so this is collision-free.
        box_lines = ([friendly] if friendly else []) + list(stats_lines)
        if box_lines:
            price_ax.text(
                0.01, 0.02, "\n".join(box_lines),
                transform=price_ax.transAxes,
                ha="left", va="bottom", fontsize=8,
                color="#263238",
                bbox={"facecolor": "white", "alpha": 0.8,
                      "edgecolor": "#B0BEC5", "boxstyle": "round,pad=0.3"},
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
