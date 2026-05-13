"""Tests for cloud vision providers (Gemini, Claude) and the auto-selector.

We never call the real APIs in CI — all network-dependent paths are mocked.
The tests focus on:
  * is_available() gating (returns False without API key or SDK)
  * _parse() produces correct ChartReading fields
  * get_best_vision_provider() fallback priority
  * get_vision_provider() explicit selection
  * get_vision_status() structure
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from agent.llm.cloud_vision import (
    ClaudeVision,
    GeminiVision,
    get_best_vision_provider,
    get_vision_provider,
    get_vision_status,
)


# ── Availability tests ───────────────────────────────────────────────────────


class TestGeminiAvailability:
    def test_unavailable_without_key(self):
        v = GeminiVision(api_key="")
        assert v.is_available() is False

    def test_unavailable_with_key_no_sdk(self):
        with patch.dict("sys.modules", {"google.generativeai": None}):
            v = GeminiVision(api_key="test-key-123")
            assert v.is_available() is False

    def test_available_with_key_and_sdk(self):
        v = GeminiVision(api_key="test-key-123")
        assert v.is_available() is True

    def test_provider_name(self):
        v = GeminiVision()
        assert v.provider_name == "gemini"


class TestClaudeAvailability:
    def test_unavailable_without_key(self):
        v = ClaudeVision(api_key="")
        assert v.is_available() is False

    def test_unavailable_with_key_no_sdk(self):
        with patch.dict("sys.modules", {"anthropic": None}):
            v = ClaudeVision(api_key="test-key-123")
            assert v.is_available() is False

    def test_available_with_key_and_sdk(self):
        v = ClaudeVision(api_key="test-key-123")
        assert v.is_available() is True

    def test_provider_name(self):
        v = ClaudeVision()
        assert v.provider_name == "claude"


# ── Parsing tests (reuse JSON from test_vision.py) ──────────────────────────

_STRICT_JSON = (
    '{"timeframe": "H1", "direction_bias": "long", '
    '"current_price_estimate": 1.17207, '
    '"key_levels": [{"label": "PWH", "price": 1.17800, "kind": "resistance"}], '
    '"active_zones": ["heavy confluence 1.17000-1.17500"], '
    '"session_context": "london", '
    '"narrative": "Bullish bias above support trendline.", '
    '"trade_idea": {"direction": "long", "entry": 1.17000, "stop": 1.16800, '
    '               "tp": 1.17500, "rationale": "fib 50 hold"}}'
)

_LOOSE_JSON = (
    "Here's the analysis:\n"
    '{"timeframe": "M15", "direction_bias": "short", '
    '"current_price_estimate": null, "key_levels": [], '
    '"active_zones": [], "session_context": "ny", '
    '"narrative": "Looks bearish near PDH.", "trade_idea": {}}\n'
    "Let me know if you need more."
)


class TestGeminiParsing:
    def test_strict_json(self):
        v = GeminiVision(api_key="test")
        rd = v._parse(_STRICT_JSON)
        assert rd.timeframe == "H1"
        assert rd.direction_bias == "long"
        assert rd.current_price_estimate == 1.17207
        assert rd.key_levels[0]["label"] == "PWH"
        assert rd.model == "gemini:gemini-2.5-flash"

    def test_loose_json_with_prose(self):
        v = GeminiVision(api_key="test")
        rd = v._parse(_LOOSE_JSON)
        assert rd.timeframe == "M15"
        assert rd.direction_bias == "short"
        assert rd.current_price_estimate is None

    def test_empty_returns_default(self):
        v = GeminiVision(api_key="test")
        rd = v._parse("")
        assert rd.timeframe == "unknown"


class TestClaudeParsing:
    def test_strict_json(self):
        v = ClaudeVision(api_key="test")
        rd = v._parse(_STRICT_JSON)
        assert rd.timeframe == "H1"
        assert rd.direction_bias == "long"
        assert rd.current_price_estimate == 1.17207
        assert rd.trade_idea["direction"] == "long"
        assert rd.model.startswith("claude:")

    def test_loose_json_with_prose(self):
        v = ClaudeVision(api_key="test")
        rd = v._parse(_LOOSE_JSON)
        assert rd.timeframe == "M15"
        assert rd.session_context == "ny"


# ── Provider selection tests ─────────────────────────────────────────────────


class TestGetBestProvider:
    def test_no_keys_no_ollama_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("GEMINI_API_KEY", None)
            with patch("agent.llm.vision.ChartVision") as MockCV:
                mock_local = MagicMock()
                mock_local.is_available.return_value = False
                MockCV.return_value = mock_local
                result = get_best_vision_provider()
                assert result is None

    def test_gemini_key_returns_gemini(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            result = get_best_vision_provider()
            assert result is not None
            assert result.provider_name == "gemini"

    def test_claude_key_returns_claude(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            result = get_best_vision_provider()
            assert result is not None
            assert result.provider_name == "claude"

    def test_both_keys_prefers_claude(self):
        with patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "claude-key", "GEMINI_API_KEY": "gemini-key"},
            clear=False,
        ):
            result = get_best_vision_provider()
            assert result is not None
            assert result.provider_name == "claude"


class TestGetVisionProvider:
    def test_explicit_gemini(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            result = get_vision_provider("gemini")
            assert result is not None
            assert result.provider_name == "gemini"

    def test_explicit_claude(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            result = get_vision_provider("claude")
            assert result is not None
            assert result.provider_name == "claude"

    def test_explicit_gemini_no_key_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GEMINI_API_KEY", None)
            result = get_vision_provider("gemini")
            assert result is None

    def test_auto_delegates_to_best(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            result = get_vision_provider("auto")
            assert result is not None
            assert result.provider_name == "gemini"

    def test_unknown_name_returns_none(self):
        result = get_vision_provider("openai")
        assert result is None


class TestGetVisionStatus:
    def test_returns_expected_structure(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("GEMINI_API_KEY", None)
            with patch("agent.llm.vision.ChartVision") as MockCV:
                mock_local = MagicMock()
                mock_local.is_available.return_value = False
                mock_local.model = None
                MockCV.return_value = mock_local
                status = get_vision_status()

        assert "active_provider" in status
        assert "providers" in status
        assert len(status["providers"]) == 3
        names = [p["name"] for p in status["providers"]]
        assert "claude" in names
        assert "gemini" in names
        assert "local" in names
        for p in status["providers"]:
            assert "available" in p
            assert "model" in p
            assert "label" in p

    def test_shows_gemini_active_when_key_set(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            status = get_vision_status()
            assert status["active_provider"] == "gemini"
