"""Adapter: wrap the present-time `ReactionEngine` as an `Alpha`.

The reaction engine reacts to committed price action (displacement, expansion,
momentum, order-flow imbalance) at/near marked levels. As an isolated alpha its
level set is built causally from daily anchors + recent swings (no HTF multi-TF
dependency, so it runs on a single H1 series like the other alphas).

The ``erl_irl`` variant is the **quarantined** ERL/IRL liquidity-magnet concept
(docs/10 §10.6): it gets a fair standalone OOS scorecard here before any verdict.
"""
from __future__ import annotations

from typing import Optional

from agent.alphas.base import Alpha, AlphaContext, AlphaSignal
from agent.config import Config, ReactionConfig
from agent.detectors.liquidity_magnet import compute_range_liquidity
from agent.reaction.engine import LevelOfInterest, ReactionEngine


class ReactionAlpha(Alpha):
    def __init__(self, cfg: Config, *, name: str = "reaction",
                 use_erl_irl: bool = False, use_htf_draws: bool = False,
                 swing_window: int = 60):
        self.name = name
        self.description = "present-time reaction engine"
        self._swing_window = swing_window
        self._use_erl_irl = use_erl_irl
        self._use_htf_draws = use_htf_draws
        # Causal HTF demand/supply draws, keyed by bar time. Injected by the
        # evaluation harness (built once over the FULL series so the deep daily
        # lookback survives chunk-slicing). See agent/context/htf_draws.py.
        self._htf_draws: dict | None = None
        rcfg = cfg.reaction.model_copy(deep=True) if hasattr(cfg.reaction, "model_copy") \
            else ReactionConfig(**cfg.reaction.__dict__)
        if use_erl_irl:
            rcfg.liquidity_magnet_enabled = True
            self.description = "reaction engine + ERL/IRL liquidity magnets (quarantined)"
        if use_htf_draws:
            self.description += " + deep HTF zone draws"
        self._engine = ReactionEngine(rcfg)

    def set_htf_draws(self, draws: dict | None) -> None:
        """Inject the precomputed (time → (supply_above, demand_below)) map."""
        self._htf_draws = draws

    def _levels(self, actx: AlphaContext, i: int) -> list[LevelOfInterest]:
        bars = actx.bars
        ctx = actx.ctx
        levels: list[LevelOfInterest] = []
        if ctx.daily_levels and i < len(ctx.daily_levels):
            try:
                for label, price in ctx.daily_levels[i].levels_dict().items():
                    if price:
                        levels.append(LevelOfInterest(price, label, "daily"))
            except Exception:
                pass
        window = bars[max(0, i - self._swing_window):i]
        if window:
            levels.append(LevelOfInterest(max(b.high for b in window), "recent_high", "swing"))
            levels.append(LevelOfInterest(min(b.low for b in window), "recent_low", "swing"))
        return levels

    def signal(self, actx: AlphaContext, i: int) -> Optional[AlphaSignal]:
        ctx = actx.ctx
        atr = ctx.atr_by_index.get(i, 0.0)
        if atr <= 0:
            return None
        bars_upto = actx.bars[: i + 1]
        daily = ctx.daily_levels[i] if (ctx.daily_levels and i < len(ctx.daily_levels)) else None
        range_liq = None
        if self._use_erl_irl:
            range_liq = compute_range_liquidity(
                actx.bars, i,
                lookback_bars=actx.cfg.reaction.range_lookback_bars,
                swings=ctx.swings,
            )
        session_label = (
            ctx.session_labels[i]
            if getattr(ctx, "session_labels", None) and i < len(ctx.session_labels)
            else None
        )
        htf_long = htf_short = None
        if self._use_htf_draws and self._htf_draws:
            pair = self._htf_draws.get(actx.bars[i].time)
            if pair is not None:
                htf_long, htf_short = pair  # (supply above, demand below)
        sig = self._engine.evaluate(
            bars_upto, atr=atr, levels=self._levels(actx, i),
            daily_levels=daily, swings=ctx.swings, range_liq=range_liq,
            session_label=session_label,
            htf_target_long=htf_long, htf_target_short=htf_short,
        )
        if sig is None:
            return None
        return AlphaSignal(
            direction=sig.direction, entry=sig.entry, stop=sig.stop,
            take_profit=sig.take_profit, reason=getattr(sig, "target_label", self.name),
            conviction=getattr(sig, "conviction", 1.0),
        )
