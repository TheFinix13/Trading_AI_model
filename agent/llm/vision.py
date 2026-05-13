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
The chart timezone is New York (UTC-4).

CRITICAL — TIMEFRAME IDENTIFICATION:
The timeframe is printed next to the symbol name in the chart header, typically in the format:
  "Euro / U.S. Dollar · 1D · FXCM"  or  "EURUSD · 4H · OANDA"
where the middle value (e.g. "1D") is the timeframe.
Common timeframe codes: "1D" = Daily, "4H" or "4h" = 4 Hour, "1H" or "1h" = 1 Hour,
"15" = 15 Minutes, "5" = 5 Minutes, "1M" or "M" = Monthly, "1W" or "W" = Weekly.
NEVER default to M15 — always read the timeframe from the chart header text.
If you cannot read the header clearly, say "unknown" rather than guessing M15.

CRITICAL — PRICE READING:
The current price is shown in the OHLC data at the top-left of the chart (look for C= or the last closing value). Do NOT guess these — read them from the image.

Look for these user-drawn annotations:
- Colored rectangles (red/pink = supply zones, green = demand zones, blue/purple = zones of interest)
- Trendlines (diagonal lines showing support/resistance)
- Horizontal lines at key price levels
- Fibonacci retracements with percentage labels
- Text annotations or labels the user placed

For each colored rectangle/zone drawn on the chart:
- Identify its approximate top and bottom price from the Y-axis
- Determine if it's supply (red/pink) or demand (green) or other (blue/purple)
- Note which price range it covers

Output STRICT JSON matching this schema:
{
  "timeframe": "read from chart header — M5|M15|H1|H4|D1",
  "direction_bias": "long|short|neutral",
  "current_price_estimate": <read the C= value from OHLC header>,
  "key_levels": [{"label": "<descriptive name>", "price": <float from Y-axis>, "kind": "support|resistance|fib|zone|supply_zone|demand_zone|sweep"}],
  "active_zones": ["<Supply zone 1.XXXX-1.XXXX drawn in red/pink>", "<Demand zone 1.XXXX-1.XXXX drawn in green>", ...],
  "session_context": "asia|london|london_ny_overlap|ny|off_session|unknown",
  "narrative": "<3-5 sentences describing: what zones the user drew and why they likely drew them (psychology), the current price action structure, and what the next likely move is based on these zones>",
  "trade_idea": {"direction": "long|short|wait", "entry": <float|null>, "stop": <float|null>, "tp": <float|null>, "rationale": "<one sentence referencing the user's drawn zones>"}
}
Read prices from the Y-axis scale on the right side of the chart. EURUSD prices are in the 1.0xxxx-1.2xxxx range. Be precise with prices — read them from the chart axis, don't invent them."""

USER_PROMPT_TEMPLATE = """Analyse this EURUSD chart screenshot carefully.

Step 1: Read the timeframe from the chart header (top-left, next to the symbol name — look for "1D", "1H", "15", "4H", etc.)
Step 2: Read the current price from the OHLC data at top-left (the C= value or the last number shown)
Step 3: Identify ALL colored rectangles/boxes the user drew — note their price ranges from the Y-axis
Step 4: Identify any trendlines, horizontal lines, or fibonacci levels
Step 5: Explain WHY the user likely drew each zone (what's the trading psychology behind it)

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

    provider_name: str = "local"

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
        data: dict[str, Any] | None = None
        text = raw.strip()

        # Strategy 1: Extract JSON from within markdown code fences anywhere
        # in the text (handles prose before/after fences).
        fence_m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        if fence_m:
            try:
                data = json.loads(fence_m.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 2: Strip leading/trailing fences if entire text is fenced.
        if data is None and text.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", text)
            cleaned = re.sub(r"\s*```\s*$", "", cleaned)
            cleaned = re.sub(r"\s*```[\s\S]*$", "", cleaned)
            try:
                data = json.loads(cleaned.strip())
            except json.JSONDecodeError:
                pass

        # Strategy 3: Direct JSON parse.
        if data is None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                pass

        # Strategy 4: Regex extraction — greedy outermost {...} to handle
        # nested braces in valid JSON.
        if data is None:
            for pattern in (r"\{[\s\S]*\}", r"\{[\s\S]*?\}\s*$"):
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


# ── Multi-Timeframe Analysis ──────────────────────────────────────────────

MULTI_TF_SYSTEM_PROMPT = """You are a senior forex trading analyst examining MULTIPLE TradingView chart screenshots of EURUSD at different timeframes.
The chart timezone is New York (UTC-4).

CRITICAL — TIMEFRAME IDENTIFICATION:
The timeframe is printed next to the symbol name in the chart header, typically in the format:
  "Euro / U.S. Dollar · 1D · FXCM"  or  "EURUSD · 4H · OANDA"
