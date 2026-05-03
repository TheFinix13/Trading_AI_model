"""Thin HTTP client for a local Ollama daemon.

Why a hand-rolled client instead of the ``ollama`` Python package?
  * Zero new dependencies — ``httpx`` is already required by FastAPI/uvicorn.
  * We only need two endpoints (``/api/chat`` and ``/api/tags``) so the surface
    is tiny and easy to mock in tests.
  * We want graceful behaviour when the daemon isn't running — every public
    method either returns a clear ``None``/raises :class:`OllamaUnavailable`,
    so callers can route around it (e.g. ``teach.py`` falls back to
    interactive YAML).

All requests go to ``http://localhost:11434`` by default. The host can be
overridden via the ``OLLAMA_HOST`` env var or ``OllamaClient(host=...)``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Iterator

import httpx

log = logging.getLogger(__name__)


class OllamaUnavailable(RuntimeError):
    """Raised when the daemon is unreachable or returns a non-2xx status.
    Callers should treat this as "LLM features disabled" and degrade gracefully."""


class OllamaClient:
    """Synchronous Ollama client. One instance is fine for the whole process."""

    def __init__(
        self,
        host: str | None = None,
        timeout: float = 120.0,
    ):
        self.host = (host or os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    # ----- low-level helpers --------------------------------------------------

    def _post(self, path: str, payload: dict) -> httpx.Response:
        try:
            return self._client.post(f"{self.host}{path}", json=payload)
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"POST {path} failed: {e}") from e

    def _get(self, path: str) -> httpx.Response:
        try:
            return self._client.get(f"{self.host}{path}")
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"GET {path} failed: {e}") from e

    # ----- introspection ------------------------------------------------------

    def is_alive(self) -> bool:
        """True if the daemon answers ``/api/tags`` within the timeout."""
        try:
            r = self._client.get(f"{self.host}/api/tags", timeout=2.0)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        r = self._get("/api/tags")
        if r.status_code != 200:
            raise OllamaUnavailable(f"/api/tags returned {r.status_code}")
        return [m["name"] for m in r.json().get("models", [])]

    def has_model(self, name: str) -> bool:
        try:
            tags = self.list_models()
        except OllamaUnavailable:
            return False
        # Ollama tags include the version suffix (e.g. "qwen2.5:14b-instruct").
        # Match either an exact tag or a prefix so callers can pass either.
        return any(t == name or t.startswith(name + ":") or name.startswith(t.split(":")[0]) for t in tags)

    # ----- generation ---------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        images: list[str] | None = None,
    ) -> str:
        """Single-shot, non-streaming chat. Returns the assistant message content.

        ``json_mode=True`` asks the model to emit valid JSON (Ollama's
        ``format: 'json'`` flag). Combine this with a system prompt that
        spells out the schema for reliable extraction.

        ``images`` is a list of base64-encoded image strings to attach to the
        last user message (vision-model only). Supported by llava, llava-phi3,
        moondream, llama3.2-vision, etc. Standard text models will ignore them."""
        # Vision: Ollama's API accepts an `images` field on each message that
        # is a list of base64 PNGs/JPEGs. We attach to the LAST user message.
        if images:
            messages = [m.copy() for m in messages]
            for m in reversed(messages):
                if m.get("role") == "user":
                    m["images"] = images
                    break
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        r = self._post("/api/chat", payload)
        if r.status_code != 200:
            raise OllamaUnavailable(f"/api/chat returned {r.status_code}: {r.text[:200]}")
        body = r.json()
        return body.get("message", {}).get("content", "").strip()

    # ----- vision -------------------------------------------------------------

    KNOWN_VISION_PREFIXES = (
        "llava", "llava-phi3", "llava-llama3", "bakllava", "moondream",
        "llama3.2-vision", "qwen2-vl", "qwen2.5-vl", "minicpm-v",
    )

    def find_vision_model(self) -> str | None:
        """Return the first locally-installed vision-capable model, or None."""
        try:
            tags = self.list_models()
        except OllamaUnavailable:
            return None
        for tag in tags:
            base = tag.split(":")[0].lower()
            if any(base.startswith(p) for p in self.KNOWN_VISION_PREFIXES):
                return tag
        return None

    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.4,
    ) -> Iterator[str]:
        """Yield content chunks as they arrive. Used by the dashboard chat UI."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }
        try:
            with self._client.stream("POST", f"{self.host}/api/chat", json=payload) as r:
                if r.status_code != 200:
                    raise OllamaUnavailable(f"/api/chat returned {r.status_code}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = chunk.get("message", {})
                    if (content := msg.get("content")):
                        yield content
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"stream failed: {e}") from e

    def close(self) -> None:
        self._client.close()
