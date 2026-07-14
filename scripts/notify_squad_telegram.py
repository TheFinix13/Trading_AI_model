"""One-off smoke test for the DEDICATED squad Telegram bot (v2).

Sends a single test message through the squad notifier so you can
confirm the new bot/chat pair works BEFORE trusting it to commentate a
paper-loop run. Credentials resolve exactly like the paper loop does:
``[telegram]`` in ``platform.toml`` wins per key, then
``SQUAD_TELEGRAM_BOT_TOKEN`` / ``SQUAD_TELEGRAM_CHAT_ID`` from ``.env``
or the environment. The v1 bot's ``TG_BOT_TOKEN`` / ``TG_CHAT_ID`` are
deliberately NOT consulted — the squad channel is separate by design.

Usage:
    # Send a test GOAL message through the squad bot
    python scripts/notify_squad_telegram.py

    # Custom text instead of the sample GOAL
    python scripts/notify_squad_telegram.py "squad bot check"

    # Print instead of sending (no network, no credentials needed)
    python scripts/notify_squad_telegram.py --dry-run

Exit code is 0 on a confirmed send (or any dry-run), 1 if the squad bot
is unconfigured or Telegram rejected the message — so this doubles as a
scriptable "is the squad bot wired correctly?" check.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from agent.notifications.telegram import TelegramNotifier  # noqa: E402
from agent.platform.config import load_config  # noqa: E402
from agent.platform.squad_notify import build_squad_goal, resolve_config  # noqa: E402

load_dotenv(REPO_ROOT / ".env", override=False)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Send a one-off test message via the squad Telegram bot.")
    ap.add_argument("text", nargs="?", default=None,
                    help="message text (default: a sample GOAL message)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the message instead of calling Telegram")
    args = ap.parse_args()

    cfg = load_config(REPO_ROOT)
    config, _ = resolve_config(cfg.get("telegram"), dry_run=args.dry_run)

    if not args.dry_run and not config.configured:
        print("Squad Telegram bot is not configured. Set [telegram] "
              "bot_token/chat_id in platform.toml, or "
              "SQUAD_TELEGRAM_BOT_TOKEN / SQUAD_TELEGRAM_CHAT_ID in .env. "
              "Nothing sent; pass --dry-run to preview without credentials.",
              file=sys.stderr)
        sys.exit(1)

    text = args.text or build_squad_goal(
        agent_id="isagi_yoichi", symbol="EURUSD", pips=42.5, tqs=0.61,
        r_multiple=1.5, exit_reason="test message — squad bot smoke check")

    ok = TelegramNotifier(config).notify_text(text)
    if args.dry_run:
        sys.exit(0)
    if ok:
        print("Sent via the squad bot.")
        sys.exit(0)
    print("Squad Telegram send failed — check the token/chat id and that "
          "you've messaged the new bot at least once.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
