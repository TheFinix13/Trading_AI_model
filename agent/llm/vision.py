"""Chart-vision service: pipe a chart screenshot through a local vision LLM
and get a structured trader's-eye reading back.

Why this exists
---------------
The user works exclusively from TradingView charts (NY tz, UTC-4) annotated
with their own POI/FVG/zone library. A picture of those charts contains data
the agent's bar-by-bar feed *cannot* see: hand-drawn trendlines, named POI
zones, fib placements, the user's own narrative boxes ("Heavy Confluence",
"Liquidity Grab"). We want the agent to be able to:

  1. Read a screenshot the user uploads via the dashboard /chat page and
     produce a textual summary the chat LLM can then reason over.
  2. Cross-check the agent's own recent signals against what the user sees on
     the chart (does the agent's "buy zone at 1.16700" match a box the user
     drew?).
  3. Eventually: live-monitor a charts folder via filesystem watcher and ping
     the user when its read disagrees with the agent's bar-feed read.

We deliberately keep the prompt narrow and structured. Vision LLMs hallucinate
prices freely if asked open-ended questions; they hallucinate much less when
constrained to a JSON schema with explicit fields.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.llm.ollama import OllamaClient, OllamaUnavailable

log = logging.getLogger(__name__)

# Trader's-eye system prompt. The vision model has weak technical-chart prior
# so we prime it with the exact vocabulary the user uses (POI zones, FVG, BOS,
# liquidity grab, fib levels) and the EURUSD price context.
SYSTEM_PROMPT = """You are a forex trading analyst examining a TradingView chart screenshot for EURUSD.
The chart timezone is New York (UTC-4). Common annotations on the chart include:
- POI Zones (Points of Interest) at 15-minute, 1-hour and 4-hour timeframes
- Fair Value Gaps (FVGs) shown as small rectangles
- BOS (Break of Structure) markers
- Supply / Demand zones (coloured rectangles)
- Liquidity Grab boxes (small boxes around wick lows or highs)
- Fibonacci retracements with named levels (38.2%, 50%, 61.8%, 78.6%)
- Support / Resistance trendlines (red descending, green ascending)
- Info lines tagged by timeframe: 1M / 1D / 1W / 1HR

You will read the chart and output STRICT JSON matching this schema:
{
  "timeframe": "M1|M5|M15|M30|H1|H4|D1 or unknown",
  "direction_bias": "long|short|neutral",
  "current_price_estimate": <float | null>,
  "key_levels": [{"label": "<name>", "price": <float>, "kind": "support|resistance|fib|zone|fvg|sweep"}],
  "active_zones": ["<short description>", ...],
  "session_context": "asia|london|london_ny_overlap|ny|off_session|unknown",
  "narrative": "<2-4 sentence trader's read of what is happening and what the next likely move is>",
  "trade_idea": {"direction": "long|short|wait", "entry": <float|null>, "stop": <float|null>, "tp": <float|null>, "rationale": "<one sentence>"}
}
Only emit fields you can confirm from the image. Use null for unknowns. EURUSD prices are in the 1.0xxxx-1.2xxxx range."""

USER_PROMPT_TEMPLATE = """Analyse this EURUSD chart. Identify the timeframe, current price, key drawn levels (zones, fibs, trendlines), and give me a trade idea consistent with the structure on screen.

{extra_context}

