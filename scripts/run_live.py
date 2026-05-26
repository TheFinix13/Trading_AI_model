"""Start the live trading agent.

Usage:
    # Paper trading (default, no broker needed, works on macOS):
    python scripts/run_live.py --broker paper --timeframe H1

    # MT5 demo (requires Windows or Docker bridge):
    python scripts/run_live.py --broker mt5 --timeframe H1 --lot 0.01

    # Exness demo via MT5:
    python scripts/run_live.py --broker exness --timeframe H1

    # Multiple timeframes:
    python scripts/run_live.py --broker paper --timeframe H1 --timeframe M15

Environment variables (from .env):
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH
    TG_BOT_TOKEN, TG_CHAT_ID
    AGENT_MODE (paper|live)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.live.signal_loop import run_signal_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_live")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EURUSD AI Agent — Live Trading Loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--broker", "-b",
        choices=["paper", "mt5", "exness"],
        default="paper",
        help="Broker connection type (default: paper)",
    )
    parser.add_argument(
        "--timeframe", "-t",
        action="append",
        default=None,
        help="Timeframe(s) to monitor (e.g. H1, M15). Can specify multiple.",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=None,
        help="Check interval in seconds (default: auto based on timeframe)",
    )
    parser.add_argument(
        "--lot",
        type=float,
        default=None,
        help="Fixed lot size override (bypasses risk calculator)",
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=None,
        help="Paper broker starting balance (default: 10000)",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="ML score threshold for trade entry (default: from config)",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Disable Telegram notifications",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config YAML file",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=" * 60)
    log.info("EURUSD AI Agent — Live Trading")
    log.info("=" * 60)
    log.info("Broker: %s", args.broker)
    log.info("Timeframes: %s", args.timeframe or ["H1 (default)"])

    if args.broker in ("mt5", "exness"):
        import os
        if not os.getenv("MT5_LOGIN"):
            log.error(
                "MT5_LOGIN not set. For %s broker, you need:\n"
                "  MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in your .env file.\n"
                "  See docs/exness_setup.md for details.\n"
                "  Use --broker paper to test without a real account.",
                args.broker,
            )
            sys.exit(1)

    # Build overrides dict
    overrides: dict = {}
    if args.interval is not None:
        overrides["check_interval_seconds"] = args.interval
    if args.lot is not None:
        overrides["lot_size_override"] = args.lot
    if args.balance is not None:
        overrides["paper_initial_balance"] = args.balance
    if args.score_threshold is not None:
        overrides["score_threshold"] = args.score_threshold
    if args.no_telegram:
        overrides["telegram_enabled"] = False

    # Set up graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(sig: signal.Signals) -> None:
        log.info("Received %s, shutting down...", sig.name)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    try:
        loop.run_until_complete(
            run_signal_loop(
                broker_type=args.broker,
                timeframes=args.timeframe,
                config_path=args.config,
                **overrides,
            )
        )
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
