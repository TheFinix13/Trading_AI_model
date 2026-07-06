"""One-off healthcheck (dead-man's-switch) smoke test / manual ping.

Sends a single ping through :class:`agent.notifications.healthcheck.
HealthcheckPinger` using whatever ``HEALTHCHECK_URL`` / ``HEALTHCHECK_URL_
<SYMBOL>`` is set in ``.env`` (or the environment). Use this to confirm a
check URL actually works BEFORE trusting it to catch a real VM freeze.

Usage:
    # Plain success ping (shared HEALTHCHECK_URL)
    python scripts/ping_healthcheck.py

    # Ping the per-symbol check (HEALTHCHECK_URL_EURUSD)
    python scripts/ping_healthcheck.py --symbol EURUSD

    # Print instead of sending (no network, no URL needed)
    python scripts/ping_healthcheck.py --dry-run

    # Simulate the immediate-failure ping the monitor sends on an
    # emergency close / critical halt
    python scripts/ping_healthcheck.py --fail "test failure"

Exit code is 0 on a confirmed ping (or any dry-run), 1 if the check
rejected the ping or no URL is configured — so this doubles as a
scriptable "is the watchdog configured correctly?" check.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from agent.config import PROJECT_ROOT  # noqa: E402
from agent.notifications.healthcheck import HealthcheckPinger  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Send a one-off healthcheck ping.")
    p.add_argument("--symbol", default="",
                   help="Check HEALTHCHECK_URL_<SYMBOL> before falling back "
                        "to the shared HEALTHCHECK_URL")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the ping instead of calling the network")
    p.add_argument("--fail", metavar="MESSAGE", default=None,
                   help="Send an immediate failure ping instead of a "
                        "success heartbeat")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    pinger = HealthcheckPinger.from_env(symbol=args.symbol, dry_run=args.dry_run)

    if not args.dry_run and not pinger.config.configured:
        if args.symbol:
            env_desc = f"HEALTHCHECK_URL_{args.symbol.upper()} (or HEALTHCHECK_URL)"
        else:
            env_desc = "HEALTHCHECK_URL"
        print(f"{env_desc} is not set (checked .env + environment). "
              "Nothing sent. Pass --dry-run to preview without a URL.",
              file=sys.stderr)
        sys.exit(1)

    ok = pinger.ping_fail(args.fail) if args.fail is not None else pinger.ping()

    if args.dry_run:
        sys.exit(0)
    if ok:
        print("Pinged.")
        sys.exit(0)
    print("Healthcheck ping failed — check HEALTHCHECK_URL and that the "
          "check exists on your provider.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
