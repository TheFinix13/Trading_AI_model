"""Setup and trade explainer.

Given a Trade or Setup, produces a human-readable narrative of WHY the system took
the trade. Two flavors:

  - Rule-based setups: list confluences in plain English with the actual prices
    each confluence was detected at.
  - ML-discovered setups: top-N SHAP feature contributions showing which features
    pushed the prediction up or down, plus the calibrated probability.

The point: every trade in the journal can be opened up and audited. If the user can
see exactly what triggered each trade, they can identify which patterns work in
practice vs which ones look good but lose money in the real world."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from agent.types import Direction, Setup, Trade


# Plain-English templates for each confluence tag emitted by the rule engine.
# Keep these short; the narrative reader is meant for quick scan, not prose.
_CONF_TEMPLATES: dict[str, str] = {
    "zone": "fresh {direction} zone (price retesting it)",
    "fvg": "unfilled Fair Value Gap aligned with direction",
    "bos": "Break of Structure confirming {direction} momentum",
    "trendline": "trendline support/resistance touch",
    "liquidity_wick": "long-wick liquidity grab on a recent swing",
    "fib_382": "price at the 38.2% Fibonacci retracement",
    "fib_500": "price at the 50% Fibonacci retracement",
    "fib_618": "price at the 61.8% (golden) Fibonacci retracement",
    "fib_786": "price at the 78.6% Fibonacci retracement",
    "discoverer": "ML pattern-discovery model fired",
    "htf_bias_long": "higher timeframes are bullish (D1/H4 trend up)",
    "htf_bias_short": "higher timeframes are bearish (D1/H4 trend down)",
    "htf_zone_long": "price is reacting to a higher-timeframe demand zone",
    "htf_zone_short": "price is reacting to a higher-timeframe supply zone",
}


@dataclass
class ExplanationLine:
    """One bulleted line in a narrative. Optional context dict for structured access."""
    text: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeExplanation:
    title: str
    summary_lines: list[str] = field(default_factory=list)
    why_taken: list[ExplanationLine] = field(default_factory=list)  # rule confluences / ML drivers
    risk_lines: list[str] = field(default_factory=list)
    outcome_lines: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _direction_word(d: Direction) -> str:
    return "long" if d == Direction.LONG else "short"


def _format_confluence(tag: str, setup: Setup) -> ExplanationLine:
    """Render one confluence tag with the actual prices/details from the setup."""
    direction = _direction_word(setup.direction)
    template = _CONF_TEMPLATES.get(tag, tag)
    text = template.format(direction=direction)
    ctx: dict[str, Any] = {"tag": tag}

    # Pull in the actual price levels from the setup attributes when present.
    if tag == "zone" and setup.zone is not None:
        z = setup.zone
        text += f" — zone={z.bottom:.5f}–{z.top:.5f}, impulse={z.impulse_pips:.0f} pips"
        ctx.update(zone_top=z.top, zone_bottom=z.bottom, impulse_pips=z.impulse_pips)
    elif tag == "fvg" and setup.fvg is not None:
        f = setup.fvg
        text += f" — gap={f.bottom:.5f}–{f.top:.5f}"
        ctx.update(fvg_top=f.top, fvg_bottom=f.bottom)
    elif tag == "bos" and setup.bos is not None:
        b = setup.bos
        text += f" — break of {b.broken_level:.5f}"
        ctx.update(broken_level=b.broken_level)
    elif tag.startswith("fib_") and setup.fib is not None:
        # Find matching fib level from the FibLevel.levels dict
        for lvl, price in setup.fib.levels.items():
            int_lvl = int(lvl * 1000)
            if f"fib_{int_lvl}" == tag:
                text += f" — {lvl*100:.1f}% level @ {price:.5f}"
                ctx.update(fib_level=lvl, fib_price=price)
                break
    elif tag == "trendline" and setup.trendline is not None:
        tl = setup.trendline
        line_price = tl.price_at(setup.detected_bar_index)
        text += f" — line @ {line_price:.5f}"
        ctx.update(line_price=line_price)
    elif tag == "liquidity_wick" and setup.liquidity_wick is not None:
        w = setup.liquidity_wick
        text += f" — wick {w.wick_bottom:.5f}–{w.wick_top:.5f} ({w.wick_to_body_ratio:.1f}x body)"
        ctx.update(wick_top=w.wick_top, wick_bottom=w.wick_bottom)

    return ExplanationLine(text=text, context=ctx)


def _shap_contributions(model, feature_cols: list[str], features: dict[str, float],
                        top_n: int = 5) -> list[ExplanationLine]:
    """For ML-discovered setups: compute per-feature SHAP contributions and pick the
    N largest by absolute impact. Returns empty list if SHAP isn't available or model
    doesn't support it."""
    try:
        import shap
    except ImportError:
        return [ExplanationLine(text="(SHAP unavailable; install `shap` to see ML feature attributions)")]
    if model is None:
        return []
    try:
        x = np.array([[features.get(c, 0.0) for c in feature_cols]], dtype=float)
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(x)
        if isinstance(shap_vals, list):
            shap_vals = shap_vals[1]  # binary classifier: positive class
        contribs = list(zip(feature_cols, shap_vals[0], x[0]))
        contribs.sort(key=lambda t: -abs(t[1]))
        out: list[ExplanationLine] = []
        for name, sv, value in contribs[:top_n]:
            arrow = "↑" if sv >= 0 else "↓"
            out.append(ExplanationLine(
                text=f"{arrow} {name} = {value:+.3f}  →  contribution {sv:+.3f}",
                context={"feature": name, "value": float(value), "shap": float(sv)},
            ))
        return out
    except Exception as e:
        return [ExplanationLine(text=f"(SHAP failed: {e})")]


