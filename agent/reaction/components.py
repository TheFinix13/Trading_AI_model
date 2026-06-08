"""Measured commitment components for the reaction engine.

Every function here returns a score in [0, 1] derived from MEASURED facts about
the just-closed bar(s) — no predictions, no look-ahead. Direction-bearing
components also return a :class:`Direction` so the engine can vote on the
dominant side. Keep these pure and cheap: the engine runs them every bar.
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.config import ReactionConfig
from agent.types import Bar, Direction

PIP = 0.0001


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class ReactionComponents:
    """The four measured commitment scores plus the voted direction."""

    displacement: float = 0.0
    expansion: float = 0.0
    momentum: float = 0.0
    imbalance: float = 0.0

    direction: Direction | None = None
    # Per-component directional reads (None where a component is non-directional
    # or undecided). Used by the engine to compute directional agreement.
    displacement_dir: Direction | None = None
    momentum_dir: Direction | None = None
    imbalance_dir: Direction | None = None

    def as_dict(self) -> dict[str, float]:
        return {
            "displacement": round(self.displacement, 4),
            "expansion": round(self.expansion, 4),
            "momentum": round(self.momentum, 4),
            "imbalance": round(self.imbalance, 4),
        }


def displacement_score(
    bars: list[Bar], atr: float, cfg: ReactionConfig
) -> tuple[float, Direction | None]:
    """Body > ``displacement_atr_mult`` * ATR with a strong directional close.

    Returns (score, direction). Score scales with body/ATR (0.5 at exactly the
    threshold, 1.0 at twice the threshold) and is halved when the close is not
    in the top/bottom fraction of the bar range (weak/indecisive close).
    """
    if not bars or atr <= 0:
        return 0.0, None
    bar = bars[-1]
    rng = bar.range
    if rng <= 0:
        return 0.0, None

    body_ratio = bar.body / atr
    raw = body_ratio / (2.0 * cfg.displacement_atr_mult)
    score = _clamp(raw)

    # Close location within the bar range: 1.0 = closed on the high.
    close_loc = (bar.close - bar.low) / rng
    if bar.close >= bar.open:
        direction = Direction.LONG
        strong_close = close_loc >= cfg.displacement_close_frac
    else:
        direction = Direction.SHORT
        strong_close = close_loc <= (1.0 - cfg.displacement_close_frac)

    if not strong_close:
        score *= 0.5
    return score, direction


def range_expansion_score(bars: list[Bar], cfg: ReactionConfig) -> float:
    """Recent bar range vs the prior rolling average range (volatility ignition).

    Non-directional. Score is 0.5 at exactly ``expansion_mult`` and 1.0 at
    twice that ratio.
    """
    n_recent = max(1, cfg.expansion_bars)
    need = n_recent + cfg.expansion_lookback
    if len(bars) < need + 1:
        # Fall back to whatever history we have, but require at least a few bars.
        if len(bars) < n_recent + 3:
            return 0.0
    recent = bars[-n_recent:]
    prior = bars[-(n_recent + cfg.expansion_lookback): -n_recent]
    if not prior:
        prior = bars[:-n_recent] or recent
    cur_range = max(b.range for b in recent)
    avg_range = sum(b.range for b in prior) / len(prior)
    if avg_range <= 0:
        return 0.0
    ratio = cur_range / avg_range
    return _clamp(ratio / (2.0 * cfg.expansion_mult))


def momentum_score(
    bars: list[Bar], atr: float, cfg: ReactionConfig
) -> tuple[float, Direction | None]:
    """Rate-of-change normalised by ATR, blended with consecutive directional closes.

    Returns (score, direction).
    """
    lb = cfg.momentum_lookback
    if len(bars) < lb + 1 or atr <= 0:
        return 0.0, None

    roc = bars[-1].close - bars[-1 - lb].close
    roc_score = _clamp(abs(roc) / (atr * cfg.momentum_atr_norm))

    direction = Direction.LONG if roc > 0 else (Direction.SHORT if roc < 0 else None)
    if direction is None:
        return 0.0, None

    # Count consecutive closes in the dominant direction (most recent first).
    consec = 0
    for i in range(len(bars) - 1, 0, -1):
        up = bars[i].close > bars[i - 1].close
        if (direction == Direction.LONG and up) or (
            direction == Direction.SHORT and not up
        ):
            consec += 1
        else:
            break
    consec_score = _clamp(consec / lb)

    score = 0.65 * roc_score + 0.35 * consec_score
    return _clamp(score), direction


def imbalance_score(
    bars: list[Bar], cfg: ReactionConfig
) -> tuple[float, Direction | None]:
    """Order-flow imbalance proxy from a single bar (no true tick delta).

    Blends three measured signals:
      (a) close location within the bar range (close near high = buy pressure),
      (b) wick asymmetry (small wick in trade direction, long opposite wick),
      (c) tick volume rising on a directional bar (if available/enabled).

    Returns (score, direction).
    """
    if not bars:
        return 0.0, None
    bar = bars[-1]
    rng = bar.range
    if rng <= 0:
        return 0.0, None

    close_loc = (bar.close - bar.low) / rng  # 0 = on low, 1 = on high
    direction = Direction.LONG if close_loc >= 0.5 else Direction.SHORT

    # (a) Close-location pressure mapped to [0, 1] for the chosen direction.
    cp = close_loc if direction == Direction.LONG else (1.0 - close_loc)
    cp_score = _clamp((cp - 0.5) * 2.0)

    # (b) Wick asymmetry: for a buy, a long lower wick (demand absorbed) and a
    # small upper wick (little supply rejection) is bullish, and vice-versa.
    upper, lower = bar.upper_wick, bar.lower_wick
    total_wick = upper + lower
    if total_wick > 0:
        if direction == Direction.LONG:
            wick_score = lower / total_wick
        else:
            wick_score = upper / total_wick
    else:
        wick_score = 0.5
    wick_score = _clamp((wick_score - 0.5) * 2.0)

    # (c) Tick-volume confirmation.
    vol_score = 0.5
    if cfg.imbalance_use_volume and len(bars) > cfg.imbalance_volume_lookback:
        window = bars[-(cfg.imbalance_volume_lookback + 1): -1]
        avg_vol = sum(b.volume for b in window) / max(1, len(window))
        if avg_vol > 0:
            vol_score = _clamp((bar.volume / avg_vol) - 1.0)
        else:
            vol_score = 0.5

    score = 0.5 * cp_score + 0.3 * wick_score + 0.2 * vol_score
    return _clamp(score), direction


def compute_components(
    bars: list[Bar], atr: float, cfg: ReactionConfig
) -> ReactionComponents:
    """Run all four measured components and vote on the dominant direction."""
    disp, disp_dir = displacement_score(bars, atr, cfg)
    exp = range_expansion_score(bars, cfg)
    mom, mom_dir = momentum_score(bars, atr, cfg)
    imb, imb_dir = imbalance_score(bars, cfg)

    # Weighted directional vote: each directional component contributes its
    # (weight * score) to the side it reads.
    long_w = 0.0
    short_w = 0.0
    for dir_, w, s in (
        (disp_dir, cfg.weight_displacement, disp),
        (mom_dir, cfg.weight_momentum, mom),
        (imb_dir, cfg.weight_imbalance, imb),
    ):
        if dir_ == Direction.LONG:
            long_w += w * s
        elif dir_ == Direction.SHORT:
            short_w += w * s

    if long_w == 0.0 and short_w == 0.0:
        direction = None
    else:
        direction = Direction.LONG if long_w >= short_w else Direction.SHORT

    return ReactionComponents(
        displacement=disp,
        expansion=exp,
        momentum=mom,
        imbalance=imb,
        direction=direction,
        displacement_dir=disp_dir,
        momentum_dir=mom_dir,
        imbalance_dir=imb_dir,
    )
