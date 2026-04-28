"""Loss diagnostics. Categorizes losing trades, breaks down by hour/day/regime/direction,
surfaces the worst N losers with full features for manual or automated review.

The point: turn "we have losses" into "we have THESE specific patterns of losses
caused by THESE conditions". Then the iteration loop knows what to retrain or filter on."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agent.types import Direction, Trade


# Loss categories. Derived from MAE/MFE/RR + exit reason.
LOSS_STOPPED_ON_RETRACE = "stopped_on_retrace"   # never moved much; shallow stop hit by chop
LOSS_REVERSAL = "reversal"                       # MFE significant, then trend reversed and stopped us
LOSS_NEVER_WORKED = "never_worked"               # adverse excursion grew steadily; bad setup
LOSS_SPIKE_OUT = "spike_out"                     # MAE >= stop but bar closed in favor; classic stop hunt
LOSS_END_OF_DATA = "end_of_data"                 # closed by force at backtest end
LOSS_UNKNOWN = "unknown"


@dataclass
class TradeAnalysis:
    """Per-trade enrichment. Wraps a Trade with derived diagnostic fields."""
    trade: Trade
    category: str
    realized_r: float          # pnl in R units (1R = stop_pips)
    mfe_r: float               # MFE / stop_pips
    mae_r: float               # MAE / stop_pips
    hour: int                  # entry hour, UTC
    day_of_week: int           # 0=Mon, 6=Sun
    timeframe: str
    confluences: tuple[str, ...]
    bars_held: int


@dataclass
class LossReport:
    n_trades: int
    n_losers: int
    n_winners: int
    win_rate: float
    avg_winner_r: float
    avg_loser_r: float
    expectancy_r: float
    profit_factor: float

    by_category: dict[str, int] = field(default_factory=dict)
    by_hour: dict[int, dict[str, int]] = field(default_factory=dict)
    by_day: dict[int, dict[str, int]] = field(default_factory=dict)
    by_direction: dict[str, dict[str, int]] = field(default_factory=dict)
    by_timeframe: dict[str, dict[str, int]] = field(default_factory=dict)
    by_confluence_count: dict[int, dict[str, int]] = field(default_factory=dict)

    worst_losers: list[TradeAnalysis] = field(default_factory=list)
    sample_winners: list[TradeAnalysis] = field(default_factory=list)


def _classify_loss(t: Trade) -> str:
    """Bucket each losing trade.

    The categories are mutually exclusive, evaluated in priority order. The cutoffs
    below are deliberately calibrated for typical FX setups (1.5R+ targets); tweak
    if you switch to a fundamentally different RR profile."""
    if t.exit_reason == "end_of_data":
        return LOSS_END_OF_DATA
    if t.exit_reason != "sl":
        return LOSS_UNKNOWN  # winners shouldn't pass through here; defensive

    setup = t.setup
    stop_pips = max(setup.stop_pips, 0.5)  # avoid div/0 on degenerate setups

    mfe_r = t.mfe_pips / stop_pips
    mae_r = t.mae_pips / stop_pips

    # Spike-out: bar wicked through the stop but closed back in favor (we'd never know
    # in real time, but it's a useful diagnostic for "was our stop too tight?").
    if mae_r >= 1.0 and mfe_r >= 0.7:
        return LOSS_SPIKE_OUT
    # Reversal: we got significantly into profit (>= 0.5R) before being stopped.
    if mfe_r >= 0.5:
        return LOSS_REVERSAL
    # Stopped on retrace: never gave us more than 0.2R favorable, but adverse
    # was relatively contained (bar-by-bar chop).
    if mfe_r < 0.2 and t.bars_held <= 10:
        return LOSS_STOPPED_ON_RETRACE
    # Never worked: stopped within reasonable time, no real favorable progress.
    return LOSS_NEVER_WORKED


def _to_analysis(t: Trade) -> TradeAnalysis:
    setup = t.setup
    stop_pips = max(setup.stop_pips, 0.5)
    realized_r = t.pnl_pips / stop_pips
    mfe_r = t.mfe_pips / stop_pips
    mae_r = t.mae_pips / stop_pips
    is_winner = t.pnl > 0
    category = "winner" if is_winner else _classify_loss(t)
    return TradeAnalysis(
        trade=t,
        category=category,
        realized_r=realized_r,
        mfe_r=mfe_r,
        mae_r=mae_r,
        hour=t.entry_time.hour,
        day_of_week=t.entry_time.weekday(),
        timeframe=setup.timeframe.value,
        confluences=tuple(setup.confluences),
        bars_held=t.bars_held,
    )


def _bucket(items: list[TradeAnalysis], key_fn) -> dict[Any, dict[str, int]]:
    buckets: dict[Any, dict[str, int]] = defaultdict(lambda: {"win": 0, "loss": 0})
    for a in items:
        k = key_fn(a)
        if a.realized_r > 0:
            buckets[k]["win"] += 1
        else:
            buckets[k]["loss"] += 1
    return dict(buckets)


def analyze(trades: list[Trade], n_worst: int = 10, n_sample_winners: int = 5) -> LossReport:
    """Build a full diagnostic report from a list of completed trades.

    The report groups losses by hypothesis-friendly axes (hour, day, regime, etc.)
    so you can spot patterns like "all the spike-outs happen on Friday close" or
    "ranging-regime trades have 2x the never-worked rate"."""
    if not trades:
        return LossReport(n_trades=0, n_losers=0, n_winners=0, win_rate=0.0,
                          avg_winner_r=0.0, avg_loser_r=0.0, expectancy_r=0.0,
                          profit_factor=0.0)

    enriched = [_to_analysis(t) for t in trades]
    winners = [a for a in enriched if a.realized_r > 0]
    losers = [a for a in enriched if a.realized_r <= 0]

    win_rate = len(winners) / len(enriched)
    avg_w = sum(a.realized_r for a in winners) / len(winners) if winners else 0.0
    avg_l = sum(a.realized_r for a in losers) / len(losers) if losers else 0.0
    expectancy_r = sum(a.realized_r for a in enriched) / len(enriched)
    gross_profit = sum(a.realized_r for a in winners)
    gross_loss = abs(sum(a.realized_r for a in losers))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    cats = Counter(a.category for a in losers)

    return LossReport(
        n_trades=len(enriched),
        n_losers=len(losers),
        n_winners=len(winners),
        win_rate=win_rate,
        avg_winner_r=avg_w,
        avg_loser_r=avg_l,
        expectancy_r=expectancy_r,
        profit_factor=pf,
        by_category=dict(cats),
        by_hour=_bucket(enriched, lambda a: a.hour),
        by_day=_bucket(enriched, lambda a: a.day_of_week),
        by_direction=_bucket(enriched, lambda a: a.trade.direction.value),
        by_timeframe=_bucket(enriched, lambda a: a.timeframe),
        by_confluence_count=_bucket(enriched, lambda a: len(a.confluences)),
        worst_losers=sorted(losers, key=lambda a: a.realized_r)[:n_worst],
        sample_winners=sorted(winners, key=lambda a: -a.realized_r)[:n_sample_winners],
    )


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def format_report(r: LossReport) -> str:
    """Pretty-print a LossReport for terminal/CLI consumption."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("LOSS DIAGNOSTICS")
    lines.append("=" * 70)
    lines.append(f"Trades       : {r.n_trades}  (winners={r.n_winners}, losers={r.n_losers})")
    lines.append(f"Win rate     : {r.win_rate*100:.1f}%")
    lines.append(f"Avg winner   : {r.avg_winner_r:+.2f}R")
    lines.append(f"Avg loser    : {r.avg_loser_r:+.2f}R")
    lines.append(f"Expectancy   : {r.expectancy_r:+.2f}R / trade")
    pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "inf"
    lines.append(f"Profit factor: {pf_str}")
    lines.append("")
    lines.append("Loss categories:")
    for cat, n in sorted(r.by_category.items(), key=lambda kv: -kv[1]):
        pct = 100 * n / max(r.n_losers, 1)
        lines.append(f"  {cat:24s}  {n:4d}   ({pct:5.1f}% of losers)")
    lines.append("")

    def _table(title: str, buckets: dict, label_fn=str):
        lines.append(title)
        for k in sorted(buckets.keys()):
            v = buckets[k]
            total = v["win"] + v["loss"]
            wr = 100 * v["win"] / max(total, 1)
            lines.append(f"  {label_fn(k):>8s}  W:{v['win']:3d}  L:{v['loss']:3d}  "
                         f"({total:3d} trades, {wr:5.1f}% win)")
        lines.append("")

    _table("By hour (UTC):", r.by_hour, lambda h: f"{h:02d}:00")
    _table("By day of week:", r.by_day, lambda d: _DAY_NAMES[d] if 0 <= d < 7 else str(d))
    _table("By direction:", r.by_direction)
    _table("By timeframe:", r.by_timeframe)
    _table("By confluence count:", r.by_confluence_count, str)

    lines.append("Worst losers:")
    for a in r.worst_losers:
        t = a.trade
        confs = ",".join(a.confluences) or "-"
        lines.append(f"  {t.entry_time:%Y-%m-%d %H:%M}  {t.direction.value:5s} "
                     f"[{a.timeframe}]  {a.realized_r:+.2f}R  "
                     f"mfe={a.mfe_r:+.2f}R mae={a.mae_r:+.2f}R  "
                     f"bars={a.bars_held:3d}  cat={a.category}  conf={confs}")
    lines.append("")
    lines.append("Sample winners:")
    for a in r.sample_winners:
        t = a.trade
        confs = ",".join(a.confluences) or "-"
        lines.append(f"  {t.entry_time:%Y-%m-%d %H:%M}  {t.direction.value:5s} "
                     f"[{a.timeframe}]  {a.realized_r:+.2f}R  "
                     f"mfe={a.mfe_r:+.2f}R bars={a.bars_held:3d}  conf={confs}")
    lines.append("=" * 70)
    return "\n".join(lines)
