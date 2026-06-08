"""Tests for MT5 order comment sanitization.

MT5 rejects orders whose ``comment`` is longer than 31 characters or contains
characters outside basic ASCII alphanumerics/space/underscore/hyphen with a
``-2 Invalid 'comment' argument`` error. The sanitizer guards against this.
"""
from agent.live.broker import _MT5_COMMENT_MAX_LEN, _sanitize_mt5_comment
from agent.live.signal_loop import _short_order_comment


def test_strips_special_characters():
    # The exact kind of comment that triggered the live rejection.
    raw = "FVGRetest ['fvg_retest', 'fvg_killzone', 'fvg_high_quality']"
    out = _sanitize_mt5_comment(raw)
    assert all(c.isalnum() or c in " _-" for c in out)
    assert "[" not in out and "]" not in out and "'" not in out and "," not in out


def test_truncates_to_max_len():
    out = _sanitize_mt5_comment("A" * 100)
    assert len(out) == _MT5_COMMENT_MAX_LEN
    assert out == "A" * _MT5_COMMENT_MAX_LEN


def test_result_always_within_limit():
    raw = "ai-agent H1 FVGRetest fvg_retest,fvg_killzone,reaction_wick"
    out = _sanitize_mt5_comment(raw)
    assert len(out) <= _MT5_COMMENT_MAX_LEN


def test_empty_and_none_default_to_ai():
    assert _sanitize_mt5_comment("") == "AI"
    assert _sanitize_mt5_comment(None) == "AI"


def test_only_special_chars_defaults_to_ai():
    assert _sanitize_mt5_comment("[]{}'\",.;:!") == "AI"


def test_keeps_safe_characters():
    assert _sanitize_mt5_comment("FVG H1 L") == "FVG H1 L"
    assert _sanitize_mt5_comment("LZI-S") == "LZI-S"
    assert _sanitize_mt5_comment("AI_close") == "AI_close"


def test_custom_max_len():
    assert _sanitize_mt5_comment("abcdefgh", max_len=4) == "abcd"


def test_short_order_comment_is_valid():
    for strategy in (
        "FVGRetest", "LiquidityGrabReversal", "BOSContinuation",
        "FibRetracement", "SDZoneRetest", "generic", "SomeUnknownStrategy",
    ):
        for direction in ("LONG", "SHORT"):
            comment = _short_order_comment(strategy, "H1", direction)
            # Must already be MT5-safe before the broker sanitizes it again.
            assert comment == _sanitize_mt5_comment(comment)
            assert len(comment) <= _MT5_COMMENT_MAX_LEN


def test_short_order_comment_format():
    assert _short_order_comment("FVGRetest", "H1", "LONG") == "FVG H1 L"
    assert _short_order_comment("LiquidityGrabReversal", "M15", "SHORT") == "LZI M15 S"
