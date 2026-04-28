"""Day-of-week trading blocker."""
from __future__ import annotations

from datetime import datetime, timezone

from agent.rules.filters import is_no_trade_day


def _wed():
    return datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc)  # Wednesday


def _mon():
    return datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)  # Monday


def test_blocks_wednesday():
    assert is_no_trade_day(_wed(), ["Wed"]) is True
    assert is_no_trade_day(_wed(), ["wednesday"]) is True
    assert is_no_trade_day(_wed(), ["WED"]) is True


def test_does_not_block_monday():
    assert is_no_trade_day(_mon(), ["Wed"]) is False


def test_empty_list_blocks_nothing():
    assert is_no_trade_day(_wed(), []) is False
    assert is_no_trade_day(_mon(), []) is False


def test_unknown_day_name_ignored():
    """Garbage entries shouldn't crash the filter."""
    assert is_no_trade_day(_wed(), ["xyz"]) is False
    assert is_no_trade_day(_wed(), ["Wed", "garbage"]) is True
