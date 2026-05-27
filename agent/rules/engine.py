"""Confluence rule engine. Combines detector outputs into Setups gated by confluence count.

Two evaluation modes:
  - evaluate(bars, i):       slow path. Runs all detectors on bars[:i+1] from scratch.
  - evaluate_precomputed():  fast path. Uses structures detected ONCE on the full series,
                              filtering them to "as-of" decision bar i. Use this in backtests."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from agent.config import Config, GATE_PROFILES, GATE_PROFILE_DEFAULT, GateProfile
from agent.detectors.atr import atr
from agent.detectors.bos import detect_bos, latest_bos
from agent.detectors.daily_levels import DailyLevels, compute_daily_levels, nearest_level
from agent.detectors.fib import auto_fib
from agent.detectors.fvg import detect_fvgs
from agent.detectors.liquidity import detect_liquidity_wicks
from agent.detectors.liquidity_sweep import LiquiditySweep, detect_liquidity_sweeps
from agent.detectors.liquidity_zones import LiquidityZone, detect_liquidity_zones
from agent.detectors.range_phase import RangePhase, label_range_phases
from agent.detectors.sessions import is_kill_zone, label_bars
from agent.detectors.swings import detect_swings, last_swing
from agent.detectors.trendlines import fit_trendlines
from agent.detectors.zones import detect_zones, detect_qualified_zones, fresh_zones
from agent.rules.filters import in_no_trade_window, is_no_trade_day
from agent.rules.htf_bias import HTFBias, HTFBiasComputer
from agent.types import Bar, BreakOfStructure, Direction, FVG, FibLevel, LiquidityWick, Setup, Trendline, Zone
from agent.utils import to_pips

log = logging.getLogger(__name__)


@dataclass
class PrecomputedContext:
    """Detector outputs computed once over the full bar series. Slice by index at decision time."""
    bars: list[Bar]
    zones: list[Zone] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    bos_list: list[BreakOfStructure] = field(default_factory=list)
    trendlines: list[Trendline] = field(default_factory=list)
    wicks: list[LiquidityWick] = field(default_factory=list)
    fib_by_index: dict[int, FibLevel] = field(default_factory=dict)
    atr_by_index: dict[int, float] = field(default_factory=dict)
    # New ICT-style context tracks added in the "trader-partner" iteration:
    daily_levels: list[DailyLevels] = field(default_factory=list)
    liquidity_sweeps: list[LiquiditySweep] = field(default_factory=list)
    range_phases: list[RangePhase] = field(default_factory=list)
    session_labels: list[str] = field(default_factory=list)
    liquidity_zones: list[LiquidityZone] = field(default_factory=list)
    swings: list = field(default_factory=list)
    qualified_zones: list = field(default_factory=list)


def _tf_scale(bars: list[Bar]) -> float:
    """Scale absolute pip thresholds by timeframe.
    Config defaults are calibrated for D1 (~80 pip ATR). Lower timeframes have proportionally
    smaller bar ranges, so detectors set to D1 thresholds find almost nothing on H1/M15."""
    if not bars:
        return 1.0
    tf = bars[0].timeframe.value
    return {"D1": 1.0, "H4": 0.5, "H1": 0.25, "M15": 0.12, "M5": 0.08, "M1": 0.04}.get(tf, 1.0)


def precompute(bars: list[Bar], cfg: Config, fib_recompute_every: int = 25) -> PrecomputedContext:
    """Compute all detectors once over the full bar series.
    Fib is recomputed every N bars (it depends on the most recent swings, which change)."""
    ctx = PrecomputedContext(bars=bars)
    scale = _tf_scale(bars)
    ctx.zones = detect_zones(
        bars,
        min_impulse_pips=cfg.detectors.zone_min_impulse_pips * scale,
        max_age_bars=cfg.detectors.zone_max_age_bars,
    )
    ctx.qualified_zones = detect_qualified_zones(
        bars,
        min_impulse_pips=cfg.detectors.zone_min_impulse_pips * scale,
    )
    ctx.fvgs = detect_fvgs(bars, min_size_pips=cfg.detectors.fvg_min_size_pips * scale)
    ctx.bos_list = detect_bos(bars, swing_lookback=cfg.detectors.swing_lookback)
    ctx.trendlines = fit_trendlines(bars, swing_lookback=cfg.detectors.swing_lookback)
    ctx.wicks = detect_liquidity_wicks(bars, min_wick_ratio=cfg.detectors.liquidity_wick_min_ratio,
                                       swing_lookback=cfg.detectors.swing_lookback)

    # Fib needs to be "as of" each bar; recompute periodically to balance accuracy vs cost
    last_fib = None
    for i in range(0, len(bars), fib_recompute_every):
        last_fib = auto_fib(bars[: i + 1], swing_lookback=cfg.detectors.swing_lookback,
                            levels=tuple(cfg.detectors.fib_levels))
        ctx.fib_by_index[i] = last_fib

    # ATR rolling
    if len(bars) > 14:
        trs = [0.0]
        for i in range(1, len(bars)):
            h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        running = 0.0
        for i in range(len(bars)):
            window = trs[max(0, i - 13): i + 1]
            running = sum(window) / max(len(window), 1)
            ctx.atr_by_index[i] = running

    # New ICT-flavoured context. All read-only and per-bar so we can slice by index.
    ctx.session_labels = label_bars(bars)
    ctx.daily_levels = compute_daily_levels(bars)
    ctx.range_phases = label_range_phases(bars)
    # Liquidity sweeps don't need scaling — confirm_pips/buffer are already pip-denominated.
    # Skip on D1/H4 where the concept is less meaningful (PDH on a daily chart IS the chart).
    if bars and bars[0].timeframe.value in ("M1", "M5", "M15", "H1"):
        try:
            ctx.liquidity_sweeps = detect_liquidity_sweeps(
                bars,
                swing_lookback=cfg.detectors.swing_lookback,
                pierce_buffer_pips=1.0,
                confirm_pips=5.0,
                confirm_max_bars=3,
            )
        except Exception as e:  # detector noise on synthetic / very short series
            log.debug("liquidity_sweep precompute skipped: %s", e)
            ctx.liquidity_sweeps = []

    # Two-phase Liquidity Zones of Interest (LZI). Runs on M1-H4 timeframes.
    # The zones are created once; the strategy's evaluate() advances their state
    # machine (waiting → retesting → consumed → triggered) bar by bar.
    ctx.swings = detect_swings(bars, lookback=cfg.detectors.swing_lookback)
    if bars and bars[0].timeframe.value in ("M1", "M5", "M15", "H1", "H4"):
        try:
            tf_val = bars[0].timeframe.value
            liq_cfg = cfg.liquidity
            min_wick = (liq_cfg.min_wick_size_pips_h4
                        if tf_val in ("H4", "D1")
                        else liq_cfg.min_wick_size_pips_h1)
            ctx.liquidity_zones = detect_liquidity_zones(
                bars,
                swing_lookback=cfg.detectors.swing_lookback,
                min_wick_size_pips=min_wick,
                pierce_buffer_pips=1.0,
            )
        except Exception as e:
            log.debug("liquidity_zones precompute skipped: %s", e)
            ctx.liquidity_zones = []

    # Attach liquidity config so strategies can read TF-aware parameters
    ctx.liquidity_config = cfg.liquidity  # type: ignore[attr-defined]

    return ctx


class RuleEngine:
    def __init__(self, cfg: Config, htf_biases: list[HTFBiasComputer] | None = None):
        """`htf_biases` is an optional list of higher-timeframe bias computers (typically
        one for D1 and one for H4). They're only consulted when cfg.rules.htf_bias_mode
        is 'advisory' or 'strict'. Pass None for pure LTF-only evaluation."""
        self.cfg = cfg
        self.htf_biases = htf_biases or []

    def evaluate_precomputed(self, ctx: PrecomputedContext, at_index: int) -> Setup | None:
        if at_index < 50 or at_index >= len(ctx.bars):
            return None
        cur = ctx.bars[at_index]
        if in_no_trade_window(cur.time, self.cfg.session.no_trade_windows, self.cfg.session.timezone):
            return None
        if is_no_trade_day(cur.time, self.cfg.session.no_trade_days, self.cfg.session.timezone):
            return None

        # Age filter happens here (not in detector) so historical bars in a
        # multi-year backtest see zones from THEIR own past, not just the
        # last N bars of the input series. See `detect_zones()` docstring.
        zones = [
            z for z in ctx.zones
            if z.created_bar_index <= at_index
            and (at_index - z.created_bar_index) <= self.cfg.detectors.zone_max_age_bars
        ]
        fvgs = [f for f in ctx.fvgs if f.created_bar_index <= at_index]
        bos_list = [b for b in ctx.bos_list if b.broken_bar_index <= at_index]
        wicks = [w for w in ctx.wicks if w.bar_index <= at_index]
        trendlines = [tl for tl in ctx.trendlines if tl.anchors[-1].bar_index <= at_index]

        # nearest precomputed fib at or before at_index
        keys = [k for k in ctx.fib_by_index.keys() if k <= at_index]
        fib = ctx.fib_by_index[max(keys)] if keys else None

        a = ctx.atr_by_index.get(at_index, 0.0)

        # New ICT-flavoured slices
        daily_levels = ctx.daily_levels[at_index] if ctx.daily_levels and at_index < len(ctx.daily_levels) else None
        range_phase = ctx.range_phases[at_index] if ctx.range_phases and at_index < len(ctx.range_phases) else None
        session = ctx.session_labels[at_index] if ctx.session_labels and at_index < len(ctx.session_labels) else None
        # Sweeps in the recent window (only those whose CONFIRM bar is at or before now,
        # i.e. fully observable). 5-bar lookback is enough for "fresh" sweeps.
        recent_sweeps = [
            s for s in ctx.liquidity_sweeps
            if s.confirm_bar_index <= at_index and (at_index - s.sweep_bar_index) <= 5
        ]

        return self._build_best(
            ctx.bars, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a,
            daily_levels=daily_levels, range_phase=range_phase, session=session,
            recent_sweeps=recent_sweeps,
        )

    def evaluate(self, bars: list[Bar], at_index: int) -> Setup | None:
        """Slow path: detect from scratch on bars[:at_index+1]. Use precompute() + evaluate_precomputed()
        for backtests."""
        if at_index < 50:
            return None

        window = bars[: at_index + 1]
        cur = window[-1]

        if in_no_trade_window(cur.time, self.cfg.session.no_trade_windows, self.cfg.session.timezone):
            return None
        if is_no_trade_day(cur.time, self.cfg.session.no_trade_days, self.cfg.session.timezone):
            return None

        scale = _tf_scale(window)
        zones = detect_zones(
            window,
            min_impulse_pips=self.cfg.detectors.zone_min_impulse_pips * scale,
            max_age_bars=self.cfg.detectors.zone_max_age_bars,
        )
        # See evaluate_precomputed: age must be applied at use time. Slow path
        # always queries the latest bar so we filter relative to len(window)-1.
        zones = [
            z for z in zones
            if (at_index - z.created_bar_index) <= self.cfg.detectors.zone_max_age_bars
        ]
        fvgs = detect_fvgs(window, min_size_pips=self.cfg.detectors.fvg_min_size_pips * scale)
        bos_list = detect_bos(window, swing_lookback=self.cfg.detectors.swing_lookback)
        fib = auto_fib(window, swing_lookback=self.cfg.detectors.swing_lookback,
                       levels=tuple(self.cfg.detectors.fib_levels))
        trendlines = fit_trendlines(window, swing_lookback=self.cfg.detectors.swing_lookback)
        wicks = detect_liquidity_wicks(window, min_wick_ratio=self.cfg.detectors.liquidity_wick_min_ratio,
                                       swing_lookback=self.cfg.detectors.swing_lookback)
        a = atr(window, period=14)

        # ICT-flavoured context (slow path mirrors precompute's outputs)
        daily_levels_list = compute_daily_levels(window)
        daily_levels = daily_levels_list[-1] if daily_levels_list else None
        phases = label_range_phases(window)
        range_phase = phases[-1] if phases else None
        session_label_list = label_bars(window[-1:])
        session = session_label_list[0] if session_label_list else None
        recent_sweeps: list[LiquiditySweep] = []
        if window and window[0].timeframe.value in ("M1", "M5", "M15", "H1"):
            try:
                all_sweeps = detect_liquidity_sweeps(window)
                recent_sweeps = [s for s in all_sweeps if (at_index - s.sweep_bar_index) <= 5]
            except Exception:
                pass

        return self._build_best(
            window, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a,
            daily_levels=daily_levels, range_phase=range_phase, session=session,
            recent_sweeps=recent_sweeps,
        )

    def validate_setup_gates(
        self,
        setup: Setup,
        bars: list[Bar],
        at_index: int,
        profile: GateProfile | None = None,
    ) -> tuple[bool, str]:
        """Validate a pre-built setup (typically from a strategy) against
        the gate stack, gated by the supplied profile.

        Returns (passed, reason) where reason describes the first failed gate
        (empty string when passed is True).
        """
        if profile is None:
            profile = GATE_PROFILES.get(setup.strategy_name or "", GATE_PROFILE_DEFAULT)

        cur = bars[at_index]

        # --- Safety gates (always checked regardless of profile) ---
        if in_no_trade_window(cur.time, self.cfg.session.no_trade_windows, self.cfg.session.timezone):
            return False, "no_trade_window"
        if is_no_trade_day(cur.time, self.cfg.session.no_trade_days, self.cfg.session.timezone):
            return False, "no_trade_day"

        # --- Blocked hours ---
        if profile.check_blocked_hours:
            blocked_hours = set(
                profile.blocked_hours_override
                if profile.blocked_hours_override is not None
                else self.cfg.rules.blocked_hours_ny
            )
            if blocked_hours:
                try:
                    from zoneinfo import ZoneInfo
                    ny_hour = cur.time.astimezone(ZoneInfo("America/New_York")).hour
                    if ny_hour in blocked_hours:
                        return False, "blocked_hour"
                except Exception:
                    pass

        # --- Blocked sessions ---
        if profile.check_blocked_sessions:
            blocked = set(self.cfg.rules.blocked_session_tags)
            if blocked and any(c in blocked for c in setup.confluences):
                return False, "blocked_session"

        # --- Min confluences ---
        if profile.check_min_confluences:
            per_tf_min = self.cfg.rules.min_confluences_per_tf.get(
                cur.timeframe.value, self.cfg.rules.min_confluences
            )
            if len(setup.confluences) < per_tf_min:
                return False, "min_confluences"

        # --- Precision partner ---
        if profile.require_precision_partner:
            partner_set = set(self.cfg.rules.precision_partner_tags)
            if not any(c in partner_set for c in setup.confluences):
                return False, "precision_partner"

        # --- Structural anchor ---
        if profile.require_structural_anchor:
            anchor_set = set(self.cfg.rules.structural_anchor_tags)
            if not any(c in anchor_set for c in setup.confluences):
                return False, "structural_anchor"

        # --- BOS requires FVG or sweep ---
        if profile.require_fvg_or_sweep_with_bos and "bos" in setup.confluences:
            extras = {"fvg"} | {t for t in self.cfg.rules.precision_partner_tags
                                 if t.startswith("sweep_")}
            if not any(c in extras for c in setup.confluences):
                return False, "fvg_or_sweep_with_bos"

        # --- Stop bounds ---
        if profile.check_stop_bounds:
            atr_val = 0.0
            if hasattr(setup, "features") and setup.features:
                atr_val = setup.features.get("atr_pips", 0.0) / 10000.0
            if atr_val <= 0:
                atr_by_index = getattr(self, "_last_ctx_atr", {})
                atr_val = atr_by_index.get(at_index, 0.0)
            atr_pips = max(0.0, atr_val * 10000.0) if atr_val > 0 else 30.0
            min_stop = max(5.0, 0.05 * atr_pips)
            max_stop = max(200.0, 5.0 * atr_pips)
            if setup.stop_pips < min_stop or setup.stop_pips > max_stop:
                return False, "stop_bounds"

        # --- RR minimum ---
        if profile.check_rr_minimum:
            if setup.rr < self.cfg.rules.rr_min:
                return False, "rr_minimum"

        return True, ""

    def _build_best(self, bars, at_index, zones, fvgs, bos_list, fib, trendlines, wicks, a, *,
                    daily_levels=None, range_phase=None, session=None, recent_sweeps=None):
        long_setup = self._build(Direction.LONG, bars, at_index, zones, fvgs, bos_list,
                                  fib, trendlines, wicks, a,
                                  daily_levels=daily_levels, range_phase=range_phase,
                                  session=session, recent_sweeps=recent_sweeps or [])
        short_setup = self._build(Direction.SHORT, bars, at_index, zones, fvgs, bos_list,
                                   fib, trendlines, wicks, a,
                                   daily_levels=daily_levels, range_phase=range_phase,
                                   session=session, recent_sweeps=recent_sweeps or [])

        candidates = [s for s in (long_setup, short_setup) if s is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda s: len(s.confluences))

    def _build(
        self,
        direction: Direction,
        bars: list[Bar],
        at_index: int,
        zones,
        fvgs,
        bos_list,
        fib,
        trendlines,
        wicks,
        atr_value: float,
        *,
        daily_levels: DailyLevels | None = None,
        range_phase: RangePhase | None = None,
        session: str | None = None,
        recent_sweeps: list[LiquiditySweep] | None = None,
    ) -> Setup | None:
        cur = bars[at_index]
        confluences: list[str] = []

        # Volatility-aware tolerance (especially important on D1/H4).
        # Use max(15 pips, 0.2 * ATR) with a small floor.
        atr_pips = max(0.0, atr_value * 10000.0)
        tol_pips = max(15.0, 0.2 * atr_pips)
        tol = tol_pips * 0.0001

        bos = latest_bos([b for b in bos_list if b.direction == direction])
        if bos and (at_index - bos.broken_bar_index) <= 50:
            confluences.append("bos")

        fresh = fresh_zones([z for z in zones if z.direction == direction], at_index)
        zone = None
        for z in fresh[-5:]:
            # Trigger when price RANGE overlaps the zone, not only the close.
            if (cur.low <= z.top + tol) and (cur.high >= z.bottom - tol):
                zone = z
                confluences.append("zone")
                break

        active_fvg = None
        for f in fvgs[-20:]:
            if f.direction != direction or f.filled:
                continue
            if (cur.low <= f.top + tol) and (cur.high >= f.bottom - tol):
                active_fvg = f
                confluences.append("fvg")
                break

        active_fib = None
        if fib is not None and fib.direction == direction:
            for lvl, price in fib.levels.items():
                # Consider the fib "hit" if the bar range tagged it within tolerance.
                if (cur.low - tol) <= price <= (cur.high + tol):
                    active_fib = fib
                    confluences.append(f"fib_{int(lvl*1000)}")
                    break

        active_tl = None
        for tl in trendlines:
            if tl.direction != direction or not tl.valid:
                continue
            line_price = tl.price_at(at_index)
            if (cur.low - tol) <= line_price <= (cur.high + tol):
                active_tl = tl
                confluences.append("trendline")
                break

        active_wick = None
        for w in wicks[-10:]:
            if w.direction != direction:
                continue
            if (at_index - w.bar_index) > 30:
                continue
            wick_low = min(w.wick_top, w.wick_bottom)
            wick_high = max(w.wick_top, w.wick_bottom)
            if (cur.low <= wick_high + tol) and (cur.high >= wick_low - tol):
                active_wick = w
                confluences.append("liquidity_wick")
                break

        # ---- ICT context: daily levels, sweeps, sessions, range phases -----
        # These get tagged with their *source* timeframe in confluence_tfs so the
        # explainer renders e.g. "near_PDH (D1)" and "session_ny (M15)".
        ict_tfs: dict[str, str] = {}

        # Daily/weekly anchor levels — entry within tolerance of PDH/PDL/PDM/PWH/PWL.
        # These come from D1 data even when applied to a M15 setup, so tag with D1.
        if daily_levels is not None:
            near = nearest_level(daily_levels, cur.close, max_pips=max(8.0, tol_pips * 0.5))
            if near is not None:
                tag = f"near_{near[0]}"
                if tag not in confluences:
                    confluences.append(tag)
                ict_tfs[tag] = "D1"

        # Recent liquidity sweep aligned with our trade direction.
        #
        # Direction-semantics safeguard (added 2026-05-03 W18 H1 audit):
        # the detector classifies levels as upper/lower targets purely by
        # price position, not semantics. So when EURUSD has fallen well
        # below PWL, PWL becomes an *upper* target and a wick-through-PWL
        # bar can emit `sweep_PWL` with direction=SHORT (a "buyside sweep
        # of PWL"). That's mathematically correct (stops above PWL got
        # taken) but semantically misleading and produced -38p / -25p H1
        # losers in the W18 audit. We enforce ICT-style semantics here:
        #   * HIGH-type level (PDH/PWH/swing_high/equal_highs) -> SHORT only
        #   * LOW-type  level (PDL/PWL/swing_low/equal_lows)   -> LONG  only
        #   * MID-type  level (PDM/PWM)                        -> dropped
        #     (mid pivots aren't stop pools; sweeps through them were 0/3
        #     wins in the audit, -25p)
        HIGH_LEVELS = {"PDH", "PWH", "swing_high", "equal_highs"}
        LOW_LEVELS = {"PDL", "PWL", "swing_low", "equal_lows"}
        MID_LEVELS = {"PDM", "PWM"}
        for sw in recent_sweeps or []:
            if sw.direction != direction:
                continue
            label = sw.swept_label
            if label in MID_LEVELS:
                continue  # mid sweeps are noise, drop them
            if label in HIGH_LEVELS and direction != Direction.SHORT:
                continue
            if label in LOW_LEVELS and direction != Direction.LONG:
                continue
            tag = f"sweep_{label}"
            if tag not in confluences:
                confluences.append(tag)
            ict_tfs[tag] = cur.timeframe.value
            break  # one sweep tag is enough; multiples are redundant noise

        # Session label — always tagged when present; counts as confluence only
        # for kill-zone sessions (london / overlap / ny). Off-session is dropped
        # to discourage low-vol entries.
        if session:
            if is_kill_zone(session):
                tag = f"session_{session}"
                if tag not in confluences:
                    confluences.append(tag)
                ict_tfs[tag] = cur.timeframe.value

        # Range phase — distribution adds confluence; manipulation/accumulation
        # are recorded as advisory tags only (not counted toward min_confluences).
        # We surface them in confluence_tfs so the narrative still mentions the phase.
        phase_tag = None
        if range_phase is not None:
            phase_tag = f"phase_{range_phase.phase}"
            ict_tfs[phase_tag] = cur.timeframe.value
            if range_phase.phase == "distribution":
                confluences.append(phase_tag)
            # else: stored later only in confluence_tfs metadata for the narrative.

        required = self.cfg.rules.required_factors
        for r in required:
            if r == "zone" and zone is None:
                return None
            if r == "fib" and active_fib is None:
                return None
            if r == "bos" and bos is None:
                return None

        # Per-timeframe minimum confluence override (defaults to global).
        per_tf_min = self.cfg.rules.min_confluences_per_tf.get(
            cur.timeframe.value, self.cfg.rules.min_confluences
        )
        if len(confluences) < per_tf_min:
            return None

        max_conf = self.cfg.rules.max_confluences
        if max_conf > 0 and len(confluences) > max_conf:
            return None

        # Time-of-day filter (NY local). The session-overlap blocklist already
        # handles the worst chop window, but per-hour audits will surface
        # additional weak hours over time.
        blocked_hours = set(self.cfg.rules.blocked_hours_ny)
        if blocked_hours:
            try:
                from zoneinfo import ZoneInfo
                ny_hour = cur.time.astimezone(ZoneInfo("America/New_York")).hour
                if ny_hour in blocked_hours:
                    return None
            except Exception:
                pass

        # Precision gate: derived from the W18 detector audit. Setups whose
        # only confluence is a noisy base tag (zone, bos, fib_*) bleed pips on
        # average. Require at least one precision partner (FVG or a tagged
        # liquidity sweep) before letting them pass — these are the tags that
        # say price has *committed* to a direction, not just *visited* a level.
        if self.cfg.rules.require_precision_partner:
            partner_set = set(self.cfg.rules.precision_partner_tags)
            has_partner = any(c in partner_set for c in confluences)
            if not has_partner:
                return None

        # Structural-anchor gate (added 2026-05-03 from 3-year audit). Even
        # with a precision partner, setups missing a fib/phase/session anchor
        # bled pips because they were chasing impulsive moves into chop. The
        # anchor proves the trigger is occurring at a *meaningful* structural
        # location, not random noise.
        if self.cfg.rules.require_structural_anchor:
            anchor_set = set(self.cfg.rules.structural_anchor_tags)
            has_anchor = any(c in anchor_set for c in confluences)
            if not has_anchor:
                return None

        # BOS-only stacks were the second-worst bleeders. Require an FVG or
        # sweep specifically when BOS is in the stack (any other tag is fine).
        if self.cfg.rules.require_fvg_or_sweep_with_bos and "bos" in confluences:
            extras = {"fvg"} | {t for t in self.cfg.rules.precision_partner_tags
                                 if t.startswith("sweep_")}
            if not any(c in extras for c in confluences):
                return None

        # Session blocklist: by default the London-NY overlap window is dropped
        # because it returned -153 pips on 10 trades during W18.
        blocked = set(self.cfg.rules.blocked_session_tags)
        if blocked and any(c in blocked for c in confluences):
            return None

        if atr_value <= 0:
            return None

        if direction == Direction.LONG:
            stop_anchor = min(zone.bottom if zone else cur.low, cur.low)
            stop = stop_anchor - self.cfg.rules.stop_buffer_pips * 0.0001
            # For backtests, we fill on next bar open anyway; entry is a signal price.
            entry = cur.close
            tp = entry + (entry - stop) * self.cfg.rules.rr_min
        else:
            stop_anchor = max(zone.top if zone else cur.high, cur.high)
            stop = stop_anchor + self.cfg.rules.stop_buffer_pips * 0.0001
            entry = cur.close
            tp = entry - (stop - entry) * self.cfg.rules.rr_min

        # All native confluences (zone/fvg/bos/fib/trendline/wick) detected by this
        # engine instance came from the setup's own TF — tag them so the user knows
        # exactly which chart to look at for each signal.
        setup_tf = cur.timeframe.value
        confluence_tfs = {c: setup_tf for c in confluences}
        # Overlay ICT context tags with their proper source TF (D1 for daily levels,
        # setup TF for sweep/session/phase). overlay overrides duplicate keys.
        confluence_tfs.update(ict_tfs)
        # Stash phase_<phase> tag in confluence_tfs even if not counted, so the
        # narrative can render "phase: manipulation" without us having to count it
        # toward min_confluences.
        if phase_tag is not None and phase_tag not in confluence_tfs:
            confluence_tfs[phase_tag] = cur.timeframe.value

        setup = Setup(
            direction=direction,
            timeframe=cur.timeframe,
            detected_at=cur.time,
            detected_bar_index=at_index,
            entry=entry,
            stop=stop,
            take_profit=tp,
            confluences=confluences,
            confluence_tfs=confluence_tfs,
            zone=zone,
            fvg=active_fvg,
            fib=active_fib,
            bos=bos,
            trendline=active_tl,
            liquidity_wick=active_wick,
        )

        # Stop size bounds: D1/H4 structural stops can be much wider than intraday.
        # Use ATR-aware bounds rather than a hard-coded 200 pips.
        min_stop_pips = max(5.0, 0.05 * atr_pips)
        max_stop_pips = max(200.0, 5.0 * atr_pips)

        # Risk-aligned cap: optionally reject anything that wouldn't fit the live account.
        # Math: max_stop_pips_live = (live_min_balance * pct_floor) / (lot_min * pip_value).
        if self.cfg.rules.enforce_live_stop_cap:
            risk_cap = (
                self.cfg.rules.live_min_balance * self.cfg.risk.pct_floor
            ) / (self.cfg.risk.lot_min * self.cfg.backtest.pip_value_per_lot)
            max_stop_pips = min(max_stop_pips, risk_cap)

        if setup.stop_pips < min_stop_pips or setup.stop_pips > max_stop_pips:
            return None
        if setup.rr < self.cfg.rules.rr_min:
            return None

        # Higher-timeframe bias check. Either annotate (advisory) or reject (strict).
        # Skipped entirely on D1/H4 timeframes — they ARE the HTF, no point self-checking.
        mode = self.cfg.rules.htf_bias_mode
        if mode != "off" and self.htf_biases and cur.timeframe.value in ("M1", "M5", "M15", "H1"):
            agrees = True
            tags_with_tf: list[tuple[str, str]] = []  # (tag, source_tf)
            dir_str = "long" if direction == Direction.LONG else "short"
            for hb in self.htf_biases:
                bias = hb.bias_at(cur.time, current_price=cur.close)
                src = bias.source_tf or "?"
                if bias.direction is not None:
                    if bias.direction == direction:
                        tag = f"htf_bias_{dir_str}"
                        tags_with_tf.append((tag, src))
                    else:
                        agrees = False
                if direction == Direction.LONG and bias.in_demand_zone:
                    tags_with_tf.append(("htf_zone_long", src))
                if direction == Direction.SHORT and bias.in_supply_zone:
                    tags_with_tf.append(("htf_zone_short", src))

                # Cross-timeframe zone alignment: if the LTF entry zone overlaps
                # an HTF zone of the same direction, that's strong confluence.
                if zone is not None:
                    for hz in bias.htf_zones_near_price:
                        overlap = (
                            zone.bottom <= hz["top"] + tol
                            and zone.top >= hz["bottom"] - tol
                        )
                        if overlap and hz["direction"] == dir_str:
                            align_tag = f"htf_zone_align_{hz['source_tf']}"
                            if align_tag not in [t_[0] for t_ in tags_with_tf]:
                                tags_with_tf.append((align_tag, hz["source_tf"]))

                # Cross-timeframe FVG alignment: if the LTF entry price sits
                # inside an HTF FVG of the same direction, add confluence.
                for hf in bias.htf_fvgs_near_price:
                    if hf["direction"] != dir_str:
                        continue
                    price_in_fvg = hf["bottom"] <= cur.close <= hf["top"]
                    bar_touches_fvg = (
                        cur.low <= hf["top"] + tol
                        and cur.high >= hf["bottom"] - tol
                    )
                    if price_in_fvg or bar_touches_fvg:
                        fvg_tag = f"htf_fvg_align_{hf['source_tf']}"
                        if fvg_tag not in [t_[0] for t_ in tags_with_tf]:
                            tags_with_tf.append((fvg_tag, hf["source_tf"]))

            if mode == "strict" and not agrees:
                return None
            for t, src in tags_with_tf:
                if t not in setup.confluences:
                    setup.confluences.append(t)
                # Map each HTF tag to its source TF (D1 / H4) so the explainer
                # renders 'htf_bias_long (D1)' instead of just 'htf_bias_long'.
                setup.confluence_tfs[t] = src

        return setup
