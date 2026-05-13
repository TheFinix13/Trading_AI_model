"""Cloud vision providers for chart analysis — Google Gemini and Anthropic Claude.

Both providers are optional: if their SDK isn't installed or no API key is set,
``is_available()`` returns False and ``get_best_vision_provider()`` skips them.
This keeps the app fully functional with local-only Ollama when no cloud keys
are configured.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Any

from agent.llm.vision import (
    ChartReading,
    MultiTimeframeReading,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    MULTI_TF_SYSTEM_PROMPT,
    MULTI_TF_USER_PROMPT,
    parse_multi_tf,
)

log = logging.getLogger(__name__)


class GeminiVision:
    """Chart analysis using Google Gemini Flash (free tier).

    Uses the ``google-genai`` SDK (``from google import genai``).
    The legacy ``google-generativeai`` package is deprecated.
    """

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model
        self._client = None

    @property
    def provider_name(self) -> str:
        return "gemini"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            from google import genai  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def analyse(
        self,
        image: Path | str | bytes,
        *,
        extra_context: str = "",
        temperature: float = 0.1,
    ) -> ChartReading:
        """Analyze a chart screenshot using Gemini."""
        from google.genai import types

        if isinstance(image, (bytes, bytearray)):
            img_data = image
        else:
            img_data = Path(image).read_bytes()

        mime_type = "image/png"
        if img_data[:3] == b"\xff\xd8\xff":
            mime_type = "image/jpeg"

        prompt = USER_PROMPT_TEMPLATE.format(
            extra_context=extra_context.strip() or "No extra context provided."
        )

        client = self._get_client()
        response = client.models.generate_content(
            model=self.model_name,
            contents=[
                types.Part.from_text(prompt),
                types.Part.from_bytes(data=img_data, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=temperature,
                max_output_tokens=2000,
            ),
        )

        raw = response.text
        return self._parse(raw)

    def analyse_multi(
        self,
        images: list[bytes],
        *,
        extra_context: str = "",
        temperature: float = 0.1,
    ) -> MultiTimeframeReading:
        """Analyze multiple chart screenshots for cross-timeframe confluences."""
        from google.genai import types

        parts = []
        prompt = MULTI_TF_USER_PROMPT.format(
            n_images=len(images),
            extra_context=extra_context.strip() or "No extra context provided.",
        )
        parts.append(types.Part.from_text(prompt))

        for img_data in images:
            mime_type = "image/png"
            if img_data[:3] == b"\xff\xd8\xff":
                mime_type = "image/jpeg"
            parts.append(types.Part.from_bytes(data=img_data, mime_type=mime_type))

        client = self._get_client()
        response = client.models.generate_content(
            model=self.model_name,
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=MULTI_TF_SYSTEM_PROMPT,
                temperature=temperature,
                max_output_tokens=4000,
            ),
        )

        raw = response.text
        result = parse_multi_tf(raw, model=f"gemini:{self.model_name}")
        return result

    def _parse(self, raw: str) -> ChartReading:
        """Parse Gemini's response into a ChartReading."""
        from agent.llm.vision import ChartVision

        parser = ChartVision.__new__(ChartVision)
        parser.model = self.model_name
        result = parser._parse(raw)
        result.model = f"gemini:{self.model_name}"
        return result


class ClaudeVision:
    """Chart analysis using Anthropic Claude (Sonnet/Opus)."""

    def __init__(
        self, api_key: str | None = None, model: str = "claude-sonnet-4-6"
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model_name = model
        self._client = None

    @property
    def provider_name(self) -> str:
        return "claude"

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def analyse(
        self,
        image: Path | str | bytes,
        *,
        extra_context: str = "",
        temperature: float = 0.1,
    ) -> ChartReading:
        """Analyze a chart screenshot using Claude."""
        if isinstance(image, (bytes, bytearray)):
            img_data = image
        else:
            img_data = Path(image).read_bytes()

        b64 = base64.b64encode(img_data).decode("ascii")

        media_type = "image/png"
        if img_data[:3] == b"\xff\xd8\xff":
            media_type = "image/jpeg"

        prompt = USER_PROMPT_TEMPLATE.format(
            extra_context=extra_context.strip() or "No extra context provided."
        )

        client = self._get_client()
        response = client.messages.create(
            model=self.model_name,
            max_tokens=2000,
            temperature=temperature,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        raw = response.content[0].text
        return self._parse(raw)

    def analyse_multi(
        self,
        images: list[bytes],
        *,
        extra_context: str = "",
        temperature: float = 0.1,
    ) -> MultiTimeframeReading:
        """Analyze multiple chart screenshots for cross-timeframe confluences."""
        content_parts: list[dict] = []
        for img_data in images:
            b64 = base64.b64encode(img_data).decode("ascii")
            media_type = "image/png"
            if img_data[:3] == b"\xff\xd8\xff":
                media_type = "image/jpeg"
            content_parts.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            })

        prompt = MULTI_TF_USER_PROMPT.format(
            n_images=len(images),
            extra_context=extra_context.strip() or "No extra context provided.",
        )
        content_parts.append({"type": "text", "text": prompt})

        client = self._get_client()
        response = client.messages.create(
            model=self.model_name,
            max_tokens=4000,
            temperature=temperature,
            system=MULTI_TF_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content_parts}],
        )

        raw = response.content[0].text
        result = parse_multi_tf(raw, model=f"claude:{self.model_name}")
        return result

    def _parse(self, raw: str) -> ChartReading:
        """Parse Claude's response into a ChartReading."""
        from agent.llm.vision import ChartVision

        parser = ChartVision.__new__(ChartVision)
        parser.model = self.model_name
        result = parser._parse(raw)
        result.model = f"claude:{self.model_name}"
        return result


