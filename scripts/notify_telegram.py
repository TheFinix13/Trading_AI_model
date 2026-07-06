"""One-off Telegram smoke test / ad-hoc pusher.

Sends a single message through :class:`agent.notifications.telegram.
TelegramNotifier` using whatever ``TG_BOT_TOKEN`` / ``TG_CHAT_ID`` are set
in ``.env`` (or the environment). Use this to confirm a bot/chat pair
actually works BEFORE trusting it to page you about a live halt.

Usage:
    # Plain text message
    python scripts/notify_telegram.py "hello from the VM"

    # Print instead of sending (no network, no credentials needed)
    python scripts/notify_telegram.py --dry-run "preview only"

    # Simulate a drawdown-halt alert (exact format the monitor sends)
    python scripts/notify_telegram.py --dd-halt --account exness_demo --dd-pct 0.06

Exit code is 0 on a confirmed send (or any dry-run), 1 if Telegram
rejected the message or the credentials are missing/invalid — so this
doubles as a scriptable "is Telegram configured correctly?" check.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from agent.config import PROJECT_ROOT  # noqa: E402
from agent.notifications.telegram import TelegramNotifier  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send a one-off Telegram message.")
    p.add_argument("text", nargs="?", default=None,
                   help="Message text (required unless --dd-halt)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the message instead of calling the Telegram API")
    p.add_argument("--dd-halt", action="store_true",
                   help="Send a drawdown-halt alert instead of a plain message")
    p.add_argument("--account", default="unknown",
                   help="Account label for --dd-halt (default: unknown)")
    p.add_argument("--dd-pct", type=float, default=0.0,
                   help="Drawdown fraction for --dd-halt, e.g. 0.06 for 6%%")
    args = p.parse_args()
    if not args.dd_halt and not args.text:
        p.error("either provide a message or pass --dd-halt")
    return args


def main() -> None:
    args = parse_args()
    notifier = TelegramNotifier.from_env(dry_run=args.dry_run)

    if not args.dry_run and not notifier.config.configured:
        print("TG_BOT_TOKEN / TG_CHAT_ID are not set (checked .env + environment). "
              "Nothing sent. Pass --dry-run to preview without credentials.",
              file=sys.stderr)
        sys.exit(1)

    if args.dd_halt:
        ok = notifier.notify_dd_halt(args.account, args.dd_pct)
    else:
        ok = notifier.notify_text(args.text)

    if args.dry_run:
        sys.exit(0)
    if ok:
        print("Sent.")
        sys.exit(0)
    print("Telegram API call failed — check TG_BOT_TOKEN / TG_CHAT_ID and that "
          "you've messaged the bot at least once.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