where the middle value (e.g. "1D") is the timeframe.
Common timeframe codes: "1D" = Daily, "4H" or "4h" = 4 Hour, "1H" or "1h" = 1 Hour,
"15" = 15 Minutes, "5" = 5 Minutes, "1M" or "M" = Monthly, "1W" or "W" = Weekly.
NEVER default to M15 — always read the timeframe from the chart header text.
If you cannot read the header clearly, say "unknown" rather than guessing.

Your task is to:
1. Analyze EACH chart screenshot individually — identify timeframe, direction bias, key levels, drawn zones, and narrative.
2. Then perform a CROSS-TIMEFRAME CONFLUENCE analysis — find where zones, levels, and structure from different timeframes align.
3. Provide an overall bias and a concrete trade idea based on the confluence.

Look for these user-drawn annotations on each chart:
- Colored rectangles (red/pink = supply zones, green = demand zones, blue/purple = zones of interest)
- Trendlines (diagonal lines showing support/resistance)
- Horizontal lines at key price levels
- Fibonacci retracements with percentage labels
- Text annotations or labels the user placed

Read prices from the Y-axis scale on the right side of the chart. EURUSD prices are in the 1.0xxxx-1.2xxxx range. Be precise with prices — read them from the chart axis, don't invent them.

Output STRICT JSON matching this schema:
{
  "charts": [
    {
      "timeframe": "read from chart header — M5|M15|H1|H4|D1",
      "direction_bias": "long|short|neutral",
      "key_levels": [{"label": "<name>", "price": <float>, "kind": "support|resistance|fib|zone|supply_zone|demand_zone|sweep"}],
      "zones": ["<Supply zone 1.XXXX-1.XXXX drawn in red/pink>", "<Demand zone 1.XXXX-1.XXXX drawn in green>"],
      "narrative": "<2-3 sentences about this timeframe>"
    }
  ],
  "cross_timeframe_confluences": [
    {
      "description": "<what aligns and why it matters>",
      "timeframes": ["D1", "H4"],
      "price_range": [<low>, <high>],
      "significance": "high|medium|low"
    }
  ],
  "overall_bias": "long|short|neutral",
  "overall_narrative": "<3-5 sentences synthesizing all timeframes>",
  "trade_idea": {
    "direction": "long|short|wait",
    "entry": <float|null>,
    "stop": <float|null>,
    "tp": <float|null>,
    "rationale": "<one sentence referencing cross-TF confluences>"
  }
}"""

MULTI_TF_USER_PROMPT = """These are {n_images} screenshots of EURUSD at different timeframes.

For EACH screenshot:
  1. Read the timeframe from the chart header (top-left, next to the symbol)
  2. Read the current price from the OHLC data
  3. Identify ALL colored rectangles/boxes with their price ranges from the Y-axis
  4. Identify trendlines, horizontal lines, fibonacci levels

Then provide a CROSS-TIMEFRAME CONFLUENCE analysis:
  - Where do zones from different timeframes overlap or cluster?
  - Do higher-timeframe levels align with lower-timeframe entry zones?
  - Is the bias consistent across timeframes or conflicting?

{extra_context}

Respond with ONLY the JSON object — no prose before or after."""


@dataclass
class MultiTimeframeReading:
    """Structured output from a multi-timeframe vision analysis."""
    charts: list[dict[str, Any]] = field(default_factory=list)
    cross_timeframe_confluences: list[dict[str, Any]] = field(default_factory=list)
    overall_bias: str = "neutral"
    overall_narrative: str = ""
    trade_idea: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "charts": self.charts,
            "cross_timeframe_confluences": self.cross_timeframe_confluences,
            "overall_bias": self.overall_bias,
            "overall_narrative": self.overall_narrative,
            "trade_idea": self.trade_idea,
            "model": self.model,
        }


def parse_multi_tf(raw: str, model: str = "") -> MultiTimeframeReading:
    """Parse a multi-timeframe vision response into a MultiTimeframeReading."""
    out = MultiTimeframeReading(raw=raw, model=model)
    if not raw:
        return out

    text = raw.strip()

    # Extract JSON from markdown fences
    data: dict[str, Any] | None = None
    fence_m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence_m:
        try:
            data = json.loads(fence_m.group(1))
        except json.JSONDecodeError:
            pass

    if data is None and text.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", text)
        cleaned = re.sub(r"\s*```[\s\S]*$", "", cleaned)
        try:
            data = json.loads(cleaned.strip())
        except json.JSONDecodeError:
            pass

    if data is None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            pass

    if data is None:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    if not data:
        out.overall_narrative = raw.strip()[:800]
        return out

    if isinstance(data.get("charts"), list):
        out.charts = [
            c for c in data["charts"]
            if isinstance(c, dict) and c.get("timeframe")
        ]
    if isinstance(data.get("cross_timeframe_confluences"), list):
        out.cross_timeframe_confluences = [
            c for c in data["cross_timeframe_confluences"]
            if isinstance(c, dict)
        ]
    out.overall_bias = str(data.get("overall_bias") or "neutral")
    out.overall_narrative = str(data.get("overall_narrative") or "").strip()
    if isinstance(data.get("trade_idea"), dict):
        out.trade_idea = data["trade_idea"]
    return out