def get_vision_provider(name: str | None = None):
    """Return a specific vision provider by name, or None if unavailable.

    ``name`` can be: "gemini", "claude", "local", or None (auto-detect).
    When None, delegates to :func:`get_best_vision_provider`.
    """
    if name is None or name == "auto":
        return get_best_vision_provider()

    if name == "claude":
        p = ClaudeVision()
        return p if p.is_available() else None

    if name == "gemini":
        p = GeminiVision()
        return p if p.is_available() else None

    if name == "local":
        from agent.llm.vision import ChartVision

        p = ChartVision()
        return p if p.is_available() else None

    return None


def get_best_vision_provider():
    """Return the best available vision provider, preferring cloud over local.

    Priority: Claude > Gemini > Local Ollama
    """
    claude_key = os.getenv("ANTHROPIC_API_KEY", "")
    if claude_key:
        provider = ClaudeVision(api_key=claude_key)
        if provider.is_available():
            log.info("Using Claude vision (cloud)")
            return provider

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        provider = GeminiVision(api_key=gemini_key)
        if provider.is_available():
            log.info("Using Gemini vision (cloud, free)")
            return provider

    try:
        from agent.llm.vision import ChartVision

        local = ChartVision()
        if local.is_available():
            log.info("Using local Ollama vision")
            return local
    except Exception:
        pass

    return None


def get_vision_provider_chain() -> list:
    """Return all available vision providers in priority order (Claude > Gemini > Local).

    Unlike :func:`get_best_vision_provider` which returns only the top pick,
    this returns the full chain so callers can implement fallback on failure.
    """
    chain: list = []

    claude_key = os.getenv("ANTHROPIC_API_KEY", "")
    if claude_key:
        provider = ClaudeVision(api_key=claude_key)
        if provider.is_available():
            chain.append(provider)

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        provider = GeminiVision(api_key=gemini_key)
        if provider.is_available():
            chain.append(provider)

    try:
        from agent.llm.vision import ChartVision
        local = ChartVision()
        if local.is_available():
            chain.append(local)
    except Exception:
        pass

    return chain


def get_vision_status() -> dict[str, Any]:
    """Return status info about all vision providers for the /api/vision/status endpoint."""
    providers = []

    # Claude
    claude = ClaudeVision()
    providers.append({
        "name": "claude",
        "label": "Claude (premium)",
        "available": claude.is_available(),
        "model": claude.model_name,
        "has_key": bool(os.getenv("ANTHROPIC_API_KEY", "")),
    })

    # Gemini
    gemini = GeminiVision()
    providers.append({
        "name": "gemini",
        "label": "Gemini (free)",
        "available": gemini.is_available(),
        "model": gemini.model_name,
        "has_key": bool(os.getenv("GEMINI_API_KEY", "")),
    })

    # Local Ollama
    local_available = False
    local_model = None
    try:
        from agent.llm.vision import ChartVision

        local = ChartVision()
        local_available = local.is_available()
        local_model = local.model
    except Exception:
        pass
    providers.append({
        "name": "local",
        "label": "Local Ollama (offline)",
        "available": local_available,
        "model": local_model,
        "has_key": True,
    })

    best = get_best_vision_provider()
    active_name = getattr(best, "provider_name", "local") if best else None

    return {
        "active_provider": active_name,
        "providers": providers,
    }
