"""Shared per-agent provenance helpers (F19/F20 dispersion inputs).

Phase P (2026-07-01, doctrine amendment "provenance-pips") adds two
functions that every agent's ``intend()`` can call to stamp real
``atr_pips`` and ``h1_swing_pips`` values on its ``proposal.rationale``
dict. These are consumed at trade-open time via
``_annotate_trade_record`` in ``run_phi4_squad_gate.py`` and flow into
``TradeRecord.source_atr_pips`` / ``TradeRecord.source_h1_swing_pips``,
which the G7 C6 evaluator (``_evaluate_criterion_6``) uses to compute
per-agent risk-shape dispersion.

Design:

- Zero external dependencies (stdlib only).
- Pure functions: no I/O, no logging.
- Robust to short bar histories: return ``None`` when the requested
  window is not available (never NaN, never a mis-scaled float).
- H1 swing is approximated by the H4 lookback high-low range for
  agents that don't have H1 bar access -- honest proxy, not a fake H1
  fetch. Agents whose home_tf IS H1 can call ``swing_pips_from_bars``
  directly on their H1 series.

Doctrine reference: 06-blue-lock-doctrine.md sec 4.1a (v1 chemistry
primitives -- F20 risk-intent inputs).
"""
from __future__ import annotations

from typing import Any


# Standard pip size for the majors we currently trade. Callers should
# pass their own pip_size for exotic instruments.
DEFAULT_PIP_SIZE_MAJOR: float = 1e-4
DEFAULT_PIP_SIZE_JPY: float = 1e-2


def pip_size_for(symbol: str) -> float:
    """Pip size for a symbol.

    Majors (EURUSD, GBPUSD, USDCAD, ...) use 1e-4. JPY quote pairs use
    1e-2. New exotics that don't fit these two rules should route
    through a per-symbol table amendment.
    """
    return DEFAULT_PIP_SIZE_JPY if symbol.upper().endswith("JPY") else DEFAULT_PIP_SIZE_MAJOR


def stop_pips_from_prices(symbol: str, entry: float, stop: float) -> float | None:
    """F22a helper -- distance from entry to SL in pips, symbol-aware."""
    if entry is None or stop is None:
        return None
    return abs(float(entry) - float(stop)) / pip_size_for(symbol)


def expected_r_from_prices(
    entry: float, stop: float, take_profit: float,
) -> float | None:
    """F22a helper -- reward:risk ratio from entry, stop and take-profit.

    Returns ``None`` if the risk leg is degenerate (SL at entry).
    """
    if entry is None or stop is None or take_profit is None:
        return None
    risk = abs(float(entry) - float(stop))
    if risk <= 0.0:
        return None
    reward = abs(float(take_profit) - float(entry))
    return reward / risk


def atr_pips_at(
    bars: list[Any],
    i: int,
    *,
    period: int = 14,
    pip_size: float = DEFAULT_PIP_SIZE_MAJOR,
) -> float | None:
    """Wilder-smoothed ATR(``period``) at bar index ``i``, expressed in pips.

    Uses the classic Wilder smoothing (alpha = 1/period, no adjust).
    Returns ``None`` when ``i`` is outside the settled window (fewer
    than ``period`` bars of history available).

    ``bars`` must be a list of bar-like objects with ``.high``, ``.low``,
    ``.close`` attributes (production ``Bar`` or a dataclass shim both
    work).
    """
    if i < period - 1 or i >= len(bars):
        return None
    # True-range series over the settled window.
    tr: list[float] = []
    for k in range(max(0, i - period), i + 1):
        h = float(bars[k].high)
        lo = float(bars[k].low)
        if k == 0:
            tr.append(h - lo)
            continue
        pc = float(bars[k - 1].close)
        tr.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    # Wilder smoothing bootstrapped from the first `period` TR values.
    if len(tr) < period:
        return None
    alpha = 1.0 / float(period)
    smoothed = sum(tr[:period]) / float(period)
    for j in range(period, len(tr)):
        smoothed = alpha * tr[j] + (1.0 - alpha) * smoothed
    return smoothed / pip_size


def swing_pips_from_bars(
    bars: list[Any],
    i: int,
    *,
    lookback: int = 20,
    pip_size: float = DEFAULT_PIP_SIZE_MAJOR,
) -> float | None:
    """Lookback-window (high - low) range at bar index ``i``, in pips.

    Used as a same-timeframe swing-structure proxy: for an H4 agent the
    20-bar range approximates ~3-4 trading days of structural volatility,
    which is the operationally-relevant "recent swing" for a Phi4-style
    stop-placement decision.

    Returns ``None`` when fewer than ``lookback`` bars are available.
    """
    lo_bound = i - lookback
    if lo_bound < 0 or i >= len(bars):
        return None
    highs = [float(bars[k].high) for k in range(lo_bound, i + 1)]
    lows = [float(bars[k].low) for k in range(lo_bound, i + 1)]
    return (max(highs) - min(lows)) / pip_size


