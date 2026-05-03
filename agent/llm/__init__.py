"""LLM layer.

The agent uses an LLM for two purposes:

  1. **Structured extraction** — turn free-form trader paragraphs into typed
     :class:`TradeLesson` objects so they can be journaled and replayed.
  2. **Conversational chat** — let the user ask the agent questions about its
     bias, journal, or live setups in natural language.

Both tasks run against a *local* model via Ollama (http://localhost:11434) by
default. No data leaves the machine; no API keys required. If Ollama is
unreachable the components raise :class:`OllamaUnavailable` and callers can
fall back to a deterministic mode (e.g. interactive YAML in ``teach.py``).
"""
from __future__ import annotations

from agent.llm.ollama import OllamaClient, OllamaUnavailable
from agent.llm.extractor import LessonExtractor, TradeLesson
from agent.llm.chat import ChatMessage, ChatService

__all__ = [
    "OllamaClient",
    "OllamaUnavailable",
    "LessonExtractor",
    "TradeLesson",
    "ChatMessage",
    "ChatService",
]
