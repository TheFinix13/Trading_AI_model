"""Start the v2 live trading agent.

Wraps :class:`agent.live.signal_loop.SignalLoop` with a small argparse + health
check shell. The v1 startup banner / ML / strategy-router checks were burned in
the v2 reset (those subsystems are gone). What remains is a focused health
ping for broker connectivity, the parquet cache, and the kill switch.

By default the process trades the VALIDATED zone strategy from the deployment
router (``agent.alphas.zone_routing``): the configured symbol's deployed
cell(s) determine the alpha, the polled timeframe, and the risk_scale applied
to position sizing. Symbols with no deployed cells refuse to start.

Usage:
    # Paper trading (default, no broker needed, works on macOS):
    python scripts/run_live.py --broker paper

    # MT5 demo (requires Windows or Docker bridge):
    python scripts/run_live.py --broker mt5

    # Exness demo via MT5:
    python scripts/run_live.py --broker exness

    # One process per deployed symbol (separate terminals):
    python scripts/run_live.py --broker exness --symbol EURUSD --verbose
    python scripts/run_live.py --broker exness --symbol GBPUSD --verbose
    python scripts/run_live.py --broker exness --symbol USDCAD --verbose

Environment variables (from .env):
    MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH
    TG_BOT_TOKEN, TG_CHAT_ID
    SYMBOL (default EURUSD; must have a deployed routing cell;
            overridden by --symbol)

Each process also writes a daily log file to a per-symbol folder under
~/Documents/TradingAgentLogs (override with --log-dir); see
``setup_live_logging``.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from agent.config import PROJECT_ROOT, load_config
from agent.journal.vault import VaultRecorder
from agent.live.broker import create_broker
from agent.live.config import LiveConfig
from agent.live.router_wiring import UndeployedSymbolError, build_live_routes
from agent.live.signal_loop import SignalLoop
from agent.utils import kill_switch_reason

load_dotenv(PROJECT_ROOT / ".env", override=False)

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# User-discoverable default (Explorer/Finder), NOT buried in the repo:
# C:\Users\<name>\Documents\TradingAgentLogs on Windows,
# ~/Documents/TradingAgentLogs on macOS/Linux. Override with --log-dir.
DEFAULT_LOG_ROOT = Path.home() / "Documents" / "TradingAgentLogs"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATEFMT,
)
log = logging.getLogger("run_live")


class _DailyDateFileHandler(logging.handlers.TimedRotatingFileHandler):
    """Daily file handler whose ACTIVE file is named symbol + current UTC day.

    The stock TimedRotatingFileHandler writes to a fixed base name and only
    appends the date when it rotates; here the symbol + ISO date IS the
    filename (``EURUSD_2026-06-10.log``), so files sort chronologically in
    Explorer, stay identifiable when downloaded/shared out of their folder,
    and a process left running for days produces exactly one file per UTC
    day. Rollover just switches to the new day's file — no renames.
    """

    def __init__(self, directory: Path, symbol: str, backup_count: int = 30):
        self._directory = directory
        self._symbol = symbol
        super().__init__(
            directory / self._current_name(), when="midnight", utc=True,
            backupCount=backup_count, encoding="utf-8", delay=False,
        )

    def _current_name(self) -> str:
        date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return f"{self._symbol}_{date}.log"

    def doRollover(self) -> None:  # noqa: N802 (logging API name)
        if self.stream:
            self.stream.close()
            self.stream = None
        self.baseFilename = os.fspath(self._directory / self._current_name())
        self.stream = self._open()

        if self.backupCount > 0:
            dated = sorted(
                p for p in self._directory.glob(f"{self._symbol}_????-??-??.log")
                if p.stem[-10:].replace("-", "").isdigit()
            )
            for old in dated[:-self.backupCount]:
                try:
                    old.unlink()
                except OSError:  # pragma: no cover - best-effort cleanup
                    pass

        # Same schedule arithmetic as the parent class.
        current_time = int(time.time())
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at += self.interval
        self.rolloverAt = new_rollover_at


def setup_live_logging(symbol: str, log_dir: Path | None = None) -> Path:
    """Attach a per-symbol daily log file to the ROOT logger.

    Layout: ``{log_dir}/{SYMBOL}/{SYMBOL}_{YYYY-MM-DD}.log`` (directories
    are created), one subfolder per symbol so three concurrent processes
    never mix lines, one symbol+date-named file per UTC day (rolls over at
    UTC midnight, 30 days kept). The symbol is in the FILENAME, not just the
    folder, so an individual file stays identifiable when downloaded or
    shared (WhatsApp etc.) without its folder. ``log_dir`` defaults to
    :data:`DEFAULT_LOG_ROOT` (~/Documents/TradingAgentLogs).

    The handler is attached to the root logger with no handler-level filter,
    so every ``agent.*`` logger flows into it and --verbose (which raises the
    ``agent.live`` logger to DEBUG) affects the file exactly as it affects
    the console. Returns the active (today's) log file path.
    """
    symbol_dir = (log_dir or DEFAULT_LOG_ROOT) / symbol
    symbol_dir.mkdir(parents=True, exist_ok=True)
    handler = _DailyDateFileHandler(symbol_dir, symbol, backup_count=30)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
    logging.getLogger().addHandler(handler)
    return Path(handler.baseFilename)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="EURUSD AI Agent — v2 Live Trading Loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--symbol", "-s",
        default=None,
        help="Trading symbol override (e.g. GBPUSD). Default: the SYMBOL "
             "env var / config (EURUSD). The symbol must have a deployed "
             "cell in the zone routing table or the process refuses to "
             "start.",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Root folder for log files (default: ~/Documents/"
             "TradingAgentLogs). Each symbol gets its own subfolder with "
             "one SYMBOL_YYYY-MM-DD.log file per UTC day.",
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
        help="Timeframe(s) to monitor (e.g. H1, M15). Can specify multiple. "
             "Ignored with --alpha router (the routing table fixes the TF).",
    )
    parser.add_argument(
        "--alpha",
        choices=["router", "reaction"],
        default="router",
        help="Alpha source (default: router = the validated zone routing "
             "table). 'reaction' runs the UNVALIDATED/experimental "
             "ReactionAlpha — never use it on a funded account.",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=None,
        help="Check interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--no-revenge-guard", action="store_true",
        help="Disable the post-loss cooldown / no-revenge guard (NOT recommended)",
    )
    parser.add_argument(
        "--balance", type=float, default=None,
        help="Paper broker starting balance (default: 10000)",
    )
    parser.add_argument(
        "--no-telegram", action="store_true",
        help="Disable Telegram notifications",
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to config YAML file",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging in agent.live",
    )
    parser.add_argument(
        "--kill-switch", choices=["on", "off"], default="on",
        help="Kill switch behaviour (default: on). 'off' ignores kill files.",
    )
    return parser.parse_args()


def _build_live_config(cfg, args: argparse.Namespace,
                       timeframes: list[str], log_root: Path) -> LiveConfig:
    # Kill file lives at {log_root}/{SYMBOL}/kill.txt — next to that symbol's
    # state.json and logs — NOT a bare "kill.txt" relative to the process's
    # CWD. Three symbol processes are normally launched from the same repo
    # directory, so a bare relative path is a single shared file: one
    # symbol's false-alarm auto-halt (e.g. a broker-maintenance disconnect
    # misread as a 100% drawdown) silently halted the other two symbols as
    # well, for days, with no indication why. Scoping it per symbol means a
    # false alarm on one pair can no longer take the others down with it.
    # (The separate, deliberately-global agent.config.kill_switch_file is
    # unaffected — that one is the manual "stop everything" master switch.)
    kill_file = str(log_root / cfg.symbol / "kill.txt")
    live = LiveConfig(
        symbol=cfg.symbol,
        timeframes=timeframes,
        broker_type=args.broker,
        mt5_login=int(cfg.mt5_login) if cfg.mt5_login else 0,
        mt5_password=cfg.mt5_password,
        mt5_server=cfg.mt5_server,
        mt5_path=cfg.mt5_path,
        check_interval_seconds=args.interval or 30,
        revenge_guard_enabled=not args.no_revenge_guard,
        paper_initial_balance=args.balance if args.balance is not None else 10000.0,
        telegram_enabled=not args.no_telegram,
        kill_file=kill_file,
    )
    return live


async def _startup_health(args: argparse.Namespace, cfg, live: LiveConfig) -> bool:
    broker = create_broker(
        broker_type=live.broker_type,
        login=live.mt5_login,
        password=live.mt5_password,
        server=live.mt5_server,
        path=live.mt5_path,
        initial_balance=live.paper_initial_balance,
        data_dir=cfg.data_dir,
    )
    try:
        ok = await broker.connect()
    except Exception as e:
        log.error("Broker connect failed: %s", e)
        ok = False
    if ok:
        info = await broker.get_account_info()
        log.info("Broker OK: %s balance=$%.2f", live.broker_type, info.balance)
        await broker.disconnect()
        return True
    log.error("Broker check failed for %s. Aborting startup.", live.broker_type)
    return False


def main() -> None:
    args = parse_args()
    if args.verbose:
        logging.getLogger("agent.live").setLevel(logging.DEBUG)
    if args.kill_switch == "off":
        os.environ["SKIP_KILL_SWITCH"] = "1"
        log.warning("Kill switch DISABLED for this run (SKIP_KILL_SWITCH=1).")
    if args.broker in ("mt5", "exness") and not os.getenv("MT5_LOGIN"):
        log.error("MT5_LOGIN not set. Configure .env or use --broker paper.")
        sys.exit(1)

    cfg = load_config(args.config)
    # Must happen BEFORE build_live_routes and _build_live_config: both read
    # cfg.symbol, so the flag overrides the SYMBOL env var / config default.
    if args.symbol:
        cfg.symbol = args.symbol.strip().upper()

    log_file = setup_live_logging(
        cfg.symbol, Path(args.log_dir) if args.log_dir else None)
    log.info("Logging to: %s", log_file)
    log.info("(one %s_YYYY-MM-DD.log file per UTC day in that folder; "
             "30 days kept)", cfg.symbol)

    log_root = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_ROOT

    # Observation-only near-miss/loss vault, stored beside the daily logs
    # ({log root}/{SYMBOL}/near_misses + /losses). Pure logging — never
    # influences gates, sizing or routing.
    vault = VaultRecorder(cfg.symbol, log_root)

    # Crash-resilient state sidecar: {log_root}/{SYMBOL}/state.json.
    # Lives next to the daily log files so it travels with the logs on
    # copy/download. One file per symbol; one process per symbol always.
    state_store_path = log_root / cfg.symbol / "state.json"
    log.info("State sidecar: %s", state_store_path)

    risk_scales: dict[str, float] = {}
    if args.alpha == "router":
        try:
            routes = build_live_routes(cfg.symbol, cfg)
        except UndeployedSymbolError as e:
            log.error("%s", e)
            sys.exit(1)
        alphas = [r.alpha for r in routes]
        risk_scales = {r.alpha.name: r.risk_scale for r in routes}
        for r in routes:
            # Records zone touches the HTF gate (alone) rejected.
            r.alpha.near_miss_hook = vault.alpha_hook(r.timeframe)
        # The routing table fixes the timeframe(s) the validated cells were
        # proven on; a CLI override here would silently change the strategy.
        timeframes = sorted({r.timeframe for r in routes})
        if args.timeframe and sorted(set(args.timeframe)) != timeframes:
            log.warning("--timeframe %s ignored: router cells for %s run on %s",
                        args.timeframe, cfg.symbol, timeframes)
        for r in routes:
            log.info("Routed cell: %s/%s/%s mode=%s risk_scale=%.2f alpha=%s",
                     r.symbol, r.timeframe, r.session, r.mode,
                     r.risk_scale, r.alpha.name)
    else:
        log.warning("Running UNVALIDATED experimental ReactionAlpha "
                    "(--alpha reaction). Not for funded accounts.")
        from agent.alphas.reaction_alpha import ReactionAlpha
        alphas = [ReactionAlpha(cfg, name="reaction")]
        timeframes = args.timeframe or [cfg.primary_timeframe]

    live = _build_live_config(cfg, args, timeframes, log_root)
    log.info("Kill file: %s", live.kill_file)

    # Pre-flight: a kill file surviving a VM/script restart is exactly what
    # silently halted the agent for days after the 2026-07-02 Exness
    # maintenance window — restarting PowerShell never cleared it, and
    # nothing printed WHY nothing was trading. Surface it loudly and refuse
    # to proceed rather than spin up a loop that will just keep skipping.
    for kill_path in (Path(live.kill_file), cfg.kill_switch_file):
        reason = kill_switch_reason(kill_path)
        if reason is not None:
            log.error(
                "REFUSING TO START: kill switch file already present at %s\n"
                "Reason recorded when it was created:\n%s\n"
                "Delete this file (after confirming it's safe to resume) "
                "and restart, or pass --kill-switch off to ignore it.",
                kill_path, reason,
            )
            sys.exit(1)

    health_loop = asyncio.new_event_loop()
    try:
        ok = health_loop.run_until_complete(_startup_health(args, cfg, live))
    finally:
        health_loop.close()
    if not ok:
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    signal_loop = SignalLoop(alphas, config=cfg, live_config=live,
                             risk_scales=risk_scales, verbose=args.verbose,
                             vault=vault, state_store_path=state_store_path)

    def _shutdown(sig: signal.Signals) -> None:
        log.info("Received %s, shutting down...", sig.name)
        loop.create_task(signal_loop.stop())

    for sig_type in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_type, _shutdown, sig_type)
        except NotImplementedError:
            signal.signal(sig_type, lambda *_: _shutdown(sig_type))

    started_at = datetime.now(tz=timezone.utc).isoformat()
    log.info("Starting v2 signal loop at %s", started_at)
    try:
        loop.run_until_complete(signal_loop.run())
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