def stamp_provenance_pips(
    rationale: dict[str, Any],
    *,
    bars: list[Any],
    i: int,
    atr_period: int = 14,
    swing_lookback: int = 20,
    pip_size: float = DEFAULT_PIP_SIZE_MAJOR,
) -> None:
    """Mutate ``rationale`` in place: add ``atr_pips`` + ``h1_swing_pips``.

    Convenience for the common agent pattern: compute both values from
    the same bar series and stash under the standard key names that
    ``_annotate_trade_record`` reads. Sets keys to ``None`` when the
    window is not settled (never raises).
    """
    rationale["atr_pips"] = atr_pips_at(
        bars, i, period=atr_period, pip_size=pip_size,
    )
    rationale["h1_swing_pips"] = swing_pips_from_bars(
        bars, i, lookback=swing_lookback, pip_size=pip_size,
    )


# ---------------------------------------------------------------------------
# Phase S (2026-07-01) -- regime_fit proxy from per-bar ATR
# ---------------------------------------------------------------------------

# Reference ATR (in pips) at which regime_fit centers on 0.5. Below this
# value the tape is quiet (regime_fit tilts low); above it the tape is
# active (regime_fit tilts high). Empirically the H4 EURUSD/GBPUSD/USDCAD
# panel 2015-2025 sits at mean ATR14 ~= 28-32 pips, so 30 is the honest
# center. Callers can override via ``mean_atr`` for exotic instruments.
DEFAULT_MEAN_ATR_PIPS: float = 30.0


def regime_fit_from_atr(
    bars: list[Any],
    i: int,
    *,
    mean_atr: float = DEFAULT_MEAN_ATR_PIPS,
    period: int = 14,
    pip_size: float = DEFAULT_PIP_SIZE_MAJOR,
    lo_bound: float = 0.2,
    hi_bound: float = 0.8,
) -> float:
    """Map current-bar ATR to a per-bar regime_fit in [``lo_bound``, ``hi_bound``].

    Doctrine 06 sec 4.1a (Phase S, 2026-07-01 amendment): every proposer
    with bar access should replace the ``regime_fit=0.5`` placeholder
    with a per-bar value derived from the same bar context the proposal
    uses. This makes ``playstyle_lot_intent`` see real variance and
    unbreaks the F19 lot-dispersion signal that Phase P Kelly-saturated
    the sandbox at MIN_LOT.

    Map:

        r_raw = 0.5 * ATR / mean_atr
        regime_fit = clip(r_raw, lo_bound, hi_bound)

    At ATR = 30 pips (panel mean): regime_fit = 0.5 (neutral).
    At ATR = 15 pips (quiet tape): regime_fit = 0.25 (below neutral).
    At ATR = 60 pips (active tape): regime_fit = 1.0 -> clipped to 0.8.

    Returns 0.5 (neutral) when ATR is unavailable (short bar history) so
    the caller can drop this in place of the constant without adding a
    null check.
    """
    atr = atr_pips_at(bars, i, period=period, pip_size=pip_size)
    if atr is None or mean_atr <= 0:
        # Truly-unavailable ATR (short bar history) -> neutral so the
        # caller can drop this in place of the 0.5 placeholder without
        # a null-check. An ATR of exactly zero is a legitimate "dead
        # tape" reading and falls through to the clipped-low path.
        return 0.5
    raw = 0.5 * (float(atr) / float(mean_atr))
    if raw < lo_bound:
        return lo_bound
    if raw > hi_bound:
        return hi_bound
    return float(raw)


def regime_fit_from_atr_pips(
    atr_pips: float | None,
    *,
    mean_atr: float = DEFAULT_MEAN_ATR_PIPS,
    lo_bound: float = 0.2,
    hi_bound: float = 0.8,
) -> float:
    """Pips-domain twin of ``regime_fit_from_atr`` (dispersion-r2,
    2026-07-14 doctrine §4.1a amendment).

    For agents WITHOUT bar access (Nagi) that borrow a leader's stamped
    ``atr_pips`` from the workspace: apply the identical Phase-S map to
    the already-computed pips value. Returns 0.5 (neutral) when the
    borrowed value is missing, so it drops in for the placeholder
    without a null check.
    """
    if atr_pips is None or mean_atr <= 0:
        return 0.5
    raw = 0.5 * (float(atr_pips) / float(mean_atr))
    if raw < lo_bound:
        return lo_bound
    if raw > hi_bound:
        return hi_bound
    return float(raw)


def isagi_metavision_lift(
    peer_directions_agree: int,
    peer_directions_disagree: int,
    *,
    agree_double_lift: float = 0.10,
    agree_single_lift: float = 0.05,
    disagree_penalty: float = 0.05,
) -> float:
    """Metavision peer-alignment conviction lift (Phase S).

    Doctrine 06 sec 3.11.3 (Isagi arc): "metavision sees the whole
    field" -- when 2+ other strikers already published thoughts in the
    same direction Isagi is about to enter, conviction lifts. Peer
    disagreement dampens.

    - ``peer_directions_agree >= 2`` -> ``+agree_double_lift`` (default +0.10).
    - ``peer_directions_agree == 1`` and no disagreement -> ``+agree_single_lift`` (default +0.05).
    - ``peer_directions_disagree > peer_directions_agree`` -> ``-disagree_penalty`` (default -0.05).
    - otherwise neutral (0.0).

    Returns a signed float to add to ``sig.conviction``. Callers should
    clip the final conviction to [0, 1].
    """
    ag = int(peer_directions_agree)
    dis = int(peer_directions_disagree)
    if ag >= 2:
        return float(agree_double_lift)
    if ag >= 1 and dis == 0:
        return float(agree_single_lift)
    if dis > ag:
        return -float(disagree_penalty)
    return 0.0
