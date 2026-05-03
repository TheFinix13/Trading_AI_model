"""Vision adapter parses model output into a ChartReading and degrades when
the daemon / model is unavailable.

We don't run the actual vision model in CI (it's a multi-GB local artifact).
Instead we mock the Ollama client so the test focuses on:
    * fallback when no vision model is installed
    * JSON parsing into ChartReading fields
    * loose-JSON recovery when the model wraps output in prose
"""
from __future__ import annotations

from unittest.mock import MagicMock

from agent.llm.ollama import OllamaUnavailable
from agent.llm.vision import ChartVision


_VISION_PREFIXES = (
    "llava", "llava-phi3", "llava-llama3", "bakllava", "moondream",
    "llama3.2-vision", "qwen2-vl", "qwen2.5-vl", "minicpm-v",
)


def _client_with_models(models: list[str], reply: str = ""):
    c = MagicMock()
    c.is_alive.return_value = True
    c.list_models.return_value = models
    def _find():
        for tag in models:
            base = tag.split(":")[0].lower()
            if any(base.startswith(p) for p in _VISION_PREFIXES):
                return tag
        return None
    c.find_vision_model.side_effect = _find
    c.chat.return_value = reply
    c.KNOWN_VISION_PREFIXES = _VISION_PREFIXES
    return c


def test_no_vision_model_installed_means_unavailable():
    c = _client_with_models(["qwen2.5:7b-instruct"])
    v = ChartVision(client=c)
    assert v.is_available() is False


def test_vision_model_detected():
    c = _client_with_models(["qwen2.5:7b-instruct", "llava-phi3:latest"])
    v = ChartVision(client=c)
    assert v.is_available() is True
    assert "llava" in (v.model or "")


def test_analyse_parses_strict_json():
    raw = (
        '{"timeframe": "H1", "direction_bias": "long", '
        '"current_price_estimate": 1.17207, '
        '"key_levels": [{"label": "PWH", "price": 1.17800, "kind": "resistance"}], '
        '"active_zones": ["heavy confluence 1.17000-1.17500"], '
        '"session_context": "london", '
        '"narrative": "Bullish bias above support trendline.", '
        '"trade_idea": {"direction": "long", "entry": 1.17000, "stop": 1.16800, '
        '               "tp": 1.17500, "rationale": "fib 50 hold"}}'
    )
    c = _client_with_models(["llava-phi3:latest"], reply=raw)
    v = ChartVision(client=c)
    rd = v.analyse(b"\x89PNG fake")
    assert rd.timeframe == "H1"
    assert rd.direction_bias == "long"
    assert rd.current_price_estimate == 1.17207
    assert rd.key_levels[0]["label"] == "PWH"
    assert rd.session_context == "london"
    assert rd.trade_idea["direction"] == "long"


def test_analyse_recovers_loose_json_with_prose():
    raw = (
        "Sure! Here's the JSON:\n"
        '{"timeframe": "M15", "direction_bias": "short", '
        '"current_price_estimate": null, "key_levels": [], '
        '"active_zones": [], "session_context": "ny", '
        '"narrative": "Looks bearish near PDH.", "trade_idea": {}}\n'
        "Hope that helps!"
    )
    c = _client_with_models(["llava-phi3:latest"], reply=raw)
    v = ChartVision(client=c)
    rd = v.analyse(b"\x89PNG")
    assert rd.timeframe == "M15"
    assert rd.direction_bias == "short"
    assert rd.current_price_estimate is None


def test_analyse_raises_when_unavailable():
    c = _client_with_models(["qwen2.5:7b-instruct"])  # no vision tag
    v = ChartVision(client=c)
    try:
        v.analyse(b"\x89PNG")
    except OllamaUnavailable:
        return
    raise AssertionError("expected OllamaUnavailable")
