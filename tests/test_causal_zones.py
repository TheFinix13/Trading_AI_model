"""Causal zone-detection semantics (2026-08-04 lookahead fix).

The pre-fix ``detect_zones`` had two lookahead channels that a live agent
(re-preparing on history-so-far) can never reproduce:

1. Impulse validity used a rolling median of candle bodies CENTERED on
   the impulse bar -- up to 100 FUTURE bars voted on whether a zone
   existed.
2. ``fresh_zones`` filtered on ``created_bar_index`` (the base candle),
   which precedes the defining impulse by up to ``base_lookback`` bars,
   so a replay could touch-trade a zone before the displacement that
   creates it had happened.

Replay evidence measured under those semantics did not transfer to live:
the 2019-2026 squad replay went from +29.2k pips / PF 1.52 (lookahead)
to -2.3k pips / PF 0.95 (causal) -- see
``reviews/audits/2026-08-04-prefix-parity/``. These tests pin the causal
semantics so a refactor can't silently reintroduce the future.

Pinned here:

1. Prefix stability: detection over ``bars[:i+1]`` agrees with detection
   over the full series for every zone knowable at ``i``.
2. Impulse knowability: ``fresh_zones`` never returns a zone whose
   impulse bar is after ``at_index``.
3. The trailing median is strictly past (the impulse bar's own body does
   not vote on its validity).
4. ``_structural_tp`` ignores swings not yet confirmable at the decision
   bar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.alphas.concepts.zone_alpha import _structural_tp
from agent.detectors.zones import detect_zones, fresh_zones
from agent.types import Bar, Direction, Swing, Timeframe

UTC = timezone.utc
START = datetime(2024, 1, 2, tzinfo=UTC)


def _bar(i: int, o: float, c: float, *, h: float | None = None,
         l: float | None = None) -> Bar:
    hi = h if h is not None else max(o, c) + 0.0002
    lo = l if l is not None else min(o, c) - 0.0002
    return Bar(time=START + timedelta(hours=4 * i), open=o, high=hi,
               low=lo, close=c, volume=100.0, timeframe=Timeframe.H4)


def _quiet_series(n: int, *, price: float = 1.10, body: float = 0.0004) -> list[Bar]:
    """Alternating small-bodied bars around a flat price."""
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(_bar(i, price, price + body))
        else:
            out.append(_bar(i, price + body, price))
    return out


def _with_impulse(series: list[Bar], idx: int, *, pips: float = 40.0,
                  bullish: bool = True) -> list[Bar]:
    """Replace ``series[idx]`` with a displacement candle."""
    out = list(series)
    base = out[idx - 1].close
    move = pips * 0.0001
    if bullish:
        out[idx] = _bar(idx, base, base + move)
    else:
        out[idx] = _bar(idx, base, base - move)
    # Re-anchor the following bars near the new price so the zone is not
    # instantly mitigated.
    level = out[idx].close
    for j in range(idx + 1, len(out)):
        b = out[j]
        out[j] = _bar(j, level, level + (b.close - b.open))
    return out


def test_prefix_detection_matches_full_series():
    """Every zone knowable at i must be identical whether detected on
    bars[:i+1] (live shape) or on the full series (replay shape)."""
    series = _quiet_series(400)
    series = _with_impulse(series, 250, bullish=False)
    series = _with_impulse(series, 320, bullish=True)

    full = detect_zones(series)
    assert full, "fixture must produce at least one zone"

    for i in (250, 260, 300, 320, 340, 399):
        prefix = detect_zones(series[:i + 1])
        knowable_full = {
            (z.direction, z.top, z.bottom, z.created_bar_index, z.impulse_bar_index)
            for z in full
            if z.impulse_bar_index is not None and z.impulse_bar_index <= i
        }
        knowable_prefix = {
            (z.direction, z.top, z.bottom, z.created_bar_index, z.impulse_bar_index)
            for z in prefix
        }
        assert knowable_prefix == knowable_full, (
            f"prefix/full zone sets diverge at i={i} -- the lookahead "
            "median is back"
        )


def test_fresh_zones_refuses_zone_before_its_impulse():
    """created_bar_index precedes the impulse; the zone must stay
    invisible until the impulse bar has closed."""
    series = _quiet_series(300)
    series = _with_impulse(series, 250, bullish=True)
    zones = detect_zones(series)
    z = next(zz for zz in zones if zz.impulse_bar_index == 250)
    assert z.created_bar_index < 250

    # One bar before the impulse: the base exists, the move does not.
    assert z not in fresh_zones(zones, 249), (
        "zone tradable before its defining impulse -- replay lookahead"
    )
    # At the impulse close and after: knowable.
    assert z in fresh_zones(zones, 250)
    assert z in fresh_zones(zones, 251)


def test_impulse_median_is_strictly_past():
    """A cluster of big future bars must not admit/reject today's zone.

    Construct two series identical up to bar 250 but with very different
    bars AFTER it; the zone set knowable at 250 must be identical.
    """
    quiet = _quiet_series(400)
    quiet = _with_impulse(quiet, 250, bullish=True)

    loud = list(quiet)
    for j in range(260, 360):  # future volatility explosion
        base = loud[j - 1].close
        loud[j] = _bar(j, base, base + (0.004 if j % 2 == 0 else -0.004))

    know_quiet = {(z.top, z.bottom, z.impulse_bar_index)
                  for z in detect_zones(quiet[:251])}
    know_loud = {(z.top, z.bottom, z.impulse_bar_index)
                 for z in detect_zones(loud[:251])}
    # Same prefix => same zones, trivially. The real assertion: the FULL
    # series detection restricted to impulse<=250 equals the prefix set.
    full_loud = {(z.top, z.bottom, z.impulse_bar_index)
                 for z in detect_zones(loud)
                 if z.impulse_bar_index is not None and z.impulse_bar_index <= 250}
    assert know_quiet == know_loud
    assert full_loud == know_loud, (
        "future bars changed which impulses were valid at bar 250"
    )


def test_structural_tp_ignores_unconfirmed_swings():
    bars = _quiet_series(60, price=1.10)
    # A swing high 2 bars before the decision bar: with lookback 5 it is
    # NOT yet confirmable at i=50.
    swings = [
        Swing(time=bars[30].time, price=1.1080, is_high=True, bar_index=30),
        Swing(time=bars[48].time, price=1.1120, is_high=True, bar_index=48),
    ]
    i = 50
    # Unfiltered legacy behaviour would pick the closer/unconfirmed swing.
    tp_legacy = _structural_tp(bars, swings, i, Direction.LONG, confirm_bars=0)
    tp_causal = _structural_tp(bars, swings, i, Direction.LONG, confirm_bars=5)
    assert tp_legacy == 1.1080  # min opposite-side swing above price
    assert tp_causal == 1.1080
    # Remove the confirmed swing: causally there is NO structural target.
    tp_only_unconfirmed = _structural_tp(
        bars, [swings[1]], i, Direction.LONG, confirm_bars=5,
    )
    assert tp_only_unconfirmed is None, (
        "TP picked off a swing that needs future bars to confirm"
    )
    assert _structural_tp(bars, [swings[1]], i, Direction.LONG,
                          confirm_bars=0) == 1.1120
