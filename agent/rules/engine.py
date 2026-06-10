"""Detector precompute pipeline — the perception backbone for v2 alphas.

What's left after the v2 reset:

* :class:`PrecomputedContext` — a per-bar-series structure carrying every
  detector output an Alpha may want to read.
* :func:`precompute` — runs each surviving detector exactly once over the
  series so chunked alpha backtests share work.

What was burned (see `docs/audit/redundancy_map.md`):

* The legacy ``RuleEngine.evaluate_*`` v1 confluence-stack scorer, with its
  dev-span-fitted `GATE_PROFILES`, `MLConfig.scorer_paths`, and the
  ``validate_setup_gates`` ladder of 20+ knobs.
* The shared ``ctx.wicks`` (``detect_liquidity_wicks``) — superseded by
  the tagged ``ctx.liquidity_sweeps``.
* `ctx.liquidity_zones` (LZI two-phase choreography) and the v1 strategy
  router — both were tied to BURN strategy classes.
* `ctx.qualified_zones` and `ctx.range_phases` — the v2 alphas that need
  them will reintroduce them through their own causal helpers (the broad
  zone band is still produced via ``detect_zones``).

Causality contract: precompute may scan the whole series to find detector
*existence*, but per-bar **state** (FVG fill %, sweep reversal confirmation,
trendline validity) must be re-derived causally by the alpha at each
decision bar — see `_CausalFVGTracker` in `agent/alphas/backtest.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from agent.config import Config
from agent.detectors.bos import detect_bos
from agent.detectors.daily_levels import DailyLevels, compute_daily_levels
from agent.detectors.fvg import detect_fvgs
from agent.detectors.liquidity_sweep import LiquiditySweep, detect_liquidity_sweeps
from agent.detectors.sessions import label_bars
from agent.detectors.swings import detect_swings
from agent.detectors.trendlines import fit_trendlines
from agent.detectors.zones import detect_zones
from agent.types import Bar, BreakOfStructure, FVG, FibLevel, Trendline, Zone

log = logging.getLogger(__name__)


@dataclass
class PrecomputedContext:
    """Detector outputs computed once over the full bar series. Slice by index at decision time."""
    bars: list[Bar]
    zones: list[Zone] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    bos_list: list[BreakOfStructure] = field(default_factory=list)
    trendlines: list[Trendline] = field(default_factory=list)
    fib_by_index: dict[int, FibLevel] = field(default_factory=dict)
    atr_by_index: dict[int, float] = field(default_factory=dict)
    daily_levels: list[DailyLevels] = field(default_factory=list)
    liquidity_sweeps: list[LiquiditySweep] = field(default_factory=list)
    session_labels: list[str] = field(default_factory=list)
    swings: list = field(default_factory=list)


def _tf_scale(bars: list[Bar]) -> float:
    """Scale absolute pip thresholds by timeframe.
    Config defaults are calibrated for D1 (~80 pip ATR). Lower timeframes have
    proportionally smaller bar ranges, so detectors set to D1 thresholds find
    almost nothing on H1/M15."""
    if not bars:
        return 1.0
    tf = bars[0].timeframe.value
    return {"D1": 1.0, "H4": 0.5, "H1": 0.25, "M15": 0.12,
            "M5": 0.08, "M3": 0.06, "M1": 0.04}.get(tf, 1.0)


def precompute(bars: list[Bar], cfg: Config, fib_recompute_every: int = 25) -> PrecomputedContext:
    """Compute the perception surface once over the full bar series.

    FVG fill state is intentionally NOT computed here — Alphas must re-derive
    it causally via ``_CausalFVGTracker``.

    ``fib_by_index`` was previously populated every ``fib_recompute_every``
    bars via ``auto_fib(bars[:i+1])`` — an O(N²/step) walk that dominated M15
    precompute (~10 min on 272k bars). The only consumer was ``FibAlpha``,
    which was retired in the v3 cuts. ``fib_recompute_every`` is kept in the
    signature for backward compatibility with downstream callers but has no
    effect; populate ``fib_by_index`` lazily in callers that need it.
    """
    ctx = PrecomputedContext(bars=bars)
    scale = _tf_scale(bars)

    ctx.zones = detect_zones(
        bars,
        min_impulse_pips=cfg.detectors.zone_min_impulse_pips * scale,
        max_age_bars=cfg.detectors.zone_max_age_bars,
    )
    ctx.fvgs = detect_fvgs(bars, min_size_pips=cfg.detectors.fvg_min_size_pips * scale)
    ctx.bos_list = detect_bos(bars, swing_lookback=cfg.detectors.swing_lookback)
    ctx.trendlines = fit_trendlines(bars, swing_lookback=cfg.detectors.swing_lookback)
    ctx.swings = detect_swings(bars, lookback=cfg.detectors.swing_lookback)

    if len(bars) > 14:
        trs = [0.0]
        for i in range(1, len(bars)):
            h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        for i in range(len(bars)):
            window = trs[max(0, i - 13): i + 1]
            ctx.atr_by_index[i] = sum(window) / max(len(window), 1)

    ctx.session_labels = label_bars(bars)
    ctx.daily_levels = compute_daily_levels(bars)

    # Liquidity sweeps default to fully-causal mode (no forward reversal
    # confirmation) so the precomputed list isn't survivor-biased. The alphas
    # that need confirmation should call ``confirm_reversal_at`` themselves.
    if bars and bars[0].timeframe.value in ("M1", "M3", "M5", "M15", "H1"):
        try:
            ctx.liquidity_sweeps = detect_liquidity_sweeps(
                bars,
                swing_lookback=cfg.detectors.swing_lookback,
                pierce_buffer_pips=1.0,
            )
        except Exception as e:
            log.debug("liquidity_sweep precompute skipped: %s", e)

    return ctx
