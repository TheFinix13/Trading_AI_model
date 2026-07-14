"""F20 -- Agent-owned SL/TP shape cognition.

Doctrine 06 v0.5 section 4.1a. Each v1 agent implements a non-trivial
`risk_intent(conviction, atr_pips, h1_swing_pips) -> (sl_pips, tp_ladder)`.
Different playstyles produce different SL/TP shapes.

## The three shipped implementations

- ``default_risk_intent``: returns ``(40.0, [80.0])`` -- 1:2 R:R single
  TP. Backwards-compat only; any agent still using this after G7 fires
  FAILS §3.11.5 criterion #6.
- ``atr_scaled_risk_intent``: SL = ``atr_mult × ATR``, TP = ``payoff × SL``.
  Baseline for Isagi + Nagi (structural-cleanliness-driven).
- ``playstyle_risk_intent``: table-lookup on ``playstyle`` -> shared
  building block with per-playstyle parameters.

## Ladder shape

A ladder is a list of TP pip distances (positive numbers, in trade
direction). ``[80.0]`` = single TP at 80 pips; ``[50, 100, 150]`` =
three partial exits at 50/100/150 pips. Fractions per rung are set by
the caller in `LadderRung.fraction`; this fn returns only the pip
distances. Ladder must sum to 1.0 in fractions per `AgentProposal`
validation (`sim/core/types.py`).

## Sandbox constraints

Sentinel R1 blocks trades with SL such that risk > 5 % of equity at
lot=MIN_LOT. In the $100 / 1:1000 sandbox that caps SL at ~50 pips
regardless of what F20 returns. Agents should not routinely return
SLs beyond 50 pips; the risk_intent output is a *desire* the Sentinel
can veto.
"""
from __future__ import annotations

from typing import Callable

from agent.squad.lot_intent import Playstyle

# Default SL/TP shape (used only for backwards-compat pre-F20 agents).
DEFAULT_SL_PIPS = 40.0
DEFAULT_TP_LADDER = (80.0,)


RiskIntent = Callable[[float, float, float], tuple[float, list[float]]]
"""F20 callable signature: (conviction, atr_pips, h1_swing_pips) -> (sl_pips, tp_ladder)."""


# ---------------------------------------------------------------------------
# Default (fixed 40-pip / 80-pip TP) -- v1 checkpoint FALLBACK, not valid v1
# ---------------------------------------------------------------------------

def default_risk_intent(
    conviction: float,           # noqa: ARG001
    atr_pips: float,             # noqa: ARG001
    h1_swing_pips: float,        # noqa: ARG001
) -> tuple[float, list[float]]:
    """Returns (40.0, [80.0]) unconditionally.

    Any agent still using this after G7 FAILS §3.11.5 criterion #6
    (SL cv or TP[0] cv must be >= 0.10).
    """
    return DEFAULT_SL_PIPS, list(DEFAULT_TP_LADDER)


# ---------------------------------------------------------------------------
# Shared building block: ATR-scaled SL with payoff-ratio TP
# ---------------------------------------------------------------------------

def atr_scaled_risk_intent(
    conviction: float,
    atr_pips: float,
    h1_swing_pips: float,
    *,
    atr_multiplier: float = 1.5,
    payoff_ratio: float = 2.0,
    sl_pips_min: float = 15.0,
    sl_pips_max: float = 50.0,
    tp_ladder_style: str = "single",   # "single" | "partial_50_100"
) -> tuple[float, list[float]]:
    """SL scales with realised ATR; TP scales with SL by payoff_ratio.

    - SL = clip(atr_multiplier * atr_pips, sl_pips_min, sl_pips_max)
    - TP1 = payoff_ratio * SL
    - Multi-partial ladders: 0.5×TP1, 1.0×TP1, 1.5×TP1 (or similar)

    ``conviction`` and ``h1_swing_pips`` are accepted for the interface
    but not consumed here -- see ``kelly_conditioned_risk_intent`` for
    the conviction-aware variant.

    Guards: if ATR is missing / zero (e.g. warmup bars), returns
    (sl_pips_min, [sl_pips_min * payoff_ratio]).
    """
    if atr_pips <= 0:
        sl = sl_pips_min
    else:
        sl = max(sl_pips_min, min(sl_pips_max, atr_multiplier * atr_pips))
    tp1 = payoff_ratio * sl
    if tp_ladder_style == "partial_50_100":
        ladder = [tp1 * 0.5, tp1 * 1.0, tp1 * 1.5]
    else:
        ladder = [tp1]
    return sl, ladder


# ---------------------------------------------------------------------------
# Shared building block: structural SL (Fib/harmonic) + Fibonacci TP ladder
# ---------------------------------------------------------------------------

def structural_risk_intent(
    conviction: float,           # noqa: ARG001
    atr_pips: float,             # noqa: ARG001
    h1_swing_pips: float,
    *,
    sl_swing_fraction: float = 0.30,
    sl_pips_min: float = 15.0,
    sl_pips_max: float = 30.0,
    tp_multipliers: tuple[float, ...] = (2.0, 4.0, 6.0),
) -> tuple[float, list[float]]:
    """SL below the source swing by ``sl_swing_fraction`` × swing pips.

    Used by Rin (analytical precision): SL is a fraction of the H1
    source swing (typically 0.30 × swing), and TPs are Fibonacci-like
    multiples of SL. Clipping to sandbox min/max applies.

    - SL = clip(sl_swing_fraction * h1_swing_pips, sl_pips_min, sl_pips_max)
    - TP ladder = [m × SL for m in tp_multipliers]

    If ``h1_swing_pips`` is missing / zero, uses ``sl_pips_min``.
    """
    if h1_swing_pips <= 0:
        sl = sl_pips_min
    else:
        sl = max(sl_pips_min, min(sl_pips_max, sl_swing_fraction * h1_swing_pips))
    ladder = [m * sl for m in tp_multipliers]
    return sl, ladder


