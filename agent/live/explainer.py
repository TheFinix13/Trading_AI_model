"""Explainable AI logging layer for the live signal loop.

Renders step-by-step reasoning on every bar check using box-drawing
characters, making the agent's decision process fully transparent.

Two output modes:
  - verbose (--verbose):  Full 5-step breakdown on every new bar.
  - default:              One-liner heartbeat between bars; full output
                          only when a signal is generated.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from agent.context.htf_context import HTFContext, MarketBias, WeeklyNarrative
from agent.strategy.base import StrategyResult
from agent.types import Bar, Direction, Setup

log = logging.getLogger(__name__)

SYM_PASS = "\u2713"   # ✓
SYM_FAIL = "\u2717"   # ✗
SYM_LIGHTNING = "\u26a1"  # ⚡
SYM_NO = "\u274c"     # ❌

BOX_TL = "\u250c"   # ┌
BOX_V = "\u2502"     # │
BOX_BL = "\u2514"   # └
BOX_H = "\u2500"    # ─
BAR_SEP = "\u2550"   # ═


@dataclass
class GateCheckItem:
    """One line in the gate-check output."""
    gate_name: str
    passed: bool
    detail: str


@dataclass
class ExplainedDecision:
    """All data needed to render the full bar-check explanation."""
    bar_time: datetime
    timeframe: str
    price: float
    session: str
    day_of_week: str
    is_caution_day: bool

    # Step 1: Market context
    htf_context: Optional[HTFContext] = None
    htf_bias_str: str = "N/A"
    htf_confidence: float = 0.0
    weekly_summary: str = ""
    patterns_summary: str = ""
    fib_summary: str = ""

    # Step 2: Zone detection
    lzi_zones: list[str] = field(default_factory=list)
    fvg_zones: list[str] = field(default_factory=list)
    sd_zones: list[str] = field(default_factory=list)
    bos_events: list[str] = field(default_factory=list)

    # Step 3: Strategy evaluation
    strategy_results: list[StrategyResult] = field(default_factory=list)

    # Step 4: Gate check
    signal: Optional[Setup] = None
    gate_profile_name: str = ""
    gate_checks: list[GateCheckItem] = field(default_factory=list)
    gates_passed: bool = False

    # Step 5: Decision / Execution
    trade_executed: bool = False
    execution_details: dict = field(default_factory=dict)
    rejection_reason: str = ""
    nearest_setup_summary: str = ""
    watching_for: str = ""
    hypothetical_trade: str = ""


class BarCheckExplainer:
    """Formats the step-by-step explanation for each bar check."""

    def explain_context(
        self,
        htf_context: Optional[HTFContext],
        current_bar: Bar,
        session: str,
    ) -> tuple[str, dict]:
        """Build Step 1: Market Context block.

        Returns (formatted_text, context_dict) where context_dict feeds
        into the ExplainedDecision for later steps.
        """
        lines: list[str] = []
        ctx_data: dict = {}

        # HTF bias
        if htf_context is not None:
            h4_bias = htf_context.h4_bias.value.upper()
            d1_bias = htf_context.d1_bias.value.upper()
            combined = htf_context.combined_bias.value.upper()
            conf = htf_context.bias_confidence
            bias_detail = f"H4: {_bias_description(htf_context.h4_bias)}, D1: {_bias_description(htf_context.d1_bias)}"
            lines.append(f"HTF Bias: {combined} ({bias_detail})")
            lines.append(f"Confidence: {conf:.2f}")
            ctx_data["htf_bias_str"] = f"{combined} ({bias_detail})"
            ctx_data["htf_confidence"] = conf

            # Weekly narrative
            if htf_context.weekly is not None:
                w = htf_context.weekly
                w_range = f"{w.week_low:.4f}\u2014{w.week_high:.4f}"
                exp = w.expansion_direction.value.upper() if w.expansion_direction else "NEUTRAL"
                lines.append(f"Weekly: Range {w_range}, expanding {exp}")

                unswept_parts: list[str] = []
                if w.unswept_high_liquidity:
                    unswept_parts.append(f"HIGH @ {w.unswept_high_liquidity[0]:.4f}")
                if w.unswept_low_liquidity:
                    unswept_parts.append(f"LOW @ {w.unswept_low_liquidity[0]:.4f}")
                if unswept_parts:
                    lines.append(f"Unswept liquidity: {', '.join(unswept_parts)}")

            # Patterns
            if htf_context.active_patterns:
                for p in htf_context.active_patterns[:3]:
                    desc = p.description
                    if len(desc) > 75:
                        desc = desc[:72] + "..."
                    lines.append(f"Pattern: {desc}")
                ctx_data["patterns_summary"] = ", ".join(
                    p.pattern_type.value for p in htf_context.active_patterns[:3]
                )

            # HTF fib levels
            if htf_context.htf_fib_levels:
                nearest = min(
                    htf_context.htf_fib_levels,
                    key=lambda lf: abs(lf[0] - current_bar.close),
                )
                dist = abs(nearest[0] - current_bar.close) * 10000
                lines.append(f"H4 Fib: Price {dist:.0f} pips from {nearest[1]} ({nearest[0]:.5f})")
        else:
            lines.append("HTF Bias: N/A (context not available)")

        return _format_box("STEP 1: MARKET CONTEXT", lines), ctx_data

    def explain_detections(
        self,
        ctx,
        at_index: int,
        bos_list: list | None = None,
    ) -> tuple[str, dict]:
        """Build Step 2: Zone Detection block."""
        lines: list[str] = []
        det_data: dict = {"lzi_zones": [], "fvg_zones": [], "sd_zones": [], "bos_events": []}

        # LZI Zones
        liq_zones = getattr(ctx, "liquidity_zones", None) or []
        active_lzi = [z for z in liq_zones if z.formation_bar_index < at_index]
        if active_lzi:
            lines.append(f"LZI Zones ({len(active_lzi)} total):")
            for i, z in enumerate(active_lzi[-5:]):
                letter = chr(65 + i)
                quality = "A" if z.wick_size_pips >= 10 else "B"
                status = z.status.upper()
                age = at_index - z.formation_bar_index
                desc = (
                    f"  [{letter}] {z.zone_bottom:.4f}-{z.zone_top:.4f} "
                    f"({z.swept_label} sweep, quality {quality}, {status}, age {age}b)"
                )
                lines.append(desc)
                det_data["lzi_zones"].append(desc.strip())
        else:
            lines.append("LZI Zones: None active")

        # FVGs
        fvgs = getattr(ctx, "fvgs", None) or []
        active_fvgs = [f for f in fvgs if f.created_bar_index <= at_index and not f.is_fully_filled]
        if active_fvgs:
            for f in active_fvgs[-3:]:
                dir_label = "bullish" if f.direction == Direction.LONG else "bearish"
                grade = "A" if f.quality_score >= 70 else ("B+" if f.quality_score >= 55 else "B")
                fill = f", {f.fill_pct * 100:.0f}% filled" if f.fill_pct > 0 else ""
                desc = f"{dir_label} @ {f.bottom:.4f}-{f.top:.4f} (grade {grade}{fill})"
                det_data["fvg_zones"].append(desc)
            lines.append(f"FVGs: {len(active_fvgs)} active — " + "; ".join(det_data["fvg_zones"][:2]))
        else:
            lines.append("FVGs: None active")

        # SD Zones
        sd_zones = getattr(ctx, "qualified_zones", None) or getattr(ctx, "zones", None) or []
        active_sd = [z for z in sd_zones if getattr(z, "created_bar_index", at_index + 1) <= at_index]
        if active_sd:
            for z in active_sd[-3:]:
                dir_label = "Supply" if z.direction == Direction.SHORT else "Demand"
                q_score = getattr(z, "quality_score", 0)
                strength = getattr(z, "strength", 0)
                if q_score:
                    desc = f"{dir_label} {z.bottom:.4f}-{z.top:.4f} (score {q_score:.0f})"
                else:
                    desc = f"{dir_label} {z.bottom:.4f}-{z.top:.4f}"
                det_data["sd_zones"].append(desc)
            lines.append(f"SD Zones: {len(active_sd)} active — " + "; ".join(det_data["sd_zones"][:2]))
        else:
            lines.append("SD Zones: None active")

        # BOS
        all_bos = getattr(ctx, "bos_list", None) or (bos_list or [])
        recent_bos = [b for b in all_bos if b.broken_bar_index <= at_index and (at_index - b.broken_bar_index) <= 50]
        if recent_bos:
            for b in recent_bos[-2:]:
                dir_label = "Bearish" if b.direction == Direction.SHORT else "Bullish"
                desc = f"{dir_label} break at {b.broken_swing_price:.5f} (quality {b.quality_score:.0f})"
                det_data["bos_events"].append(desc)
            lines.append(f"BOS: " + "; ".join(det_data["bos_events"]))
        else:
            lines.append("BOS: None recent")

        return _format_box("STEP 2: ZONE DETECTION", lines), det_data

    def explain_strategies(
        self,
        strategy_results: list[StrategyResult],
    ) -> str:
        """Build Step 3: Strategy Evaluation block."""
        lines: list[str] = []

        for sr in strategy_results:
            lines.append(f"{sr.strategy_name}:")
            if sr.zones_details:
                for zd in sr.zones_details[:3]:
                    lines.append(f"  {zd}")

            for cp in sr.checks_passed:
                lines.append(f"  {SYM_PASS} {cp}")
            for cf in sr.checks_failed:
                lines.append(f"  {SYM_FAIL} {cf}")

            arrow = "\u2192"  # →
            lines.append(f"  {arrow} STATUS: {sr.status}")
            if sr.next_trigger:
                lines.append(f"  {arrow} Next: {sr.next_trigger}")
            lines.append("")

        if not strategy_results:
            lines.append("No strategies evaluated")

        return _format_box("STEP 3: STRATEGY EVALUATION", lines)

    def explain_reaction(
        self,
        *,
        components: Optional[dict] = None,
        conviction: float = 0.0,
        threshold: float = 0.0,
        direction: str = "",
        agreement: float = 0.0,
        level_label: str = "",
        is_breakout: bool = False,
        fired: bool = False,
        rejection: str = "",
    ) -> str:
        """Build the REACTION ENGINE step so the user can SEE the measured
        commitment scores (displacement / expansion / momentum / imbalance),
        the composite conviction vs threshold, and why it did or didn't react."""
        lines: list[str] = []
        comp = components or {}
        if comp:
            def _bar(v: float) -> str:
                filled = int(round(max(0.0, min(1.0, v)) * 10))
                return "\u2588" * filled + "\u2591" * (10 - filled)
            lines.append(f"Displacement : {_bar(comp.get('displacement', 0)):<10} {comp.get('displacement', 0):.2f}")
            lines.append(f"Expansion    : {_bar(comp.get('expansion', 0)):<10} {comp.get('expansion', 0):.2f}")
            lines.append(f"Momentum     : {_bar(comp.get('momentum', 0)):<10} {comp.get('momentum', 0):.2f}")
            lines.append(f"Imbalance    : {_bar(comp.get('imbalance', 0)):<10} {comp.get('imbalance', 0):.2f}")
            lines.append("")
        dir_label = "BUY" if str(direction).lower() in ("long", "buy") else ("SELL" if direction else "—")
        conv_sym = SYM_PASS if conviction >= threshold else SYM_FAIL
        lines.append(
            f"Conviction: {conviction:.2f} {conv_sym} (threshold {threshold:.2f}) "
            f"| dir {dir_label} | agreement {agreement:.2f}"
        )
        if level_label:
            verb = "breaking" if is_breakout else "at"
            lines.append(f"Level: {verb} {level_label}")
        if fired:
            lines.append(f"{SYM_LIGHTNING} REACTION FIRED — committed move confirmed")
        elif rejection:
            lines.append(f"{SYM_NO} no reaction: {rejection}")
        else:
            lines.append("No reaction this bar")
        return _format_box("STEP 3.5: REACTION ENGINE", lines)

    def explain_sizing(self, sizing_summary: str) -> str:
        """Build the POSITION SIZING step showing the risk-based math."""
        lines = [sizing_summary] if sizing_summary else ["[no sizing performed]"]
        return _format_box("STEP 6: POSITION SIZING", lines)

    def explain_guard(self, status: dict, decision: str = "", reason: str = "") -> str:
        """Build the RISK GUARD step so the user can SEE the post-loss / no-revenge
        guard working (cooldown, size reduction, circuit breaker, stop-out halt)."""
        lines: list[str] = []
        cl = status.get("consecutive_losses", 0)
        mult = status.get("size_multiplier", 1.0)
        halted = status.get("session_halted", False)
        cooldown = status.get("cooldown_until")
        lines.append(f"Consecutive losses: {cl} | next-trade risk x{mult:.2f}")
        if cooldown:
            lines.append(f"Cooldown until: {cooldown}")
        if halted:
            lines.append(f"{SYM_NO} SESSION HALTED: {status.get('halt_reason', '')}")
        if decision and decision != "ok":
            lines.append(f"{SYM_NO} ENTRY BLOCKED ({decision}): {reason}")
        elif not halted:
            lines.append(f"{SYM_PASS} entries allowed")
        return _format_box("STEP 0: RISK GUARD (post-loss / no-revenge)", lines)

    def explain_gates(
        self,
        signal: Optional[Setup],
        gate_checks: list[GateCheckItem],
        gate_profile_name: str,
    ) -> str:
        """Build Step 4: Gate Check block."""
        lines: list[str] = []

        if signal is None and not gate_checks:
            lines.append("[skipped \u2014 no confirmed signals this bar]")
            return _format_box("STEP 4: GATE CHECK (if signal exists)", lines)

        if signal is not None:
            dir_label = "BUY" if signal.direction == Direction.LONG else "SELL"
            strategy = signal.strategy_name or "generic"
            lines.append(f"Signal: {strategy} {dir_label} @ {signal.entry:.5f}")
            lines.append(f"Gate profile: {gate_profile_name}")

        for gc in gate_checks:
            sym = SYM_PASS if gc.passed else SYM_FAIL
            lines.append(f"  {sym} {gc.gate_name}: {gc.detail}")

        all_passed = all(gc.passed for gc in gate_checks) if gate_checks else False
        if all_passed:
            lines.append(f"All gates PASSED {SYM_PASS}")
        elif gate_checks:
            failed = [gc for gc in gate_checks if not gc.passed]
            lines.append(f"BLOCKED by: {failed[0].gate_name}")

        return _format_box("STEP 4: GATE CHECK", lines)

    def explain_decision(
        self,
        trade_executed: bool,
        signal: Optional[Setup] = None,
        execution_details: dict | None = None,
        rejection_reason: str = "",
        nearest_setup: str = "",
        watching_for: str = "",
        hypothetical: str = "",
        htf_aligned: bool | None = None,
    ) -> str:
        """Build Step 5: Decision / Execution block."""
        lines: list[str] = []

        if trade_executed and signal is not None and execution_details:
            lines.append(f"{SYM_LIGHTNING} TRADE SIGNAL CONFIRMED")
            dir_label = "BUY" if signal.direction == Direction.LONG else "SELL"
            lot = execution_details.get("lot_size", 0.01)
            lines.append(f"Action: {dir_label} {lot:.2f} EURUSD @ {signal.entry:.5f}")
            lines.append(f"Stop Loss: {signal.stop:.5f} ({signal.stop_pips:.0f} pips)")
            lines.append(f"Take Profit: {signal.take_profit:.5f} ({signal.reward_pips:.0f} pips)")
            lines.append(f"Risk:Reward: 1:{signal.rr:.2f}")
            strategy = signal.strategy_name or "generic"
            confluences = ", ".join(signal.confluences[:4])
            lines.append(f"Strategy: {strategy} | Confluences: {confluences}")
            if execution_details.get("fill_price"):
                fill = execution_details["fill_price"]
                slippage = abs(fill - signal.entry) * 10000
                lines.append(f"Sending to broker...")
                lines.append(f"{SYM_PASS} ORDER FILLED @ {fill:.5f} (slippage: {slippage:.1f} pips)")
            elif execution_details.get("rejected"):
                lines.append(f"{SYM_FAIL} ORDER REJECTED: {execution_details.get('reject_reason', 'unknown')}")
            header = "STEP 5: EXECUTION"
        else:
            lines.append(f"{SYM_NO} NO ENTRY THIS BAR")
            if rejection_reason:
                lines.append(f"Reason: {rejection_reason}")
            lines.append("")
            if nearest_setup:
                lines.append(f"Nearest setup: {nearest_setup}")
            if watching_for:
                lines.append(f"Watching for: {watching_for}")
            if hypothetical:
                lines.append(f"If triggered: {hypothetical}")
            if htf_aligned is not None:
                alignment = f"{SYM_PASS} confirms direction" if htf_aligned else f"{SYM_FAIL} conflicts"
                lines.append(f"HTF alignment: {alignment}")
            header = "STEP 5: DECISION"

        return _format_box(header, lines)

    def format_full_check(self, decision: ExplainedDecision) -> str:
        """Compose all 5 steps into the full bar-check output."""
        parts: list[str] = []

        # Header
        bar_time_str = decision.bar_time.strftime("%Y-%m-%d %H:%M UTC")
        day = decision.day_of_week
        caution = " (CAUTION)" if decision.is_caution_day else ""
        session = decision.session.upper().replace("_", " ") if decision.session else "UNKNOWN"

        parts.append("")
        parts.append(f"{BAR_SEP * 3} BAR CHECK: {bar_time_str} ({decision.timeframe}) {BAR_SEP * 3}")
        parts.append(f"Price: {decision.price:.5f} | Session: {session} | Day: {day}{caution}")
        parts.append("")

        # Step 1
        ctx_text, _ = self.explain_context(
            decision.htf_context, _mock_bar(decision), decision.session,
        )
        parts.append(ctx_text)

        # Step 2
        parts.append(_format_box("STEP 2: ZONE DETECTION", [
            f"LZI Zones: {', '.join(decision.lzi_zones) if decision.lzi_zones else 'None'}",
            f"FVGs: {', '.join(decision.fvg_zones) if decision.fvg_zones else 'None'}",
            f"SD Zones: {', '.join(decision.sd_zones) if decision.sd_zones else 'None'}",
            f"BOS: {', '.join(decision.bos_events) if decision.bos_events else 'None'}",
        ]))

        # Step 3
        parts.append(self.explain_strategies(decision.strategy_results))

        # Step 4
        parts.append(self.explain_gates(
            decision.signal, decision.gate_checks, decision.gate_profile_name,
        ))

        # Step 5
        parts.append(self.explain_decision(
            trade_executed=decision.trade_executed,
            signal=decision.signal,
            execution_details=decision.execution_details,
            rejection_reason=decision.rejection_reason,
            nearest_setup=decision.nearest_setup_summary,
            watching_for=decision.watching_for,
            hypothetical=decision.hypothetical_trade,
        ))

        return "\n".join(parts)

    def format_waiting_line(
        self,
        timeframe: str,
        price: float,
        next_close: str,
    ) -> str:
        """One-liner for non-new-bar checks."""
        now_str = datetime.now(tz=timezone.utc).strftime("%H:%M")
        return (
            f"{now_str} | Waiting for next {timeframe} close at {next_close} "
            f"| Price: {price:.5f}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _format_box(title: str, lines: list[str]) -> str:
    """Wrap lines in box-drawing characters."""
    width = 55
    header = f"{BOX_TL}{BOX_H} {title} {BOX_H * max(1, width - len(title) - 4)}"
    body = "\n".join(f"{BOX_V} {line}" for line in lines if line is not None)
    footer = f"{BOX_BL}{BOX_H * width}"
    return f"{header}\n{body}\n{footer}"


def _bias_description(bias: MarketBias) -> str:
    labels = {
        MarketBias.BULLISH: "higher highs",
        MarketBias.BEARISH: "lower highs",
        MarketBias.NEUTRAL: "neutral",
    }
    return labels.get(bias, bias.value)


def _mock_bar(decision: ExplainedDecision) -> Bar:
    """Create a minimal Bar for the explain_context method."""
    from agent.types import Timeframe
    return Bar(
        time=decision.bar_time,
        open=decision.price,
        high=decision.price,
        low=decision.price,
        close=decision.price,
        volume=0,
        timeframe=Timeframe(decision.timeframe),
    )
