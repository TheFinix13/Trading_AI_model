"""Configuration knobs for A9 Sae Itoshi (event specialist).

Sae only fires INSIDE a scheduled high-impact USD event window. The
knobs here govern:

* The pre-event / post-event window widths.
* The fade-mechanic thresholds (min move, min wick fraction).
* The ride-mechanic threshold (min retention).
* The proposal geometry (target R:R).
* The `sae_enabled` master flag -- **disabled by default** so Sae
  does NOT enter ``roster.proposers`` until the Phase AE pre-reg
  lands and the operator flips the flag.

Universe knob (``symbols``) defaults to EURUSD-only because the
current parquet cache only has M15/M5 for EURUSD (and GBPUSD).
Sae's mechanics require M15 granularity within the H4 bar around
the event; multi-pair support waits until the M15 cache broadens.
"""
from __future__ import annotations

from dataclasses import dataclass


DEFAULT_SAE_SYMBOLS: tuple[str, ...] = ("EURUSD",)


@dataclass(frozen=True)
class SaeConfig:
    """Locked knobs for :class:`agent.squad.agents.a09_sae.A9SaeV1`.

    Attributes:
        sae_enabled:              Master enable flag. Default False --
                                  Sae only enters ``roster.proposers``
                                  when this is True.
        symbols:                  Universe whitelist. Default EURUSD-only
                                  until M15 cache broadens.
        fire_window_before_min:   Minutes BEFORE the event Sae is
                                  allowed to fire (0 in v1 -- no
                                  pre-release firing).
        fire_window_after_min:    Minutes AFTER the event Sae remains
                                  eligible. Default 60.
        fade_min_move_pips:       Minimum |close - open| of the event
                                  bar for the fade mechanic to consider
                                  firing. Default 40.0.
        fade_min_wick_frac:       Minimum fraction of bar range in the
                                  wick opposite the move for the fade
                                  to fire. Default 0.5.
        ride_min_retention:       Minimum |next_close - event_open| /
                                  |event_bar move| for the ride
                                  mechanic to fire. Default 0.7.
        target_rr:                Fixed target R:R for both mechanics.
                                  Default 1.5.
        fade_wait_min:            Minutes after the event before the
                                  fade mechanic can fire (needs the
                                  first M15 bar to close). Default 15.
        ride_wait_min:            Minutes after the event before the
                                  ride mechanic can fire (needs two
                                  M15 bars to close). Default 30.
        fade_stop_padding_pips:   Extra pips beyond the wick extremum
                                  for the fade stop. Default 5.0.
        pip_size:                 Currency-quote pip size for the
                                  universe (0.0001 for USD-quoted
                                  majors; JPY-quoted would need
                                  0.01). Default 0.0001.
    """

    sae_enabled: bool = False
    symbols: tuple[str, ...] = DEFAULT_SAE_SYMBOLS
    fire_window_before_min: int = 30
    fire_window_after_min: int = 60
    fade_min_move_pips: float = 40.0
    fade_min_wick_frac: float = 0.5
    ride_min_retention: float = 0.7
    target_rr: float = 1.5
    fade_wait_min: int = 15
    ride_wait_min: int = 30
    fade_stop_padding_pips: float = 5.0
    pip_size: float = 0.0001


DEFAULT_SAE_CONFIG = SaeConfig()


__all__ = [
    "DEFAULT_SAE_CONFIG",
    "DEFAULT_SAE_SYMBOLS",
    "SaeConfig",
]
