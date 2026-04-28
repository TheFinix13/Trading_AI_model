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


def format_explanation(e: TradeExplanation) -> str:
    """Pretty-print a TradeExplanation to a single string, ready for terminal/CLI."""
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
            lines.append("  • " + w.text)
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