Respond with ONLY the JSON object — no prose before or after."""


@dataclass
class ChartReading:
    """Structured output from the vision pass."""
    timeframe: str = "unknown"
    direction_bias: str = "neutral"
    current_price_estimate: float | None = None
    key_levels: list[dict[str, Any]] = field(default_factory=list)
    active_zones: list[str] = field(default_factory=list)
    session_context: str = "unknown"
    narrative: str = ""
    trade_idea: dict[str, Any] = field(default_factory=dict)
    raw: str = ""              # raw model output, kept for debugging
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "direction_bias": self.direction_bias,
            "current_price_estimate": self.current_price_estimate,
            "key_levels": self.key_levels,
            "active_zones": self.active_zones,
            "session_context": self.session_context,
            "narrative": self.narrative,
            "trade_idea": self.trade_idea,
            "model": self.model,
        }


class ChartVision:
    """Adapter around an Ollama vision model. Stateless beyond the client."""

    def __init__(
        self,
        client: OllamaClient | None = None,
        model: str | None = None,
    ):
        self.client = client or OllamaClient()
        # If the caller didn't pin a model, ask the daemon for any vision tag.
        self.model = model or self.client.find_vision_model()

    def is_available(self) -> bool:
        return self.client.is_alive() and self.model is not None

    @staticmethod
    def _encode_image(path: Path | str | bytes) -> str:
        """Base64-encode a PNG/JPEG file or raw bytes for the Ollama API."""
        if isinstance(path, (bytes, bytearray)):
            return base64.b64encode(path).decode("ascii")
        data = Path(path).read_bytes()
        return base64.b64encode(data).decode("ascii")

    def analyse(
        self,
        image: Path | str | bytes,
        *,
        extra_context: str = "",
        temperature: float = 0.1,
    ) -> ChartReading:
        """Run a single-image analysis and return a parsed :class:`ChartReading`.

        Raises :class:`OllamaUnavailable` if the daemon or model is missing —
        callers should catch and surface a friendly "vision disabled" message.
        """
        if not self.is_available():
            raise OllamaUnavailable(
                "no vision model installed (try `ollama pull llava-phi3`)"
            )
        b64 = self._encode_image(image)
        prompt = USER_PROMPT_TEMPLATE.format(
            extra_context=extra_context.strip() or "No extra context provided."
        )
        # Some vision models (llava-phi3) do not always honour `format: 'json'`;
        # we still ask for it because llama3.2-vision and qwen-vl do, and we
        # have a fallback regex extractor below.
        raw = self.client.chat(
            self.model,
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            images=[b64],
            json_mode=True,
            temperature=temperature,
            # Vision models are verbose; allow enough headroom that even a
            # bullet-y key-levels list doesn't get truncated mid-JSON.
            max_tokens=1500,
        )
        return self._parse(raw)

    def _parse(self, raw: str) -> ChartReading:
        out = ChartReading(raw=raw, model=self.model or "")
        if not raw:
            return out
        # Try strict JSON first, then fall back to a few extraction strategies:
        #   * strip ```json fences if the model wrapped it
        #   * non-greedy first {...} (handles models that emit prose then JSON)
        #   * greedy {...} (handles models that emit JSON then trailing prose)
        data: dict[str, Any] | None = None
        text = raw.strip()
        # Strip Markdown fences (```json ... ```)
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            for pattern in (r"\{[\s\S]*?\}\s*$", r"\{[\s\S]*\}", r"\{[\s\S]*?\}"):
                m = re.search(pattern, text)
                if not m:
                    continue
                try:
                    data = json.loads(m.group(0))
                    break
                except json.JSONDecodeError:
                    continue
            if data is None:
                log.warning("vision model returned non-JSON, keeping raw")
        if not data:
            out.narrative = raw.strip()[:500]
            return out
        out.timeframe = str(data.get("timeframe") or "unknown")
        out.direction_bias = str(data.get("direction_bias") or "neutral")
        cp = data.get("current_price_estimate")
        try:
            out.current_price_estimate = float(cp) if cp is not None else None
        except (TypeError, ValueError):
            out.current_price_estimate = None
        if isinstance(data.get("key_levels"), list):
            out.key_levels = [
                lv for lv in data["key_levels"]
                if isinstance(lv, dict) and "price" in lv
            ]
        if isinstance(data.get("active_zones"), list):
            out.active_zones = [str(z) for z in data["active_zones"]][:8]
        out.session_context = str(data.get("session_context") or "unknown")
        out.narrative = str(data.get("narrative") or "").strip()
        if isinstance(data.get("trade_idea"), dict):
            out.trade_idea = data["trade_idea"]
        return out