def explain_setup(setup: Setup, ml_model=None, ml_feature_cols: list[str] | None = None) -> TradeExplanation:
    """Build the explanation for a setup at the moment it was decided."""
    direction = _direction_word(setup.direction)
    title = (f"{setup.detected_at:%Y-%m-%d %H:%M} UTC | EURUSD {setup.timeframe.value} "
             f"| {direction.upper()} setup")

    summary = [
        f"Entry: {setup.entry:.5f}",
        f"Stop:  {setup.stop:.5f}  ({setup.stop_pips:.1f} pips)",
        f"TP:    {setup.take_profit:.5f}  ({setup.reward_pips:.1f} pips)",
        f"R:R:   1:{setup.rr:.2f}",
    ]
    if setup.ml_score is not None:
        summary.append(f"ML score: {setup.ml_score:.3f}")

    why: list[ExplanationLine] = []
    if "discoverer" in setup.confluences:
        # ML-driven setup: list SHAP contributions
        why.append(ExplanationLine(text="Generated by the pattern-discoverer model:"))
        if ml_model is not None and ml_feature_cols and setup.features:
            why.extend(_shap_contributions(ml_model, ml_feature_cols, setup.features))
        else:
            why.append(ExplanationLine(text="(load the model and pass ml_model to see top features)"))
    else:
        # Rule-driven setup: render each confluence tag
        for tag in setup.confluences:
            why.append(_format_confluence(tag, setup))

    risk = [
        f"Risk per trade: {setup.stop_pips:.1f} pips → at 0.01 lot = ${setup.stop_pips * 0.01 * 10:.2f}",
        f"Reward target : {setup.reward_pips:.1f} pips → at 0.01 lot = ${setup.reward_pips * 0.01 * 10:.2f}",
    ]

    return TradeExplanation(
        title=title, summary_lines=summary, why_taken=why, risk_lines=risk,
        raw={"setup": setup},
    )