# ---------------------------------------------------------------------------
# Playstyle dispatch
# ---------------------------------------------------------------------------

def playstyle_risk_intent(
    conviction: float,
    atr_pips: float,
    h1_swing_pips: float,
    *,
    playstyle: Playstyle,
) -> tuple[float, list[float]]:
    """Table-lookup on ``playstyle`` -> shared building block.

    Locked at v0.5; any parameter change is a §11 amendment.
    """
    if playstyle == "conservative_metavision":
        # Isagi: wide-stop zone-fade shape -- SL ≈ 40, TP1 ≈ 60.
        #
        # Dispersion-r2 (2026-07-14, doctrine §4.1a amendment): the
        # original damped anchor (0.25× ATR sensitivity) produced CV
        # 0.083 < 0.10 in G7 §11.13. Replaced with full ATR
        # proportionality: 1.3 × panel-mean ATR (~30 pips) ≈ 39 keeps
        # the doctrine anchor "SL ≈ 40"; 1.3 is the multiplier already
        # shipped for confluence_only / copier_hrp, not a new number.
        # Payoff 1.5 preserves the ~60-pip TP1 anchor.
        return atr_scaled_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            atr_multiplier=1.3, payoff_ratio=1.5,
            sl_pips_min=30.0, sl_pips_max=50.0,
        )
    if playstyle == "rebel_tight":
        # Bachira: tight-stop-wide-TP pattern shape -- SL ≈ 20, TP1 ≈ 60.
        return atr_scaled_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            atr_multiplier=0.8, payoff_ratio=3.0,
            sl_pips_min=15.0, sl_pips_max=25.0,
        )
    if playstyle == "analytical_precision":
        # Rin: structural SL, Fibonacci TP ladder [2x, 4x, 6x].
        #
        # Dispersion-r2 (2026-07-14, doctrine §4.1a amendment): G7
        # §11.13 published mean SL 29.18 vs ceiling 30 -- the 0.30 ×
        # swing map was pinned at the clip ceiling and the structural
        # signal was saturated away (CV 0.086). De-saturated: fraction
        # 0.20 maps the banked typical H4 20-bar swing (~125-140 pips)
        # to ≈ 25-28, restoring the doctrine anchor "SL ≈ 25" INSIDE
        # the band; ceiling lifted to 35. Min and TP ladder unchanged.
        return structural_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            sl_swing_fraction=0.20,
            sl_pips_min=15.0, sl_pips_max=35.0,
            tp_multipliers=(2.0, 4.0, 6.0),
        )
    if playstyle == "speed_momentum":
        # Chigiri: tight-trailing-stop shape -- SL ≈ 30, TP1 ≈ 90 (payoff 3x).
        return atr_scaled_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            atr_multiplier=1.2, payoff_ratio=3.0,
            sl_pips_min=20.0, sl_pips_max=40.0,
        )
    if playstyle == "copier_hrp":
        # Reo: HRP-weighted mixture of top-K peer risk intents.
        # Reo's agent class computes the mixture and calls this fn
        # with the mixed conviction; this fn returns a mean SL/TP.
        return atr_scaled_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            atr_multiplier=1.3, payoff_ratio=2.0,
            sl_pips_min=20.0, sl_pips_max=45.0,
        )
    if playstyle == "confluence_only":
        # Nagi: structural-cleanliness-driven SL/TP -- SL ≈ 30, TP1 ≈ 90.
        # Larger lot on 2+ peer overlap is handled in lot_intent, not here.
        return atr_scaled_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            atr_multiplier=1.3, payoff_ratio=3.0,
            sl_pips_min=20.0, sl_pips_max=40.0,
            tp_ladder_style="partial_50_100",
        )
    if playstyle == "solo_king":
        # Barou: tight-stop-wide-TP baseline-zone shape -- SL ≈ 30, TP ladder [50, 100].
        return structural_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            sl_swing_fraction=0.25,
            sl_pips_min=20.0, sl_pips_max=35.0,
            tp_multipliers=(1.5, 3.0),
        )
    if playstyle == "defensive":
        # Kunigami: standard 40-pip SL; warning fires -> refuse (handled elsewhere).
        return atr_scaled_risk_intent(
            conviction, atr_pips, h1_swing_pips,
            atr_multiplier=1.5, payoff_ratio=1.5,
            sl_pips_min=25.0, sl_pips_max=45.0,
        )
    # Unknown -> default.
    return default_risk_intent(conviction, atr_pips, h1_swing_pips)


__all__ = [
    "DEFAULT_SL_PIPS",
    "DEFAULT_TP_LADDER",
    "RiskIntent",
    "default_risk_intent",
    "atr_scaled_risk_intent",
    "structural_risk_intent",
    "playstyle_risk_intent",
]
