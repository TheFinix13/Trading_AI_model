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
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from agent.config import PROJECT_ROOT, load_config
from agent.live.broker import create_broker
from agent.live.config import LiveConfig
from agent.live.signal_loop import run_signal_loop

load_dotenv(PROJECT_ROOT / ".env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_live")

VERSION = "9b"
def _make_separator() -> str:
    # Some Windows terminals still default to cp1252 and can't print box-drawing chars.
    enc = (getattr(sys.stdout, "encoding", None) or "").lower()
    if "utf" not in enc:
        return "=" * 51
    return "\u2550" * 51  # ═ repeated


SEPARATOR = _make_separator()
_UNICODE_TERMINAL = "utf" in (getattr(sys.stdout, "encoding", None) or "").lower()
SYM_OK = "\u2713" if _UNICODE_TERMINAL else "OK"
SYM_FAIL = "X"
SYM_WARN = "!"


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
        help="Show every check cycle detail (without this, only heartbeat + signals are logged)",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip the startup health check",
    )
    parser.add_argument(
        "--kill-switch",
        choices=["on", "off"],
        default="on",
        help="Kill switch behavior (default: on). Use 'off' to ignore kill files.",
    )
    return parser.parse_args()


# ── Health Check ──────────────────────────────────────────────


def _check_models(model_dir: Path) -> tuple[list[str], list[str]]:
    """Return (found, missing) model file basenames."""
    expected = [
        "scorer_EURUSD_H1_v8.joblib",
        "scorer_EURUSD_LZI_H1_v1.joblib",
    ]
    found: list[str] = []
    missing: list[str] = []
    for name in expected:
        if (model_dir / name).exists():
            found.append(name)
        else:
            missing.append(name)
    # Also pick up any other joblib files present
    for p in sorted(model_dir.glob("*.joblib")):
        if p.name not in expected and p.name not in found:
            found.append(p.name)
    return found, missing


def _check_data(data_dir: Path, symbol: str, timeframes: list[str]) -> tuple[list[str], str]:
    """Check parquet data files exist and return latest bar timestamp."""
    found: list[str] = []
    latest_bar = ""
    for tf in timeframes:
        parquet = data_dir / f"{symbol}_{tf}.parquet"
        if parquet.exists():
            found.append(f"{symbol}_{tf}")
            try:
                import pandas as pd
                df = pd.read_parquet(parquet)
                if not df.empty:
                    last_ts = df.index[-1]
                    ts_str = str(last_ts)[:19]
                    if not latest_bar or ts_str > latest_bar:
                        latest_bar = ts_str
            except Exception:
                pass
    if not latest_bar:
        latest_bar = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M") + " UTC"
    return found, latest_bar


async def _check_broker(
    broker_type: str, login: int, password: str, server: str, path: str,
    initial_balance: float, data_dir: Path,
) -> tuple[bool, str, float]:
    """Test broker connectivity. Returns (ok, account_desc, balance)."""
    broker = create_broker(
        broker_type=broker_type,
        login=login,
        password=password,
        server=server,
        path=path,
        initial_balance=initial_balance,
        data_dir=data_dir,
    )
    try:
        connected = await broker.connect()
        if not connected:
            return False, "connection failed", 0.0
        info = await broker.get_account_info()
        desc = f"#{info.login}" if info.login else "paper"
        balance = info.balance
        await broker.disconnect()
        return True, desc, balance
    except Exception as e:
        return False, str(e)[:60], 0.0


def _check_kill_switch() -> bool:
    """Return True if any kill switch file is active."""
    for name in ("kill.txt", "kill_switch"):
        # Uses agent.utils.kill_switch_active, which respects SKIP_KILL_SWITCH.
        from agent.utils import kill_switch_active

        if kill_switch_active(PROJECT_ROOT / name):
            return True
    return False