def explain_trade(trade: Trade, ml_model=None, ml_feature_cols: list[str] | None = None) -> TradeExplanation:
    """Same as explain_setup but also includes the OUTCOME of the trade
    (entry/exit prices, MAE/MFE, exit reason, P&L in pips and dollars)."""
    explanation = explain_setup(trade.setup, ml_model=ml_model, ml_feature_cols=ml_feature_cols)

    if trade.exit_time is not None:
        is_winner = trade.pnl > 0
        outcome = ["", "OUTCOME"]
        outcome.append(f"  Entered: {trade.entry_time:%Y-%m-%d %H:%M} UTC at {trade.entry_price:.5f}")
        outcome.append(f"  Exited:  {trade.exit_time:%Y-%m-%d %H:%M} UTC at {trade.exit_price:.5f}  "
                       f"(reason: {trade.exit_reason})")
        outcome.append(f"  Held    : {trade.bars_held} bars")
        outcome.append(f"  MFE     : {trade.mfe_pips:.1f} pips  (best favorable excursion)")
        outcome.append(f"  MAE     : {trade.mae_pips:.1f} pips  (worst adverse excursion)")
        outcome.append(f"  P&L     : {trade.pnl_pips:+.1f} pips  =  ${trade.pnl:+.2f}")
        outcome.append(f"  Result  : {'WIN' if is_winner else 'LOSS'}")
        explanation.outcome_lines = outcome

    return explanation


# ---------------------------------------------------------------------------
# Journal-aware narratives (what the dashboard /trade/{id} page renders).
# Doesn't require the full Setup object — only the journaled row + features dict.
# ---------------------------------------------------------------------------

# Plain-English templates keyed by confluence tag, used when reconstructing
# narratives from the journal (where we don't have the full Setup object).
_JOURNAL_TEMPLATES: dict[str, dict[str, str]] = {
    "zone": {
        "title": "Supply / demand zone",
        "long": ("Price retraced into a fresh demand zone. The zone formed from a strong "
                 "bullish impulse leaving an order-flow imbalance. We expect institutional "
                 "buyers to defend the zone."),
        "short": ("Price rallied back into a fresh supply zone. The zone formed from a strong "
                  "bearish impulse leaving an order-flow imbalance. We expect institutional "
                  "sellers to defend the zone."),
    },
    "bos": {
        "title": "Break of Structure",
        "long":  "Recent price action broke a prior swing high, confirming bullish momentum.",
        "short": "Recent price action broke a prior swing low, confirming bearish momentum.",
    },
    "fvg": {
        "title": "Fair Value Gap",
        "long":  "An unfilled bullish FVG sits below the entry, providing a magnet of liquidity.",
        "short": "An unfilled bearish FVG sits above the entry, providing a magnet of liquidity.",
    },
    "fib_382": {"title": "Fib 38.2%", "long": "Price tagged the shallow 38.2% retracement.", "short": "Price tagged the shallow 38.2% retracement."},
    "fib_500": {"title": "Fib 50%",   "long": "Price tagged the 50% retracement (mid of swing).", "short": "Price tagged the 50% retracement."},
    "fib_618": {"title": "Fib 61.8% (golden)", "long": "Price tagged the golden-ratio retracement — classic bullish entry zone.", "short": "Price tagged the golden-ratio retracement — classic bearish entry zone."},
    "fib_786": {"title": "Fib 78.6%", "long": "Price retraced 78.6% of the prior swing — deep retest.", "short": "Price retraced 78.6% of the prior swing — deep retest."},
    "trendline": {"title": "Trendline touch", "long": "Price tagged a rising trendline support.", "short": "Price tagged a falling trendline resistance."},
    "liquidity_wick": {"title": "Liquidity wick (sweep)", "long": "A long wick swept resting liquidity below a swing low before reversing — classic bullish stop hunt.", "short": "A long wick swept resting liquidity above a swing high before reversing — classic bearish stop hunt."},
    "discoverer": {"title": "ML pattern", "long": "The discovery model recognised a learned bullish pattern.", "short": "The discovery model recognised a learned bearish pattern."},
    "htf_bias_long": {"title": "HTF bias bullish", "long": "Higher timeframes (H4 / D1) trend up — entries align with the dominant flow.", "short": ""},
    "htf_bias_short": {"title": "HTF bias bearish", "long": "", "short": "Higher timeframes (H4 / D1) trend down — entries align with the dominant flow."},
    "htf_zone_long": {"title": "HTF demand zone", "long": "Price is reacting from a higher-timeframe demand zone (D1 / H4).", "short": ""},
    "htf_zone_short": {"title": "HTF supply zone", "long": "", "short": "Price is reacting from a higher-timeframe supply zone (D1 / H4)."},
}


