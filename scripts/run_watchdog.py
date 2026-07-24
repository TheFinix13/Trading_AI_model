"""F017 -- Ops Watchdog runner (cron / Windows Task Scheduler entry).

One-shot mode (default) runs the full check registry once, publishes
any state TRANSITIONS to the alerts bus (so the Telegram bridge can
carry them when configured), prints one line per check, and exits:

    0  every check ok / na
    1  at least one warn
    2  at least one alarm

Loop mode (``--loop N``) re-runs every N seconds and rewrites the
standard heartbeat file (``<config_dir>/watchdog_heartbeat.txt``) on
each pass so the watchdog itself is watchable.

    python scripts/run_watchdog.py                 # one shot
    python scripts/run_watchdog.py --loop 300      # every 5 minutes
    python scripts/run_watchdog.py --json          # machine-readable

The runner observes and notifies -- it never mutates the systems it
watches (F017 spec hard rule).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.platform import alerts_telegram, credentials, watchdog  # noqa: E402
from agent.platform.config import load_config  # noqa: E402

HEARTBEAT_FILENAME = "watchdog_heartbeat.txt"

_EXIT_BY_STATUS = {"ok": 0, "na": 0, "warn": 1, "alarm": 2}


def _configure_telegram(cfg: dict) -> None:
    """Attach the F014 Telegram bridge when platform.toml enables it,
    so watchdog_alert transitions page the operator. No-ops (fails
    closed) when the bridge is disabled or unconfigured.

    The [alerts.telegram.ops] block (CEO ops-split, 2026-07-24) wires
    a SEPARATE destination for ops alerts; when it is absent/disabled
    watchdog_alert falls back to the primary destination."""
    tg_cfg = cfg.get("alerts", {}).get("telegram", {})
    if tg_cfg.get("enabled"):
        alerts_telegram.configure(
            bot_token=str(cfg.get("telegram", {}).get("bot_token", "") or ""),
            chat_id=str(cfg.get("telegram", {}).get("chat_id", "") or ""),
            per_event=tg_cfg.get("per_event") or {},
            enabled=True)
    ops_cfg = tg_cfg.get("ops") or {}
    if ops_cfg.get("enabled"):
        alerts_telegram.configure_ops(
            bot_token=str(ops_cfg.get("bot_token", "") or ""),
            chat_id=str(ops_cfg.get("chat_id", "") or ""),
            enabled=True)
    alerts_telegram.start()


def _write_heartbeat(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        encoding="utf-8")
    except OSError:
        pass


def run_once(live_dir: Path | None, *, as_json: bool = False,
             log=print) -> int:
    """One registry pass. Returns the exit code for the worst status."""
    results = watchdog.run_checks(live_dir=live_dir)
    published = watchdog.publish_transitions(results)
    overall = watchdog.overall_status(results)
    if as_json:
        log(json.dumps({"checks": results, "overall": overall,
                        "published_transitions": published},
                       indent=2, sort_keys=True))
    else:
        for r in results:
            log(f"[{r['status']:>5}] {r['id']:<18} {r['detail']}")
        log(f"overall: {overall}"
            + (f" ({len(published)} transition alert(s) published)"
               if published else ""))
    return _EXIT_BY_STATUS.get(overall, 2)


def main(argv: list[str] | None = None) -> int:
    cfg = load_config(REPO_ROOT)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live-dir", type=Path, default=cfg["live_dir"],
                    help="squad_live output dir for the runtime_heartbeat "
                         "check (platform.toml default)")
    ap.add_argument("--loop", type=float, default=None, metavar="SECONDS",
                    help="re-run every N seconds instead of one-shot")
    ap.add_argument("--max-iterations", type=int, default=None,
                    help="stop the loop after N passes (tests / bounded runs)")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON per pass")
    args = ap.parse_args(argv)

    _configure_telegram(cfg)

    if args.loop is None:
        return run_once(args.live_dir, as_json=args.json)

    interval = max(1.0, float(args.loop))
    heartbeat = credentials._config_dir() / HEARTBEAT_FILENAME
    iterations = 0
    worst = 0
    while True:
        code = run_once(args.live_dir, as_json=args.json)
        worst = max(worst, code)
        _write_heartbeat(heartbeat)
        iterations += 1
        if args.max_iterations is not None \
                and iterations >= args.max_iterations:
            return worst
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return worst


if __name__ == "__main__":
    sys.exit(main())
