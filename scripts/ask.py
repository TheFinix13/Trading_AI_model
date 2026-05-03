"""Terminal chat with the trading agent.

Examples:

    # interactive REPL
    python scripts/ask.py

    # one-shot question
    python scripts/ask.py "what was my best trade this week?"

    # one-shot, streamed (default if Ollama supports it)
    python scripts/ask.py --stream "what's your bias on EURUSD right now?"

    # pipe a question
    echo "explain trade 9" | python scripts/ask.py --stdin

The CLI uses :class:`agent.llm.chat.ChatService` for the LLM and
:class:`agent.conversation.context.ContextBuilder` to inject relevant
journal/live data per turn.  Every conversation is persisted in
``chat_sessions``/``chat_messages`` so dashboards can replay them.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.config import load_config
from agent.conversation.context import ContextBuilder
from agent.journal.db import Journal
from agent.llm.chat import ChatService
from agent.llm.ollama import OllamaUnavailable

PROMPT = ">>> "
EXIT_WORDS = {"exit", "quit", "bye", ":q"}


def _print_streaming(chunks):
    buf = []
    for c in chunks:
        sys.stdout.write(c)
        sys.stdout.flush()
        buf.append(c)
    print()
    return "".join(buf)


def _greet(chat: ChatService) -> None:
    print("=" * 70)
    print(" EURUSD AI Agent — chat")
    print(f" model: {chat.model}   (type 'exit' or Ctrl-D to quit)")
    print("=" * 70)


def main():
    p = argparse.ArgumentParser(description="Terminal chat with the trading agent.")
    p.add_argument("question", nargs="*", help="One-shot question (omit for REPL)")
    p.add_argument("--stdin", action="store_true", help="Read the question from stdin")
    p.add_argument("--stream", action="store_true", help="Stream tokens as they arrive")
    p.add_argument("--model", default=None, help="Override Ollama chat model (default: qwen2.5:7b-instruct)")
    p.add_argument("--no-context", action="store_true", help="Don't auto-inject journal context")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    cfg = load_config()
    chat = ChatService(model=args.model) if args.model else ChatService()
    if not chat.is_available():
        print("Ollama not reachable / model not pulled. Run:")
        print("  brew install ollama && brew services start ollama")
        print(f"  ollama pull {chat.model}")
        return 1

    ctx_builder = None if args.no_context else ContextBuilder.from_config()
    journal = Journal(cfg.journal_db)
    session_id = journal.create_chat_session(title=None)

    def _ask(question: str) -> str:
        context = ctx_builder.build(question) if ctx_builder else None
        journal.append_chat_message(session_id, "user", question, {"context": context} if context else None)
        try:
            if args.stream:
                print("\n", end="")
                reply = _print_streaming(chat.ask_stream(question, context=context))
                chat.commit_streamed_reply(reply)
            else:
                reply = chat.ask(question, context=context)
                print(f"\n{reply}\n")
        except OllamaUnavailable as e:
            print(f"\n(Ollama error: {e})")
            return ""
        journal.append_chat_message(session_id, "assistant", reply)
        return reply

    one_shot = " ".join(args.question).strip() if args.question else None
    if args.stdin:
        one_shot = sys.stdin.read().strip()

    if one_shot:
        _ask(one_shot)
        journal.close()
        return 0

    _greet(chat)
    while True:
        try:
            q = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n(bye)")
            break
        if not q:
            continue
        if q.lower() in EXIT_WORDS:
            print("(bye)")
            break
        if q.lower() == "/reset":
            chat.reset()
            print("(history cleared)")
            continue
        _ask(q)

    journal.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
