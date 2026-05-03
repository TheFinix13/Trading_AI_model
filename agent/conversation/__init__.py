"""Conversation layer that wraps the LLM with project context.

The LLM in :mod:`agent.llm` is generic. This package adapts it to the trading
domain by:

  * Pulling relevant context per question (recent trades, today's bias,
    detected setups, daily levels) — see :class:`ContextBuilder`.
  * Replaying the agent at a human's trade timestamp to produce side-by-side
    diffs — see :class:`ReplayDiffer`.
"""
from agent.conversation.context import ContextBuilder
from agent.conversation.replay import ReplayDiffer

__all__ = ["ContextBuilder", "ReplayDiffer"]
