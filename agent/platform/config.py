"""platform.toml loader — shared defaults for the platform server + tools.

Precedence: built-in defaults < ``platform.toml`` at the repo root <
CLI flags (the scripts pass ``default=cfg[...]`` to argparse, so an
explicit flag always wins). The file is optional; a missing or broken
file silently falls back to defaults so the server always starts.

Example file: ``platform.toml.example`` at the repo root.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_NAME = "platform.toml"


def _defaults(repo_root: Path) -> dict:
    return {
        "log_root": Path.home() / "Documents" / "TradingAgentLogs",
        "research_reviews": (repo_root.parent / "finance-research-experiments"
                             / "programs" / "M001_multi_agent_ensemble"
                             / "reviews"),
        "live_dir": None,   # derived from log_root below when unset
        "host": "127.0.0.1",
        "port": 8787,
        "auth_token": None,
        # Dedicated v2 squad Telegram bot ([telegram] table). Empty values
        # here fall back to SQUAD_TELEGRAM_BOT_TOKEN / SQUAD_TELEGRAM_CHAT_ID
        # env vars in agent.platform.squad_notify (toml wins per key).
        "telegram": {"bot_token": "", "chat_id": "", "summary_every": 10},
        # Paper loop cache selection ([paper_loop] table). CLI flags
        # (--cache / --aggregator) override these; when both file and
        # CLI leave everything empty, paper_loop.select_source_cache
        # auto-picks the newest g7_replay_cache_g7retry1-* under the
        # research reviews dir (so a fresh G7 second attempt shows up
        # on /v2 LIVE without config changes).
        "paper_loop": {"cache": "", "aggregator": ""},
        # Live-market squad paper runtime ([squad_live] table). CLI
        # flags on scripts/run_squad_live.py override these. Default
        # feed is resolved at runtime (mt5 on Windows, cache elsewhere)
        # when left empty.
        "squad_live": {
            "feed": "",
            "aggregator": "phi41",
            "poll_seconds": 45,
            "symbols": ["EURUSD", "GBPUSD", "USDCAD"],
        },
        # F009 -- per-install-token rate limit on non-localhost /api/*.
        # `requests_per_minute` sets both bucket capacity and refill rate.
        # Explicit `capacity` / `refill_per_sec` override.
        "rate_limit": {
            "requests_per_minute": 60,
            "capacity": None,
            "refill_per_sec": None,
        },
        # F009 -- install-token session expiry (auto-logout after N days
        # of no authenticated activity). Default 7 days.
        "session": {"expiry_days": 7},
        # F013/A005 -- approved-freshness window: an `approved` entry
        # is only executable for this many seconds after the click;
        # afterwards it flips to `approval_expired` and every gate
        # refuses it (fail-closed).
        "approvals": {"approved_ttl_seconds": 300},
        # F013 -- internal-only token used to gate
        # `POST /api/approvals/submit`. Sprint 2 does NOT call this
        # endpoint from any live pathway (D065). Left empty by default;
        # when empty, the endpoint refuses every request (fail-closed).
        "internal": {"token": ""},
        # F014 -- Telegram bridge for the alerts bus. Reuses the
        # bot_token / chat_id from [telegram] above (no new secret).
        # Default disabled; enable in platform.toml to route bus
        # events to Telegram.
        #
        # [alerts.telegram.ops] (CEO ops-split, 2026-07-24): SEPARATE
        # bot_token + chat_id for company/ops alerts (watchdog_alert).
        # Safety events (kill_switch_trip, platform_down) go to BOTH
        # destinations. Fail-closed: ops destination fires only when
        # enabled AND both fields are set; when absent/disabled,
        # ops events fall back to the primary destination.
        "alerts": {
            "telegram": {
                "enabled": False,
                "per_event": {
                    "trade_fill": True,
                    "stop_hit": True,
                    "kill_switch_trip": True,
                    "risk_budget_breach": True,
                    "approval_submitted": False,
                    "platform_down": True,
                    "watchdog_alert": True,
                },
                "ops": {
                    "enabled": False,
                    "bot_token": "",
                    "chat_id": "",
                },
            },
        },
        # F018 (Sprint 2b) -- demo-order executor. DEFAULT-DISABLED
        # (gate #5). `demo_only = true` is a REQUIRED acknowledgement:
        # the executor refuses when it is false or absent, and refuses
        # any connected server whose name doesn't match
        # `allowed_server_patterns` (fail-closed). Real-broker
        # connections stay a hard NO per escalation.md section 5.
        "live_executor": {
            "enabled": False,
            "demo_only": False,   # absent-in-toml == not acknowledged
            "allowed_server_patterns": ["*Trial*", "*Demo*", "*demo*"],
            "max_volume_lots": 0.01,
            "broker_alias": "",
        },
    }


def load_config(repo_root: Path, path: Path | None = None) -> dict:
    """Merged config dict. ``path`` overrides the default file location
    (used by tests)."""
    cfg = _defaults(repo_root)
    cfg_path = path or (repo_root / CONFIG_NAME)
    raw: dict = {}
    if cfg_path.is_file():
        try:
            raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            raw = {}
    for key in ("log_root", "research_reviews", "live_dir"):
        if raw.get(key):
            cfg[key] = Path(str(raw[key])).expanduser()
    if raw.get("host"):
        cfg["host"] = str(raw["host"])
    if raw.get("port"):
        try:
            cfg["port"] = int(raw["port"])
        except (TypeError, ValueError):
            pass
    if raw.get("auth_token"):
        cfg["auth_token"] = str(raw["auth_token"])
    tg = raw.get("telegram")
    if isinstance(tg, dict):
        for key in ("bot_token", "chat_id"):
            if tg.get(key):
                cfg["telegram"][key] = str(tg[key])
        if tg.get("summary_every"):
            try:
                cfg["telegram"]["summary_every"] = int(tg["summary_every"])
            except (TypeError, ValueError):
                pass
    pl = raw.get("paper_loop")
    if isinstance(pl, dict):
        for key in ("cache", "aggregator"):
            if pl.get(key):
                cfg["paper_loop"][key] = str(pl[key]).strip()
    sl = raw.get("squad_live")
    if isinstance(sl, dict):
        if sl.get("feed"):
            cfg["squad_live"]["feed"] = str(sl["feed"]).strip()
        if sl.get("aggregator"):
            cfg["squad_live"]["aggregator"] = str(sl["aggregator"]).strip()
        if sl.get("poll_seconds"):
            try:
                cfg["squad_live"]["poll_seconds"] = float(sl["poll_seconds"])
            except (TypeError, ValueError):
                pass
        if isinstance(sl.get("symbols"), list) and sl["symbols"]:
            cfg["squad_live"]["symbols"] = [str(s) for s in sl["symbols"]]
    rl = raw.get("rate_limit")
    if isinstance(rl, dict):
        if rl.get("requests_per_minute") is not None:
            try:
                cfg["rate_limit"]["requests_per_minute"] = int(
                    rl["requests_per_minute"])
            except (TypeError, ValueError):
                pass
        if rl.get("capacity") is not None:
            try:
                cfg["rate_limit"]["capacity"] = int(rl["capacity"])
            except (TypeError, ValueError):
                pass
        if rl.get("refill_per_sec") is not None:
            try:
                cfg["rate_limit"]["refill_per_sec"] = float(
                    rl["refill_per_sec"])
            except (TypeError, ValueError):
                pass
    se = raw.get("session")
    if isinstance(se, dict):
        if se.get("expiry_days") is not None:
            try:
                cfg["session"]["expiry_days"] = int(se["expiry_days"])
            except (TypeError, ValueError):
                pass
    approvals = raw.get("approvals")
    if isinstance(approvals, dict):
        if approvals.get("approved_ttl_seconds") is not None:
            try:
                ttl = int(approvals["approved_ttl_seconds"])
                if ttl > 0:
                    cfg["approvals"]["approved_ttl_seconds"] = ttl
            except (TypeError, ValueError):
                pass
    internal = raw.get("internal")
    if isinstance(internal, dict):
        if internal.get("token"):
            cfg["internal"]["token"] = str(internal["token"])
    ac = raw.get("alerts")
    if isinstance(ac, dict):
        tg = ac.get("telegram")
        if isinstance(tg, dict):
            if "enabled" in tg:
                cfg["alerts"]["telegram"]["enabled"] = bool(tg["enabled"])
            pe = tg.get("per_event")
            if isinstance(pe, dict):
                for k, v in pe.items():
                    if k in cfg["alerts"]["telegram"]["per_event"]:
                        cfg["alerts"]["telegram"]["per_event"][k] = bool(v)
            ops = tg.get("ops")
            if isinstance(ops, dict):
                if "enabled" in ops:
                    cfg["alerts"]["telegram"]["ops"]["enabled"] = bool(
                        ops["enabled"])
                for key in ("bot_token", "chat_id"):
                    if ops.get(key):
                        cfg["alerts"]["telegram"]["ops"][key] = str(ops[key])
    le = raw.get("live_executor")
    if isinstance(le, dict):
        if "enabled" in le:
            cfg["live_executor"]["enabled"] = bool(le["enabled"])
        # demo_only is a REQUIRED acknowledgement: only a literal TOML
        # `true` counts; anything else (absent, false, junk) leaves the
        # default False and the executor fails closed.
        cfg["live_executor"]["demo_only"] = le.get("demo_only") is True
        patterns = le.get("allowed_server_patterns")
        if isinstance(patterns, list):
            cleaned = [str(p).strip() for p in patterns if str(p).strip()]
            # An empty allowlist would match nothing -- keep it, that
            # is the fail-closed direction.
            cfg["live_executor"]["allowed_server_patterns"] = cleaned
        if le.get("max_volume_lots") is not None:
            try:
                vol = float(le["max_volume_lots"])
                if vol > 0:
                    cfg["live_executor"]["max_volume_lots"] = vol
            except (TypeError, ValueError):
                pass
        if le.get("broker_alias"):
            cfg["live_executor"]["broker_alias"] = str(
                le["broker_alias"]).strip()
    if cfg["live_dir"] is None:
        cfg["live_dir"] = Path(cfg["log_root"]) / "squad_live"
    return cfg
