"""Conversational chat service.

Used by both ``scripts/ask.py`` (terminal) and the dashboard ``/chat`` route.
The service is intentionally thin — it owns the system prompt, manages the
conversation history, and forwards to :class:`OllamaClient`. *Context* (live
bias, recent trades, journal stats) is injected by the caller via
:class:`agent.conversation.context.ContextBuilder` so the LLM stays small
and stateless.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Literal

from agent.llm.ollama import OllamaClient, OllamaUnavailable

log = logging.getLogger(__name__)

DEFAULT_CHAT_MODEL = "qwen2.5:7b-instruct"

Role = Literal["system", "user", "assistant"]


@dataclass
class ChatMessage:
    role: Role
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


SYSTEM_PROMPT = """You are the user's personal trading partner — a co-trader for EURUSD.

You know:
  * The user trades supply/demand zones, FVGs, BOS/CHoCH, fib retracements,
    trendlines, and liquidity sweeps. They use D1 + H4 for bias only and
    take entries on H1 / M15 / M5.
  * They run an event-driven backtester + ML scorer (see the journal below).
  * They prize: candle-close confirmation, false-breakout filters, stacked
    confluence with explicit timeframe attribution, NY-time analysis.

Your job is to:
  1. Answer their questions plainly. Be specific about prices, timeframes,
     and the *source* of each observation ("PDH at 1.17680 on D1", not
     "the daily high").
  2. When you don't know something — say so. Never invent a level.
  3. Push back if their plan ignores a confluence the journal contains.
  4. Keep responses tight. The user is at a chart and needs signal, not prose.

You will be given CONTEXT in the user message (recent trades, current bias,
detected setups). Use it. If something contradicts the context, flag it.
"""


class ChatService:
    """Stateful chat session. Persist `history` if you want it to survive restarts."""

    def __init__(
        self,
        client: OllamaClient | None = None,
        model: str = DEFAULT_CHAT_MODEL,
        max_history: int = 30,
    ):
        self.client = client or OllamaClient()
        self.model = model
        self.history: list[ChatMessage] = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
        self.max_history = max_history

    def is_available(self) -> bool:
        return self.client.is_alive() and self.client.has_model(self.model.split(":")[0])

    def reset(self) -> None:
        self.history = [ChatMessage(role="system", content=SYSTEM_PROMPT)]

    def _truncate(self) -> None:
        # Always keep the system message + latest (max_history - 1) turns.
        if len(self.history) > self.max_history:
            keep = [self.history[0]] + self.history[-(self.max_history - 1) :]
            self.history = keep

    def ask(self, user_message: str, *, context: str | None = None) -> str:
        """Single-shot reply. Adds both the user turn and the assistant reply to history."""
        prompt = user_message
        if context:
            prompt = f"[CONTEXT]\n{context}\n[/CONTEXT]\n\n{user_message}"
        self.history.append(ChatMessage(role="user", content=prompt))
        self._truncate()
        try:
            reply = self.client.chat(
                model=self.model,
                messages=[m.as_dict() for m in self.history],
                temperature=0.4,
            )
        except OllamaUnavailable:
            self.history.pop()  # don't pollute history with a failed turn
            raise
        self.history.append(ChatMessage(role="assistant", content=reply))
        return reply

    def ask_stream(self, user_message: str, *, context: str | None = None) -> Iterator[str]:
        """Streaming reply. Caller is responsible for buffering and storing the final
        assistant message via :meth:`commit_streamed_reply`."""
        prompt = user_message
        if context:
            prompt = f"[CONTEXT]\n{context}\n[/CONTEXT]\n\n{user_message}"
        self.history.append(ChatMessage(role="user", content=prompt))
        self._truncate()
        try:
            yield from self.client.chat_stream(
                model=self.model,
                messages=[m.as_dict() for m in self.history],
            )
        except OllamaUnavailable:
            self.history.pop()
            raise

    def commit_streamed_reply(self, full_text: str) -> None:
        self.history.append(ChatMessage(role="assistant", content=full_text))