def explain_journaled_trade(
    trade_row: dict,
    confluences: list[str],
    features: dict[str, float],
    *,
    display_tz_name: str = "America/New_York",
) -> dict:
    """Produce the rich, structured narrative the dashboard renders.

    The dashboard has a journal row (entry, exit, prices, lot) and a feature snapshot.
    From those it reconstructs *why* the trade was taken, in plain English, plus a
    market-state summary that any human can sanity-check against their own chart.

    Returns a JSON-friendly dict — the template just iterates over it."""
    direction = "long" if trade_row.get("direction") == "long" else "short"

    # Time conversion: store UTC, display in user's TZ (default NY for charting parity).
    try:
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(display_tz_name)
    except Exception:
        from datetime import timezone
        local_tz = timezone.utc

    def _fmt_local(iso_str: str | None) -> str:
        if not iso_str:
            return "—"
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.astimezone(local_tz).strftime("%a %Y-%m-%d %H:%M %Z")
        except Exception:
            return iso_str[:16]

    # 1. Confluences as rich sections (title + paragraph + concrete number)
    confluence_blocks: list[dict] = []
    for tag in confluences:
        tpl = _JOURNAL_TEMPLATES.get(tag, {"title": tag, "long": "", "short": ""})
        body = tpl.get(direction) or tpl.get("long") or tag
        block = {"tag": tag, "title": tpl["title"], "body": body, "facts": []}
        if tag == "zone" and features.get("zone_impulse_pips"):
            block["facts"].append(f"Impulse: {features['zone_impulse_pips']:.0f} pips")
            if features.get("zone_age_bars"):
                block["facts"].append(f"Zone age: {features['zone_age_bars']:.0f} bars")
            if features.get("dist_to_zone_pips") is not None:
                block["facts"].append(f"Distance to zone mid at entry: {features['dist_to_zone_pips']:.1f} pips")
        elif tag == "bos" and features.get("bos_age_bars") is not None:
            block["facts"].append(f"BOS age: {features['bos_age_bars']:.0f} bars")
            block["facts"].append(f"BOS aligned with trade dir: {'yes' if features.get('bos_aligned') else 'no'}")
        elif tag.startswith("fib_"):
            key = f"{tag}_dist_pips"
            if key in features:
                block["facts"].append(f"Distance to level at entry: {features[key]:.1f} pips")
        elif tag == "liquidity_wick" and features.get("wick_ratio"):
            block["facts"].append(f"Wick ratio: {features['wick_ratio']:.1f}× body")
        confluence_blocks.append(block)

    # 2. Market context (regime / momentum) — categorise features for the eye
    atr14 = features.get("atr_14_pips", 0.0)
    atr50 = features.get("atr_50_pips", 0.0)
    atr_ratio = features.get("atr_ratio", 1.0)
    if atr_ratio > 1.2:
        regime = f"Volatile (ATR14 {atr14:.0f} > ATR50 {atr50:.0f}, ratio {atr_ratio:.2f}×)"
    elif atr_ratio < 0.85:
        regime = f"Compressed (ATR14 {atr14:.0f} < ATR50 {atr50:.0f}, ratio {atr_ratio:.2f}×)"
    else:
        regime = f"Normal (ATR14 {atr14:.0f}, ATR50 {atr50:.0f}, ratio {atr_ratio:.2f}×)"

    pos50 = features.get("price_position_50", 0.5)
    if pos50 < 0.25:
        location = f"Near 50-bar low (position {pos50:.0%}) — discount zone"
    elif pos50 > 0.75:
        location = f"Near 50-bar high (position {pos50:.0%}) — premium zone"
    else:
        location = f"Mid 50-bar range (position {pos50:.0%})"

    above_ma21 = features.get("above_ma21", 0.5) > 0.5
    dist_ma21 = features.get("dist_to_ma21_pips", 0.0)
    ma_state = (f"Above MA21 by {dist_ma21:.1f} pips"
                if above_ma21 else f"Below MA21 by {abs(dist_ma21):.1f} pips")

    hour_utc = int(features.get("hour", -1)) if features.get("hour") is not None else -1
    if features.get("is_overlap"):
        session = f"London/NY overlap ({hour_utc}:00 UTC) — peak liquidity"
    elif features.get("is_london"):
        session = f"London session ({hour_utc}:00 UTC)"
    elif features.get("is_ny"):
        session = f"NY session ({hour_utc}:00 UTC)"
    else:
        session = f"Off-session ({hour_utc}:00 UTC)" if hour_utc >= 0 else "—"

    # 3. Outcome notes
    is_force_closed = trade_row.get("exit_reason") == "end_of_data"
    outcome_warning = None
    if is_force_closed:
        outcome_warning = ("This trade was force-closed because the backtest dataset ended "
                          "while the position was still open. Neither stop-loss nor take-profit "
                          "was actually hit — the P&L shown is just mark-to-market at the last bar's close. "
                          "DO NOT count this as a real win or loss.")

    # 4. Top-line summary
    pnl = trade_row.get("pnl") or 0
    pnl_pips = trade_row.get("pnl_pips") or 0
    rr = trade_row.get("sig_rr") or 0
    stop_pips = trade_row.get("sig_stop_pips") or 0
    ml_score = trade_row.get("ml_score")

    summary_paragraphs = [
        (f"On <strong>{_fmt_local(trade_row.get('detected_at') or trade_row.get('entry_time'))}</strong>, "
         f"the bot detected a <strong>{direction}</strong> setup on EURUSD "
         f"<strong>{trade_row.get('sig_tf') or '?'}</strong> with "
         f"<strong>{len(confluences)} confluence{'s' if len(confluences) != 1 else ''}</strong>: "
         f"{', '.join(confluences) if confluences else '<em>none recorded</em>'}."),
        (f"It entered at <strong>{trade_row.get('entry_price', 0):.5f}</strong> with a "
         f"<strong>{stop_pips:.1f}-pip stop</strong> targeting "
         f"<strong>1:{rr:.2f}</strong> reward. "
         + (f"ML scorer probability: <strong>{ml_score:.3f}</strong>. "
            if ml_score is not None else "No ML scorer was applied to this timeframe. ")),
    ]
    if trade_row.get("exit_time"):
        summary_paragraphs.append(
            f"Exited at <strong>{trade_row.get('exit_price', 0):.5f}</strong> on "
            f"<strong>{_fmt_local(trade_row.get('exit_time'))}</strong> via "
            f"<em>{trade_row.get('exit_reason')}</em>: "
            f"<strong>{pnl_pips:+.1f} pips (${pnl:+.2f})</strong>."
        )

    return {
        "direction": direction,
        "summary_paragraphs": summary_paragraphs,
        "confluence_blocks": confluence_blocks,
        "market_state": {
            "regime": regime,
            "location": location,
            "ma_state": ma_state,
            "session": session,
        },
        "is_force_closed": is_force_closed,
        "outcome_warning": outcome_warning,
        "entry_local": _fmt_local(trade_row.get("entry_time")),
        "exit_local": _fmt_local(trade_row.get("exit_time")),
        "detected_local": _fmt_local(trade_row.get("detected_at")),
    }


def format_explanation(e: TradeExplanation) -> str:
    """Pretty-print a TradeExplanation to a single string, ready for terminal/CLI.

    Uses '•' for content bullets and indents continuation/section lines without
    the bullet so headers like 'market state at entry...' aren't mistaken for
    confluence entries."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(e.title)
    lines.append("=" * 78)
    for s in e.summary_lines:
        lines.append("  " + s)
    lines.append("")
    lines.append("WHY THIS TRADE WAS TAKEN")
    if not e.why_taken:
        lines.append("  (no recorded confluences)")
    else:
        for w in e.why_taken:
            text = w.text
            if not text.strip():
                lines.append("")
            elif text.startswith("confluence:") or text.startswith("(no "):
                lines.append("  • " + text)
            else:
                # Section labels ('market state at entry...') and feature rows
                # are continuation content — render without a bullet.
                lines.append("    " + text)
    if e.risk_lines:
        lines.append("")
        lines.append("RISK / REWARD")
        for r in e.risk_lines:
            lines.append("  " + r)
    if e.outcome_lines:
        for o in e.outcome_lines:
            lines.append(o)
    lines.append("=" * 78)
    return "\n".join(lines)
