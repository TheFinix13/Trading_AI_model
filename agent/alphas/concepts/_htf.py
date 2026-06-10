"""HTF bias helper — causal higher-timeframe trend derived in-line.

Why in-line and not "load D1 in parallel": the ablation harness is built
around one bar series per cell. Plumbing a second TF would mean changing
``AlphaContext``, the cell-isolation contract, and every cell that doesn't
need HTF. Synthesising the HTF series from the alpha's own bars is cheap
(O(N)) and keeps the ablation cell's isolation boundary clean.

What "HTF bias" means here: at decision bar ``i``, compare the last
synthesised HTF close to the close ``htf_lookback`` HTF bars ago. Up if the
move is at least ``min_move_pct`` of the lookback's median ATR, down if it's
the mirror, neutral otherwise. The threshold prevents flippy bias readings
in chop.

Causality contract: the synthesiser uses only bars at indices ``<= i`` and
returns the bias at ``i`` from that strict-past slice. No look-ahead.
"""
from __future__ import annotations

from enum import Enum

from agent.types import Bar, Direction


class HTFBias(str, Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"

    def matches(self, direction: Direction) -> bool:
        if self is HTFBias.UP:
            return direction == Direction.LONG
        if self is HTFBias.DOWN:
            return direction == Direction.SHORT
        return False  # NEUTRAL never aligns

    def opposes(self, direction: Direction) -> bool:
        """Mirror of ``matches`` for counter-trend filters."""
        if self is HTFBias.UP:
            return direction == Direction.SHORT
        if self is HTFBias.DOWN:
            return direction == Direction.LONG
        return False  # NEUTRAL never opposes either


# Minutes per timeframe — single source of truth.
_TF_MINUTES = {"M1": 1, "M3": 3, "M5": 5, "M15": 15, "M30": 30,
               "H1": 60, "H4": 240, "D1": 1440}


def _resample_factor(source_tf: str, target_tf: str) -> int:
    """How many ``source_tf`` bars roll up into one ``target_tf`` bar."""
    sm = _TF_MINUTES.get(source_tf)
    tm = _TF_MINUTES.get(target_tf)
    if sm is None or tm is None or sm > tm or tm % sm != 0:
        raise ValueError(
            f"Cannot synthesise {target_tf} from {source_tf} "
            f"(needs target_min % source_min == 0 with target >= source)"
        )
    return tm // sm


def htf_bias_at(
    bars: list[Bar],
    at_index: int,
    *,
    htf: str = "D1",
    htf_lookback: int = 5,
    min_move_pips: float = 30.0,
) -> HTFBias:
    """Return the HTF bias visible at bar ``at_index``.

    Builds rolling-window HTF closes from the strict-past slice
    ``bars[:at_index + 1]`` (cheap: just walks indices), then compares the
    most-recent synthesised close to the close ``htf_lookback`` HTF bars
    earlier. ``min_move_pips`` is the dead-band that keeps chop classified
    as NEUTRAL.

    Falls back to NEUTRAL when there isn't enough history yet (cold-start
    safety: the alphas treat NEUTRAL as "no signal blocked" or "no signal
    allowed" depending on whether the filter is set to *require* alignment).
    """
    if at_index < 0 or at_index >= len(bars) or not bars:
        return HTFBias.NEUTRAL
    source_tf = bars[at_index].timeframe.value
    if source_tf == htf:
        factor = 1
    else:
        try:
            factor = _resample_factor(source_tf, htf)
        except ValueError:
            return HTFBias.NEUTRAL

    needed_source_bars = factor * htf_lookback + factor
    if at_index + 1 < needed_source_bars:
        return HTFBias.NEUTRAL

    # Walk indices to find the HTF close ``htf_lookback`` HTF-bars ago and now.
    now_close = bars[at_index].close
    earlier_idx = at_index - factor * htf_lookback
    earlier_close = bars[earlier_idx].close

    move_pips = (now_close - earlier_close) * 10000.0
    if move_pips >= min_move_pips:
        return HTFBias.UP
    if move_pips <= -min_move_pips:
        return HTFBias.DOWN
    return HTFBias.NEUTRAL
