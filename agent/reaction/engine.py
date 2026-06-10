"""ReactionEngine — turns measured commitment into a tradeable signal.

The engine evaluates the four commitment components on the just-closed bar(s),
blends them into a composite conviction, checks that price is acting on a
pre-marked level of interest (or breaking through one with force), and — if
conviction clears the configured threshold — emits a :class:`ReactionSignal`
with entry / stop / target and a human-readable rationale.

This is deliberately decoupled from the live loop: the loop supplies the bars,
ATR, the marked levels and the structures needed for PD-array targeting, and
gets back a signal (or None) plus the component scores for the explainer.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.config import ReactionConfig
from agent.detectors.daily_levels import DailyLevels
from agent.detectors.liquidity_magnet import RangeLiquidity
from agent.detectors.pd_array import find_draw_on_liquidity
from agent.reaction.components import ReactionComponents, compute_components
from agent.types import Bar, Direction, Swing

PIP = 0.0001


@dataclass
class LevelOfInterest:
    """A pre-marked structural level the reaction engine watches.

    `kind` is a short source tag (htf, lzi, sd, fvg, daily) used purely for the
    rationale string and logs.
    """

    price: float
    label: str
    kind: str = "level"


@dataclass
class ReactionAssessment:
    """Full diagnostic of one reaction evaluation — fired or not.

    Surfaced to the explainer so the user can always SEE the measured scores,
    the composite conviction vs threshold, and exactly why a reaction did or
    did not fire on this bar.
    """

    components: ReactionComponents
    conviction: float
    agreement: float
    threshold: float
    direction: Direction | None
    level: "LevelOfInterest | None"
    is_breakout: bool
    fired: bool
    rejection: str
    signal: "ReactionSignal | None"
    is_impulse: bool = False


@dataclass
class ReactionSignal:
    """A committed-move reaction ready to be risk-checked and sized."""

    direction: Direction
    conviction: float
    components: ReactionComponents
    entry: float
    stop: float
    take_profit: float
    rationale: str
    level_label: str = ""
    level_kind: str = ""
    is_breakout: bool = False
    is_impulse: bool = False
    target_label: str = "fallback_rr"
    agreement: float = 1.0

    @property
    def stop_pips(self) -> float:
        return abs(self.entry - self.stop) / PIP

    @property
    def reward_pips(self) -> float:
        return abs(self.take_profit - self.entry) / PIP

    @property
    def rr(self) -> float:
        sp = self.stop_pips
        return (self.reward_pips / sp) if sp > 0 else 0.0

    def component_summary(self) -> str:
        c = self.components
        return (
            f"disp={c.displacement:.2f} exp={c.expansion:.2f} "
            f"mom={c.momentum:.2f} imb={c.imbalance:.2f}"
        )


class ReactionEngine:
    def __init__(self, cfg: ReactionConfig):
        self.cfg = cfg

    # ------------------------------------------------------------------
    # Conviction
    # ------------------------------------------------------------------

    def _conviction(self, comp: ReactionComponents) -> tuple[float, float]:
        """Blend the four components into a composite, dampened by directional
        agreement. Returns (conviction, agreement)."""
        cfg = self.cfg
        w_sum = (
            cfg.weight_displacement
            + cfg.weight_expansion
            + cfg.weight_momentum
            + cfg.weight_imbalance
        ) or 1.0
        raw = (
            cfg.weight_displacement * comp.displacement
            + cfg.weight_expansion * comp.expansion
            + cfg.weight_momentum * comp.momentum
            + cfg.weight_imbalance * comp.imbalance
        ) / w_sum

        # Directional agreement: fraction of the directional weight that points
        # the same way as the voted direction. Expansion is non-directional, so
        # it is excluded from the agreement calculation.
        if comp.direction is None:
            return 0.0, 0.0
        aligned = 0.0
        total = 0.0
        for dir_, w, s in (
            (comp.displacement_dir, cfg.weight_displacement, comp.displacement),
            (comp.momentum_dir, cfg.weight_momentum, comp.momentum),
            (comp.imbalance_dir, cfg.weight_imbalance, comp.imbalance),
        ):
            if dir_ is None or s <= 0:
                continue
            total += w * s
            if dir_ == comp.direction:
                aligned += w * s
        agreement = (aligned / total) if total > 0 else 0.0
        # Map agreement (0.5 = split, 1.0 = unanimous) into a [0.5, 1.0] damper.
        damper = 0.5 + 0.5 * _clamp((agreement - 0.5) * 2.0)
        return raw * damper, agreement

    # ------------------------------------------------------------------
    # Level context
    # ------------------------------------------------------------------

    def _draw_bias(
        self, direction: Direction, entry: float, range_liq: RangeLiquidity | None
    ) -> tuple[float, str]:
        """Bias conviction by where price sits in the dealing range (ERL framing).

        Price in the **premium** (upper part) of the range is being drawn toward
        the external buy-side pool; a fresh LONG there is *chasing into liquidity*
        (penalised), while a SHORT is *fading the draw* (boosted). Symmetric in
        the **discount**. Mid-range is neutral. This is the reel's thesis encoded:
        external liquidity tells you where price wants to go — you fade it there.
        """
        if range_liq is None or not self.cfg.liquidity_magnet_enabled:
            return 0.0, ""
        h = range_liq.height
        if h <= 0:
            return 0.0, ""
        pos = (entry - range_liq.erl_low) / h  # 0 = at range low, 1 = at high
        prem = self.cfg.range_premium_frac
        boost = self.cfg.magnet_conviction_boost
        pen = self.cfg.magnet_chase_penalty
        if pos >= prem:  # premium — external draw is the buy-side pool above
            if direction == Direction.SHORT:
                return +boost, "fading the buy-side draw from premium"
            return -pen, "chasing a long into the buy-side draw (premium)"
        if pos <= (1.0 - prem):  # discount — external draw is the sell-side below
            if direction == Direction.LONG:
                return +boost, "fading the sell-side draw from discount"
            return -pen, "chasing a short into the sell-side draw (discount)"
        return 0.0, "mid-range (no draw bias)"

    def _level_context(
        self,
        bar: Bar,
        direction: Direction,
        atr: float,
        levels: list[LevelOfInterest],
        displacement: float,
    ) -> tuple[LevelOfInterest | None, bool]:
        """Return (nearest_level, is_breakout).

        A reaction is valid when price is at/near a marked level, OR when the
        just-closed bar broke through one with force (strong displacement and a
        close on the far side of the level in the trade direction).
        """
        if not levels or atr <= 0:
            return None, False
        proximity = self.cfg.level_proximity_atr_mult * atr

        # Nearest level to the bar close.
        nearest = min(levels, key=lambda lv: abs(lv.price - bar.close))
        if abs(nearest.price - bar.close) <= proximity:
            return nearest, False

        # Breakout: a level sits inside the bar range and we closed beyond it in
        # the trade direction, on a forceful (high-displacement) bar.
        if displacement >= 0.5:
            for lv in levels:
                crossed = bar.low <= lv.price <= bar.high
                if not crossed:
                    continue
                if direction == Direction.LONG and bar.close > lv.price:
                    return lv, True
                if direction == Direction.SHORT and bar.close < lv.price:
                    return lv, True
        return None, False

    # ------------------------------------------------------------------
    # Stop / target
    # ------------------------------------------------------------------

    def _stop(self, bars: list[Bar], direction: Direction, atr: float) -> float:
        bar = bars[-1]
        lb = max(2, self.cfg.momentum_lookback)
        window = bars[-lb:]
        buf = self.cfg.stop_buffer_pips * PIP
        atr_dist = self.cfg.stop_atr_mult * atr
        if direction == Direction.LONG:
            structural = min(b.low for b in window)
            atr_stop = bar.close - atr_dist
            return min(structural, atr_stop) - buf
        else:
            structural = max(b.high for b in window)
            atr_stop = bar.close + atr_dist
            return max(structural, atr_stop) + buf

    def _target(
        self,
        bars: list[Bar],
        at_index: int,
        direction: Direction,
        entry: float,
        stop: float,
        daily_levels: DailyLevels | None,
        swings: list[Swing] | None,
        htf_draw: float | None = None,
    ) -> tuple[float, str]:
        """Target the draw: prefer a fresh HTF zone the move is heading toward,
        then the next unswept PD-array / liquidity level; fall back to RR."""
        stop_dist = abs(entry - stop)
        # 1) A fresh higher-timeframe demand/supply zone ahead is the strongest
        #    draw (the daily zone the impulse is being pulled into).
        if htf_draw is not None and stop_dist > 0:
            ahead = (htf_draw > entry) if direction == Direction.LONG else (htf_draw < entry)
            if ahead and (abs(htf_draw - entry) / stop_dist) >= self.cfg.min_rr:
                return htf_draw, "htf_zone_draw"
        target = find_draw_on_liquidity(
            bars,
            at_index,
            direction,
            daily_levels=daily_levels,
            swings=swings,
            swept_lookback_bars=50,
        )
        if target is not None and stop_dist > 0:
            tp = target.price
            rr = (abs(tp - entry) / stop_dist)
            if rr >= self.cfg.min_rr:
                return tp, target.label
        # Fallback: fixed RR target.
        if direction == Direction.LONG:
            return entry + self.cfg.fallback_rr * stop_dist, "fallback_rr"
        return entry - self.cfg.fallback_rr * stop_dist, "fallback_rr"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        bars: list[Bar],
        *,
        atr: float,
        levels: list[LevelOfInterest] | None = None,
        anticipated_direction: Direction | None = None,
        daily_levels: DailyLevels | None = None,
        swings: list[Swing] | None = None,
        conviction_threshold: float | None = None,
        range_liq: RangeLiquidity | None = None,
        htf_target_long: float | None = None,
        htf_target_short: float | None = None,
        session_label: str | None = None,
    ) -> ReactionSignal | None:
        """Evaluate committed price action on the just-closed bar(s).

        `bars` are CLOSED bars (the live loop passes bars[:-1]); the last bar is
        the one we react to. Returns a :class:`ReactionSignal` or None.
        """
        return self.assess(
            bars,
            atr=atr,
            levels=levels,
            anticipated_direction=anticipated_direction,
            daily_levels=daily_levels,
            swings=swings,
            conviction_threshold=conviction_threshold,
            range_liq=range_liq,
            htf_target_long=htf_target_long,
            htf_target_short=htf_target_short,
            session_label=session_label,
        ).signal

    def assess(
        self,
        bars: list[Bar],
        *,
        atr: float,
        levels: list[LevelOfInterest] | None = None,
        anticipated_direction: Direction | None = None,
        daily_levels: DailyLevels | None = None,
        swings: list[Swing] | None = None,
        conviction_threshold: float | None = None,
        range_liq: RangeLiquidity | None = None,
        htf_target_long: float | None = None,
        htf_target_short: float | None = None,
        session_label: str | None = None,
    ) -> ReactionAssessment:
        """Like :meth:`evaluate` but always returns a full diagnostic, even when
        no signal fires (so the explainer can show the scores every bar)."""
        threshold = (
            conviction_threshold
            if conviction_threshold is not None
            else self.cfg.conviction_threshold
        )
        empty = ReactionComponents()

        if not self.cfg.enabled or len(bars) < 5 or atr <= 0:
            return ReactionAssessment(
                components=empty, conviction=0.0, agreement=0.0,
                threshold=threshold, direction=None, level=None,
                is_breakout=False, fired=False,
                rejection="insufficient data", signal=None,
            )

        comp = compute_components(bars, atr, self.cfg)
        if comp.direction is None:
            return ReactionAssessment(
                components=comp, conviction=0.0, agreement=0.0,
                threshold=threshold, direction=None, level=None,
                is_breakout=False, fired=False,
                rejection="no dominant direction", signal=None,
            )

        conviction, agreement = self._conviction(comp)

        # ERL draw bias: fade external draws, don't chase into them.
        draw_delta, draw_note = self._draw_bias(
            comp.direction, bars[-1].close, range_liq
        )
        if draw_delta:
            conviction = max(0.0, min(1.0, conviction + draw_delta))

        # Session is intentionally NOT folded into conviction here. In v2 it is
        # an explicit ablation axis (see docs/audit/preservation_list.md §I).
        # The `session_label` parameter is preserved for downstream tagging only.
        _ = session_label

        levels = levels or []
        nearest, is_breakout = self._level_context(
            bars[-1], comp.direction, atr, levels, comp.displacement
        )

        if conviction < threshold:
            return ReactionAssessment(
                components=comp, conviction=conviction, agreement=agreement,
                threshold=threshold, direction=comp.direction, level=nearest,
                is_breakout=is_breakout, fired=False,
                rejection=f"conviction {conviction:.2f} < {threshold:.2f}",
                signal=None,
            )

        # Is this a genuine impulse? A clean volatility-ignition move that may
        # fire WITHOUT an adjacent marked level (reacting to the move itself).
        is_impulse = (
            self.cfg.impulse_override_enabled
            and conviction >= self.cfg.impulse_min_conviction
            and comp.displacement >= self.cfg.impulse_min_displacement
            and comp.expansion >= self.cfg.impulse_min_expansion
        )

        if self.cfg.require_level and nearest is None and not is_impulse:
            return ReactionAssessment(
                components=comp, conviction=conviction, agreement=agreement,
                threshold=threshold, direction=comp.direction, level=None,
                is_breakout=False, fired=False,
                rejection="no level of interest at price (and not a clean impulse)",
                signal=None, is_impulse=False,
            )

        bar = bars[-1]
        entry = bar.close
        stop = self._stop(bars, comp.direction, atr)
        if abs(entry - stop) < PIP:  # degenerate stop
            return ReactionAssessment(
                components=comp, conviction=conviction, agreement=agreement,
                threshold=threshold, direction=comp.direction, level=nearest,
                is_breakout=is_breakout, fired=False,
                rejection="degenerate stop distance", signal=None,
                is_impulse=is_impulse,
            )
        htf_draw = (
            htf_target_long if comp.direction == Direction.LONG else htf_target_short
        )
        tp, target_label = self._target(
            bars, len(bars) - 1, comp.direction, entry, stop, daily_levels, swings,
            htf_draw=htf_draw,
        )

        signal = ReactionSignal(
            direction=comp.direction,
            conviction=conviction,
            components=comp,
            entry=entry,
            stop=stop,
            take_profit=tp,
            rationale="",
            level_label=nearest.label if nearest else "",
            level_kind=nearest.kind if nearest else "",
            is_breakout=is_breakout,
            is_impulse=is_impulse and nearest is None,
            target_label=target_label,
            agreement=agreement,
        )
        if signal.rr < self.cfg.min_rr:
            return ReactionAssessment(
                components=comp, conviction=conviction, agreement=agreement,
                threshold=threshold, direction=comp.direction, level=nearest,
                is_breakout=is_breakout, fired=False,
                rejection=f"R:R {signal.rr:.1f} < {self.cfg.min_rr}",
                signal=None, is_impulse=is_impulse,
            )
        signal.rationale = self._rationale(signal, anticipated_direction)
        return ReactionAssessment(
            components=comp, conviction=conviction, agreement=agreement,
            threshold=threshold, direction=comp.direction, level=nearest,
            is_breakout=is_breakout, fired=True, rejection="", signal=signal,
            is_impulse=is_impulse and nearest is None,
        )

    def _rationale(
        self, sig: ReactionSignal, anticipated_direction: Direction | None
    ) -> str:
        dir_label = "BUY" if sig.direction == Direction.LONG else "SELL"
        parts = [
            f"{dir_label} reaction (conviction {sig.conviction:.2f}, "
            f"agreement {sig.agreement:.2f}): {sig.component_summary()}."
        ]
        if sig.level_label:
            verb = "breaking through" if sig.is_breakout else "reacting at"
            parts.append(f"Price {verb} {sig.level_label} [{sig.level_kind}].")
        elif sig.is_impulse:
            parts.append(
                "Reacting to a clean impulse in open space (displacement + "
                "volatility ignition) — no adjacent level required."
            )
        parts.append(
            f"Target {sig.target_label} @ {sig.take_profit:.5f} "
            f"(R:R 1:{sig.rr:.1f}, stop {sig.stop_pips:.0f}p)."
        )
        if (
            anticipated_direction is not None
            and anticipated_direction != sig.direction
        ):
            parts.append(
                "FLIP: dominant momentum opposes the anticipated bias — "
                "abandoning the anticipated setup."
            )
        return " ".join(parts)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
