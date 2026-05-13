"""CLI for sending one-off Telegram messages from a script / cron job.

Usage:
    python scripts/notify_telegram.py "deploy complete"
    python scripts/notify_telegram.py --dry-run "test message"
    python scripts/notify_telegram.py --dd-halt --account live --dd-pct 0.06
    python scripts/notify_telegram.py --trade-open path/to/trade.json   # future

Reads `TG_BOT_TOKEN` and `TG_CHAT_ID` from the environment unless --dry-run
is supplied. Set them in `.env` (auto-loaded by `agent.config`) for
convenience.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.notifications.telegram import (  # noqa: E402
    TelegramConfig,
    TelegramNotifier,
    format_dd_halt,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Send a Telegram notification")
    p.add_argument("text", nargs="?", help="Plain message body (Markdown allowed)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print to stdout instead of hitting the Telegram API")
    p.add_argument("--dd-halt", action="store_true",
                   help="Send a drawdown-halt alert instead of a plain text")
    p.add_argument("--account", default="live", help="Account label (used with --dd-halt)")
    p.add_argument("--dd-pct", type=float, default=0.05,
                   help="Drawdown fraction to report, 0..1 (used with --dd-halt)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = TelegramConfig.from_env(dry_run=args.dry_run)
    notifier = TelegramNotifier(cfg)

    if args.dd_halt:
        ok = notifier.notify_text(format_dd_halt(args.account, args.dd_pct))
    elif args.text:
        ok = notifier.notify_text(args.text)
    else:
        print("error: nothing to send (provide a message or --dd-halt)", file=sys.stderr)
        return 2

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
