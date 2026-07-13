"""v1 data plane — live zones-agent status from its own log root.

Read-only collectors over what the running agent already writes
(``state.json`` sidecars, daily logs, kill files). Extracted from the
original ``scripts/serve_live_dashboard.py`` so the unified platform
server and tests share one implementation. No agent code is touched;
nothing here can affect trading.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Aliveness thresholds derive from the live loop's contracts: it polls
# every ~30 s and logs a heartbeat every 15 min, so >20 min of log
# silence is suspicious and >45 min means the process is likely gone.
ALIVE_MAX_AGE_S = 20 * 60
STALE_MAX_AGE_S = 45 * 60

# Log-line tags worth surfacing in the decision feed, mapped to a
# category the UI colours. Order matters — first match wins.
FEED_PATTERNS: list[tuple[str, str]] = [
    (r"\[TRADE OPENED\]", "trade"),
    (r"TRADE CLOSED|CLOSED \(cause unconfirmed\)", "trade"),
    (r"\[LADDER\]", "ladder"),
    (r"\[SOFT SL", "ladder"),
    (r"\[ORDER REJECTED\]", "block"),
    (r"blocked by post-loss guard", "block"),
    (r"blocked by RiskManager", "block"),
    (r"blocked by portfolio risk cap", "block"),
    (r"sized to zero lots", "block"),
    (r"rejected:", "signal"),
    (r"\[POSITION RESTORED\]", "info"),
    (r"\[STATE ", "info"),
    (r"Routed cell:", "info"),
    (r"kill switch|KILL SWITCH|HALTED", "halt"),
    (r"emergency|EMERGENCY", "halt"),
    (r"heartbeat:", "heartbeat"),
]
_FEED_RES = [(re.compile(pat), cat) for pat, cat in FEED_PATTERNS]
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")


def _classify(line: str) -> str | None:
    for rx, cat in _FEED_RES:
        if rx.search(line):
            return cat
    return None


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _recent_log_files(sym_dir: Path, symbol: str, days: int = 2) -> list[Path]:
    today = datetime.now(tz=timezone.utc).date()
    out = []
    for d in range(days - 1, -1, -1):
        day = today - timedelta(days=d)
        p = sym_dir / f"{symbol}_{day.isoformat()}.log"
        if p.exists():
            out.append(p)
    return out


def collect_feed(sym_dir: Path, symbol: str, max_events: int = 60) -> list[dict]:
    """Parse the last two daily logs into categorized feed events."""
    events: list[dict] = []
    for logfile in _recent_log_files(sym_dir, symbol):
        try:
            lines = logfile.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            cat = _classify(line)
            if cat is None:
                continue
            m = _TS_RE.match(line)
            ts = m.group(1) if m else ""
            # Strip the logger-name noise: keep timestamp + message tail.
            msg = line[m.end():].strip(" -") if m else line
            msg = re.sub(r"^[,\d]*\s*(INFO|WARNING|ERROR)\s+\S+\s*[-—]*\s*", "", msg)
            events.append({"ts": ts, "symbol": symbol, "cat": cat, "msg": msg[:300]})
    return events[-max_events:]


def collect_symbol(sym_dir: Path, repo_root: Path) -> dict:
    """Collect one symbol's live status from its log directory."""
    symbol = sym_dir.name
    now = datetime.now(tz=timezone.utc)

    state = _read_json(sym_dir / "state.json") or {}
    saved_at = state.get("saved_at")

    # Aliveness from the freshest daily log mtime (heartbeats land there
    # every 15 min even when nothing trades).
    last_activity: datetime | None = None
    for logfile in _recent_log_files(sym_dir, symbol):
        try:
            mtime = datetime.fromtimestamp(logfile.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if last_activity is None or mtime > last_activity:
            last_activity = mtime
    age_s = (now - last_activity).total_seconds() if last_activity else None
    if age_s is None:
        status = "no-data"
    elif age_s <= ALIVE_MAX_AGE_S:
        status = "alive"
    elif age_s <= STALE_MAX_AGE_S:
        status = "stale"
    else:
        status = "down"

    pm = state.get("position_monitor") or {}
    excursion = pm.get("excursion") or {}
    positions = []
    for ticket, ctx in (pm.get("entry_ctx") or {}).items():
        if not isinstance(ctx, dict):
            continue
        pos = {"ticket": ticket}
        for key in ("direction", "entry", "sl", "tp", "soft_stop", "lots",
                    "lot_size", "alpha", "timeframe", "opened_at"):
            if key in ctx:
                pos[key] = ctx[key]
        exc = excursion.get(ticket)
        if isinstance(exc, dict):
            pos["excursion"] = exc
        positions.append(pos)

    risk = state.get("risk_manager") or {}
    guard = state.get("post_loss_guard") or {}

    kill_file = sym_dir / "kill.txt"
    kill_reason = None
    if kill_file.exists():
        try:
            kill_reason = kill_file.read_text(encoding="utf-8")[:200].strip()
        except OSError:
            kill_reason = "(unreadable)"

    return {
        "symbol": symbol,
        "status": status,
        "age_seconds": age_s,
        "state_saved_at": saved_at,
        "positions": positions,
        "risk": {
            "day_pnl": risk.get("day_pnl"),
            "halted_today": risk.get("halted_today"),
            "day_open_balance": risk.get("day_open_balance"),
        },
        "guard": {
            "consecutive_losses": guard.get("consecutive_losses"),
            "session_halted": guard.get("session_halted"),
            "halt_reason": guard.get("halt_reason"),
            "cooldown_until": guard.get("cooldown_until_iso"),
            "size_multiplier": guard.get("size_multiplier"),
        },
        "kill_file": kill_reason,
        "feed": collect_feed(sym_dir, symbol),
    }


def collect_status(log_root: Path, repo_root: Path = REPO_ROOT) -> dict:
    """Full v1 payload: every symbol dir under the log root."""
    symbols = []
    if log_root.exists():
        for child in sorted(log_root.iterdir()):
            # Symbol dirs are UPPERCASE FX pairs holding daily logs.
            if child.is_dir() and re.fullmatch(r"[A-Z]{6}", child.name):
                symbols.append(collect_symbol(child, repo_root))
    global_kill = repo_root / "kill_switch"
    global_kill_reason = None
    if global_kill.exists():
        try:
            global_kill_reason = global_kill.read_text(encoding="utf-8")[:200].strip()
        except OSError:
            global_kill_reason = "(unreadable)"
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "log_root": str(log_root),
        "global_kill": global_kill_reason,
        "symbols": symbols,
    }