def _print_banner(
    args: argparse.Namespace,
    config,
    broker_ok: bool,
    account_desc: str,
    balance: float,
    models_found: list[str],
    models_missing: list[str],
    latest_bar: str,
    kill_active: bool,
) -> None:
    """Print the formatted startup banner."""
    timeframes = args.timeframe or [config.primary_timeframe]
    tf_str = ", ".join(timeframes)
    lot = args.lot or config.risk.lot_min
    strategies = "LZI Retest, FVG Retest, SD Zone"
    lzi_threshold = 0.40
    generic_threshold = args.score_threshold or config.ml.prob_threshold
    risk_pct = config.risk.pct_target * 100
    dd_pct = config.risk.daily_dd_halt_pct * 100
    caution = ", ".join(config.session.caution_days) if config.session.caution_days else "None"

    mode_map = {"paper": "PAPER (local simulation)", "mt5": "DEMO (MT5)", "exness": "DEMO (Exness MT5)"}
    mode_label = mode_map.get(args.broker, args.broker.upper())

    total_models = len(models_found) + len(models_missing)
    if total_models == 0:
        total_models = 2

    print()
    print(SEPARATOR)
    print(f"  EURUSD AI Trading Agent v{VERSION}")
    print(f"  Mode: {mode_label}")
    print(f"  Timeframe: {tf_str}")
    print(f"  Lot size: {lot}")
    print(f"  Strategies: {strategies}")
    print(f"  Scorer: LZI v1 (threshold {lzi_threshold:.2f}) + Generic v8")
    print(f"  Risk: {risk_pct:.0f}% per trade, {dd_pct:.0f}% daily DD halt")
    print(f"  Caution days: {caution}")
    print(f"  Account: {account_desc} (${balance:,.2f})")
    print(SEPARATOR)

    # Broker
    if broker_ok:
        print(f"  [{SYM_OK}] {args.broker.upper()} connected")
    else:
        print(f"  [{SYM_FAIL}] {args.broker.upper()} connection FAILED")

    # Models
    if models_found and not models_missing:
        print(f"  [{SYM_OK}] Models loaded ({len(models_found)}/{total_models})")
    elif models_found:
        print(f"  [{SYM_WARN}] Models partial ({len(models_found)}/{total_models}) — missing: {', '.join(models_missing)}")
    else:
        print(f"  [{SYM_WARN}] No models found — running rules-only mode")

    # Data
    print(f"  [{SYM_OK}] Data current (last bar: {latest_bar})")

    # Kill switch
    if kill_active:
        if os.getenv("SKIP_KILL_SWITCH"):
            print(f"  [{SYM_WARN}] Kill switch present but IGNORED (SKIP_KILL_SWITCH=1)")
        else:
            print(f"  [{SYM_FAIL}] Kill switch ACTIVE — remove kill.txt or run with --kill-switch off")
    else:
        print(f"  [{SYM_OK}] No kill switch active")

    print()
    if broker_ok and not kill_active:
        print(f"  Watching for setups... (Ctrl+C to stop)")
    elif kill_active:
        if os.getenv("SKIP_KILL_SWITCH"):
            print(f"  Kill switch files will be ignored for this run.")
        else:
            print(f"  Remove kill.txt (or use --kill-switch off) and restart to begin trading.")
    else:
        print(f"  Fix broker connection and restart.")
    print(SEPARATOR)
    print()


async def startup_health_check(args: argparse.Namespace) -> bool:
    """Run all startup checks and print the banner. Returns True if OK to proceed."""
    config = load_config(args.config)
    timeframes = args.timeframe or [config.primary_timeframe]

    # Models
    models_found, models_missing = _check_models(config.model_dir)

    # Data
    _, latest_bar = _check_data(config.data_dir, config.symbol, timeframes)

    # Kill switch
    kill_active = _check_kill_switch()

    # Broker
    mt5_login = int(config.mt5_login) if config.mt5_login else 0
    balance_default = args.balance or 10000.0
    broker_ok, account_desc, balance = await _check_broker(
        broker_type=args.broker,
        login=mt5_login,
        password=config.mt5_password,
        server=config.mt5_server,
        path=config.mt5_path,
        initial_balance=balance_default,
        data_dir=config.data_dir,
    )

    _print_banner(
        args=args,
        config=config,
        broker_ok=broker_ok,
        account_desc=account_desc,
        balance=balance,
        models_found=models_found,
        models_missing=models_missing,
        latest_bar=latest_bar,
        kill_active=kill_active,
    )

    if not broker_ok and args.broker in ("mt5", "exness"):
        log.error("Broker connection failed. Is MetaTrader 5 open and logged in?")
        return False

    if kill_active:
        log.warning("Kill switch is active. Remove kill.txt to trade.")
        return False

    return True


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    args = parse_args()

    if args.verbose:
        logging.getLogger("agent.live").setLevel(logging.DEBUG)

    if args.kill_switch == "off":
        os.environ["SKIP_KILL_SWITCH"] = "1"
        log.warning("Kill switch is DISABLED for this run (SKIP_KILL_SWITCH=1).")

    if args.broker in ("mt5", "exness"):
        if not os.getenv("MT5_LOGIN"):
            log.error(
                "MT5_LOGIN not set. For %s broker, you need:\n"
                "  MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in your .env file.\n"
                "  See docs/deployment_guide.md for details.\n"
                "  Use --broker paper to test without a real account.",
                args.broker,
            )
            sys.exit(1)

    # Run startup health check
    if not args.skip_health:
        loop_check = asyncio.new_event_loop()
        try:
            ok = loop_check.run_until_complete(startup_health_check(args))
        finally:
            loop_check.close()

        if not ok:
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

    verbose = args.verbose

    # Set up graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(sig: signal.Signals) -> None:
        log.info("Received %s, shutting down...", sig.name)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig_type in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_type, _shutdown, sig_type)
        except NotImplementedError:
            # Windows ProactorEventLoop does not support add_signal_handler.
            # Ctrl+C still raises KeyboardInterrupt; SIGTERM handling is best-effort.
            signal.signal(sig_type, lambda *_: _shutdown(sig_type))

    try:
        loop.run_until_complete(
            run_signal_loop(
                broker_type=args.broker,
                timeframes=args.timeframe,
                config_path=args.config,
                verbose=verbose,
                **overrides,
            )
        )
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
