"""Catalogue of known confluence boosters and their price-extraction metadata.

Each booster has a category and description. Boosters with a specific price
(e.g. fib levels, daily levels) can be used for alignment checking.
Session/time-based boosters have no associated price.
"""
from __future__ import annotations

BOOSTER_CATALOG: dict[str, dict[str, str]] = {
    # Fibonacci levels (price = the fib level itself)
    "fib_382": {"category": "fib", "description": "38.2% retracement"},
    "fib_500": {"category": "fib", "description": "50% retracement"},
    "fib_618": {"category": "fib", "description": "61.8% retracement"},
    "fib_786": {"category": "fib", "description": "78.6% retracement"},

    # Session context (no specific price — time-based)
    "session_london": {"category": "session", "description": "London session active"},
    "session_ny": {"category": "session", "description": "NY session active"},
    "session_overlap": {"category": "session", "description": "London-NY overlap"},

    # Daily levels (price = the level)
    "near_PDH": {"category": "daily_level", "description": "Near previous day high"},
    "near_PDL": {"category": "daily_level", "description": "Near previous day low"},
    "near_PWH": {"category": "daily_level", "description": "Near previous week high"},
    "near_PWL": {"category": "daily_level", "description": "Near previous week low"},

    # Structural
    "trendline": {"category": "structural", "description": "At trendline"},
    "htf_bias_long": {"category": "trend", "description": "H4/D1 trend is bullish"},
    "htf_bias_short": {"category": "trend", "description": "H4/D1 trend is bearish"},
    "htf_zone_align_D1": {"category": "htf", "description": "Price in D1 zone"},
    "htf_zone_align_H4": {"category": "htf", "description": "Price in H4 zone"},

    # Phase/sweep
    "phase_distribution": {"category": "phase", "description": "ICT distribution phase"},
    "phase_accumulation": {"category": "phase", "description": "ICT accumulation phase"},
    "liquidity_sweep": {"category": "sweep", "description": "Recent liquidity sweep"},

    # Zone quality (from SD zone detector)
    "zone_high_quality": {"category": "zone", "description": "SD zone quality >= 70"},
    "zone_killzone": {"category": "zone", "description": "Zone formed in killzone"},
    "zone_fvg_behind": {"category": "zone", "description": "Zone with FVG behind it"},
    "zone_proper_formation": {"category": "zone", "description": "Rally-base-drop or vice versa"},

    # BOS context
    "bos_body_break": {"category": "bos", "description": "BOS via body close (not wick)"},
    "bos_displacement": {"category": "bos", "description": "BOS with large displacement"},
}


def get_price_boosters() -> list[str]:
    """Return boosters that have an associated price for alignment checking."""
    price_categories = {"fib", "daily_level", "structural", "htf"}
    return [
        name for name, meta in BOOSTER_CATALOG.items()
        if meta["category"] in price_categories
    ]


def get_time_boosters() -> list[str]:
    """Return boosters that are time-based (no specific price)."""
    time_categories = {"session", "phase"}
    return [
        name for name, meta in BOOSTER_CATALOG.items()
        if meta["category"] in time_categories
    ]
