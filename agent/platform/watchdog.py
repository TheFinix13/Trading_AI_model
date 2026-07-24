"""F017 -- Ops Watchdog: the no-black-boxes check registry.

Seven named health checks, each returning a small dict::

    {"id": <check id>, "status": "ok" | "warn" | "alarm" | "na",
     "detail": <human string>, "checked_at": <iso8601>}

Checks cover BOTH the trading runtime (heartbeat, calendar feed,
broker health, risk-state file) AND the company loop (intake SLA,
sprint pulse, ledger drift) -- per the CEO's 2026-07-24 directive:
"we need to be notified of irregular behaviors or problems within any
of our systems, including the company loop."

Design rules:

* **Observe, never mutate.** No check writes to the system it
  watches. The only file this module writes is its own
  ``<config_dir>/watchdog_state.json`` (last-known statuses, used for
  state-transition-only alert publishing).
* **Never raise.** A broken artefact degrades to ``alarm`` (with a
  descriptive detail) or ``na`` -- a watchdog that crashes on the
  problem it is meant to report is worse than none.
* **State-change-only publishing.** :func:`publish_transitions`
  publishes a ``watchdog_alert`` event to the F014 bus only when a
  check's status CHANGES into warn/alarm (or recovers back out of
  it). Steady-state polling publishes nothing.
* This module MUST NOT import from ``agent/live/*``, ``agent/risk/*``,
  or ``agent/squad/*`` (Sprint 2b zero-diff invariant). Runtime
  freshness is read via :func:`agent.platform.paper_loop.live_status`
  over the artefact files only.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from agent.platform import broker_health, credentials, paper_loop

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CHECK_IDS: tuple[str, ...] = (
    "runtime_heartbeat",
    "calendar_feed",
    "broker_health",
    "risk_state",
    "intake_sla",
    "sprint_pulse",
    "ledger_drift",
)

STATUSES: tuple[str, ...] = ("ok", "warn", "alarm", "na")

# Freshness thresholds (seconds).
RUNTIME_WARN_SECONDS: float = 5 * 60.0
RUNTIME_ALARM_SECONDS: float = 30 * 60.0
CALENDAR_WARN_SECONDS: float = 12 * 3600.0
CALENDAR_ALARM_SECONDS: float = 48 * 3600.0
INTAKE_P0_ALARM_SECONDS: float = 4 * 3600.0
INTAKE_P1_WARN_SECONDS: float = 7 * 86400.0
INTAKE_OPEN_WARN_SECONDS: float = 30 * 86400.0
SPRINT_QUIET_WARN_SECONDS: float = 7 * 86400.0

# Tolerance before a risk_state row counts as "future-dated" (clock
# skew between writer and reader is real on the VM).
FUTURE_SKEW_TOLERANCE_SECONDS: float = 120.0

SNAPSHOT_CACHE_SECONDS: float = 30.0
STATE_FILENAME: str = "watchdog_state.json"

ALERT_EVENT_TYPE: str = "watchdog_alert"

# Intake front-matter statuses that mean "nobody has triaged this yet"
# (SLA clock runs against these) and statuses that mean "closed".
_UNTRIAGED_STATUSES: frozenset[str] = frozenset({"new", "filed"})
_CLOSED_STATUSES: frozenset[str] = frozenset(
    {"resolved", "shipped", "declined", "deferred", "closed"})

_DECISION_HEADING_RE = re.compile(r"^## D\d{3,}\b", re.MULTILINE)

_LOCK = threading.RLock()
_SNAPSHOT_CACHE: dict | None = None
_SNAPSHOT_CACHE_AT: float = 0.0


# ---------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------

def _now_epoch(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _result(check_id: str, status: str, detail: str,
            now: float | None = None) -> dict:
    return {
        "id": check_id,
        "status": status,
        "detail": detail,
        "checked_at": _iso(_now_epoch(now)),
    }


def _parse_iso_epoch(raw: object) -> float | None:
    """Parse an ISO-8601 string to a UTC epoch. None on failure."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _age_label(seconds: float) -> str:
    if seconds < 120:
        return f"{seconds:.0f}s"
    if seconds < 7200:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _state_path() -> Path:
    return credentials._config_dir() / STATE_FILENAME


# ---------------------------------------------------------------------
# the seven checks
# ---------------------------------------------------------------------

def check_runtime_heartbeat(live_dir: Path | str | None = None,
                            now: float | None = None) -> dict:
    """squad_live artefact freshness via ``paper_loop.live_status``.

    ``na`` when no live dir is configured or it was never created --
    a platform that has never run the squad runtime is healthy, not
    silent. Warn > 5 min, alarm > 30 min on the freshest of
    ``state.json`` / ``poll_heartbeat.txt``.
    """
    cid = "runtime_heartbeat"
    if live_dir is None:
        return _result(cid, "na", "no live dir configured", now)
    live_dir = Path(live_dir)
    if not live_dir.is_dir():
        return _result(cid, "na",
                       f"live dir not created yet ({live_dir})", now)
    try:
        status = paper_loop.live_status(live_dir)
    except Exception as exc:  # never raise -- degrade loudly
        return _result(cid, "alarm",
                       f"live_status failed: {exc!s:.120}", now)
    ages = [a for a in (status.get("state_age_seconds"),
                        status.get("poll_heartbeat_age_seconds"))
            if isinstance(a, (int, float))]
    kill = status.get("kill")
    if kill:
        return _result(cid, "warn", f"kill file present: {kill}", now)
    if not ages:
        return _result(cid, "na",
                       "no heartbeat artefacts written yet", now)
    freshest = min(ages)
    label = _age_label(freshest)
    if freshest > RUNTIME_ALARM_SECONDS:
        return _result(cid, "alarm",
                       f"runtime silent for {label} (> 30m)", now)
    if freshest > RUNTIME_WARN_SECONDS:
        return _result(cid, "warn",
                       f"runtime quiet for {label} (> 5m)", now)
    return _result(cid, "ok", f"heartbeat {label} old", now)


def check_calendar_feed(cache_path: Path | str | None = None,
                        now: float | None = None) -> dict:
    """News-calendar cache ``fetched_at`` age (shape from
    ``agent/news/calendar.py``). ``na`` when absent; warn > 12 h;
    alarm > 48 h; corrupt cache is an alarm."""
    cid = "calendar_feed"
    path = Path(cache_path) if cache_path is not None \
        else REPO_ROOT / "data" / "news_calendar.json"
    if not path.is_file():
        return _result(cid, "na", f"no news cache at {path.name}", now)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _result(cid, "alarm",
                       f"news cache unreadable: {exc!s:.120}", now)
    fetched_epoch = _parse_iso_epoch(
        payload.get("fetched_at") if isinstance(payload, dict) else None)
    if fetched_epoch is None:
        return _result(cid, "alarm",
                       "news cache has no parseable fetched_at", now)
    age = _now_epoch(now) - fetched_epoch
    label = _age_label(max(0.0, age))
    if age > CALENDAR_ALARM_SECONDS:
        return _result(cid, "alarm",
                       f"news cache {label} old (> 48h)", now)
    if age > CALENDAR_WARN_SECONDS:
        return _result(cid, "warn",
                       f"news cache {label} old (> 12h)", now)
    return _result(cid, "ok", f"news cache {label} old", now)


def check_broker_health(now: float | None = None) -> dict:
    """Reuse ``broker_health.list_health_states()``. ``na`` when no
    aliases are saved; warn when any PROBED alias reports not-alive.
    Never triggers a fresh probe (the /risk poller owns that)."""
    cid = "broker_health"
    try:
        states = broker_health.list_health_states()
    except Exception as exc:
        return _result(cid, "alarm",
                       f"broker health probe failed: {exc!s:.120}", now)
    if not states:
        return _result(cid, "na", "no broker aliases saved", now)
    dead = [s for s in states
            if not s.get("alive") and s.get("checked_at")]
    unprobed = [s for s in states
                if not s.get("alive") and not s.get("checked_at")]
    if dead:
        names = ", ".join(
            f"{s.get('alias')}: {s.get('reason')}" for s in dead)
        return _result(cid, "warn", f"broker down -- {names}", now)
    if unprobed and len(unprobed) == len(states):
        return _result(cid, "ok",
                       f"{len(states)} alias(es) saved, none probed yet",
                       now)
    return _result(cid, "ok",
                   f"{len(states)} alias(es) healthy", now)


def check_risk_state(state_path: Path | str | None = None,
                     now: float | None = None) -> dict:
    """``risk_state.jsonl`` integrity: parseable JSON per line, no
    future-dated rows. Absent file (clean install) is ``na``;
    corruption is an alarm -- a broken risk ledger silently disables
    the F012 cap arithmetic."""
    cid = "risk_state"
    path = Path(state_path) if state_path is not None \
        else credentials._config_dir() / "risk_state.jsonl"
    if not path.is_file():
        return _result(cid, "na", "no risk_state.jsonl yet", now)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _result(cid, "alarm",
                       f"risk_state.jsonl unreadable: {exc!s:.120}", now)
    horizon = _now_epoch(now) + FUTURE_SKEW_TOLERANCE_SECONDS
    rows = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            return _result(cid, "alarm",
                           f"corrupt JSON at line {line_no}", now)
        if not isinstance(row, dict):
            return _result(cid, "alarm",
                           f"non-object row at line {line_no}", now)
        ts = _parse_iso_epoch(row.get("ts"))
        if ts is not None and ts > horizon:
            return _result(cid, "alarm",
                           f"future-dated row at line {line_no} "
                           f"({row.get('ts')})", now)
        rows += 1
    return _result(cid, "ok", f"{rows} fill row(s), all parseable", now)


def _parse_front_matter(text: str) -> dict:
    """YAML front-matter reader (F024, I011): the block between the
    leading ``---`` fences fed to ``yaml.safe_load``, so list-bearing
    and nested front matter (``linked_features``, ``history``) parses
    correctly. Never raises: missing fence, malformed YAML, or
    non-mapping front matter degrade to ``{}`` (the item is skipped,
    same as pre-F024). Date/datetime scalars are normalised back to
    ISO strings so ``_parse_iso_epoch`` behaviour is unchanged."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    try:
        data = yaml.safe_load("\n".join(body))
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): (v.isoformat() if isinstance(v, (datetime, date))
                     else str(v) if isinstance(v, (int, float, bool))
                     else v)
            for k, v in data.items()}


def check_intake_sla(intake_dir: Path | str | None = None,
                     now: float | None = None) -> dict:
    """Company-loop check: walk ``company/rd/intake/I*.md`` front
    matter. P0 still un-triaged after 4 h -> alarm; P1 un-triaged
    after 7 d -> warn; ANY open item older than 30 d -> warn."""
    cid = "intake_sla"
    directory = Path(intake_dir) if intake_dir is not None \
        else REPO_ROOT / "company" / "rd" / "intake"
    if not directory.is_dir():
        return _result(cid, "na", "no intake dir", now)
    now_e = _now_epoch(now)
    alarms: list[str] = []
    warns: list[str] = []
    seen = 0
    for path in sorted(directory.glob("I*.md")):
        try:
            fm = _parse_front_matter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        item_id = fm.get("id") or path.stem.split("-")[0]
        status = (fm.get("status") or "").lower()
        priority = (fm.get("priority") or "").upper()
        submitted = _parse_iso_epoch(fm.get("submitted_at"))
        if not status or submitted is None:
            continue
        seen += 1
        age = now_e - submitted
        if status in _UNTRIAGED_STATUSES:
            if priority == "P0" and age > INTAKE_P0_ALARM_SECONDS:
                alarms.append(f"{item_id} P0 untriaged {_age_label(age)}")
            elif priority == "P1" and age > INTAKE_P1_WARN_SECONDS:
                warns.append(f"{item_id} P1 untriaged {_age_label(age)}")
        if status not in _CLOSED_STATUSES and age > INTAKE_OPEN_WARN_SECONDS:
            warns.append(f"{item_id} open {_age_label(age)} (> 30d)")
    if alarms:
        return _result(cid, "alarm", "; ".join(alarms), now)
    if warns:
        return _result(cid, "warn", "; ".join(warns), now)
    return _result(cid, "ok",
                   f"{seen} intake item(s) inside SLA", now)


def check_sprint_pulse(ledger_json_path: Path | str | None = None,
                       now: float | None = None) -> dict:
    """Any sprint marked ``in_progress`` in company_state.json with no
    ledger decision in 7 days -> warn (a sprint that stops deciding
    has stalled). No in-progress sprint -> na."""
    cid = "sprint_pulse"
    path = Path(ledger_json_path) if ledger_json_path is not None \
        else REPO_ROOT / "company" / "ledger" / "company_state.json"
    if not path.is_file():
        return _result(cid, "na", "no company ledger", now)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _result(cid, "na", "company ledger unreadable "
                                  "(see ledger_drift)", now)
    if not isinstance(payload, dict):
        return _result(cid, "na", "company ledger malformed", now)
    in_progress = [s for s in (payload.get("sprints") or [])
                   if isinstance(s, dict)
                   and str(s.get("verdict") or "").lower() == "in_progress"]
    if not in_progress:
        return _result(cid, "na", "no in-progress sprint", now)
    newest_decision: float | None = None
    for d in (payload.get("decisions") or []):
        if not isinstance(d, dict):
            continue
        ts = _parse_iso_epoch(str(d.get("date") or "") + "T23:59:59+00:00")
        if ts is not None and (newest_decision is None
                               or ts > newest_decision):
            newest_decision = ts
    names = ", ".join(str(s.get("id")) for s in in_progress)
    if newest_decision is None:
        return _result(cid, "warn",
                       f"{names} in progress but ledger has no dated "
                       "decisions", now)
    quiet = _now_epoch(now) - newest_decision
    if quiet > SPRINT_QUIET_WARN_SECONDS:
        return _result(cid, "warn",
                       f"{names}: no ledger decision for "
                       f"{_age_label(quiet)} (> 7d)", now)
    return _result(cid, "ok",
                   f"{names}: last decision {_age_label(max(0.0, quiet))} "
                   "ago", now)


def check_ledger_drift(ledger_json_path: Path | str | None = None,
                       ledger_md_path: Path | str | None = None,
                       now: float | None = None) -> dict:
    """Decision-count parity between company_state.json and
    decisions_log.md. A mismatch is an ALARM -- this is the drift bug
    that actually happened at Sprint 2 close (D076-D080 history)."""
    cid = "ledger_drift"
    json_path = Path(ledger_json_path) if ledger_json_path is not None \
        else REPO_ROOT / "company" / "ledger" / "company_state.json"
    md_path = Path(ledger_md_path) if ledger_md_path is not None \
        else REPO_ROOT / "company" / "ledger" / "decisions_log.md"
    if not json_path.is_file() and not md_path.is_file():
        return _result(cid, "na", "no ledger files", now)
    if not json_path.is_file() or not md_path.is_file():
        return _result(cid, "alarm",
                       "one ledger file missing (json="
                       f"{json_path.is_file()}, md={md_path.is_file()})",
                       now)
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        json_count = len(payload.get("decisions") or []) \
            if isinstance(payload, dict) else -1
    except (OSError, json.JSONDecodeError) as exc:
        return _result(cid, "alarm",
                       f"company_state.json unreadable: {exc!s:.120}", now)
    try:
        md_text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        return _result(cid, "alarm",
                       f"decisions_log.md unreadable: {exc!s:.120}", now)
    md_count = len(_DECISION_HEADING_RE.findall(md_text))
    if json_count != md_count:
        return _result(cid, "alarm",
                       f"decision counts diverged: JSON={json_count} "
                       f"MD={md_count}", now)
    return _result(cid, "ok",
                   f"{json_count} decisions, JSON == MD", now)


# ---------------------------------------------------------------------
# registry runners
# ---------------------------------------------------------------------

def run_check(check_id: str, *,
              live_dir: Path | str | None = None,
              calendar_cache_path: Path | str | None = None,
              risk_state_path: Path | str | None = None,
              intake_dir: Path | str | None = None,
              ledger_json_path: Path | str | None = None,
              ledger_md_path: Path | str | None = None,
              now: float | None = None) -> dict:
    """Run one named check. Unknown id raises ValueError (the one
    deliberate raise in the module -- caller bug, not system state)."""
    if check_id == "runtime_heartbeat":
        return check_runtime_heartbeat(live_dir, now)
    if check_id == "calendar_feed":
        return check_calendar_feed(calendar_cache_path, now)
    if check_id == "broker_health":
        return check_broker_health(now)
    if check_id == "risk_state":
        return check_risk_state(risk_state_path, now)
    if check_id == "intake_sla":
        return check_intake_sla(intake_dir, now)
    if check_id == "sprint_pulse":
        return check_sprint_pulse(ledger_json_path, now)
    if check_id == "ledger_drift":
        return check_ledger_drift(ledger_json_path, ledger_md_path, now)
    raise ValueError(f"unknown check id {check_id!r}; "
                     f"expected one of {CHECK_IDS}")


def run_checks(**kwargs) -> list[dict]:
    """Run the full registry in :data:`CHECK_IDS` order. Keyword
    arguments are the same injectable paths as :func:`run_check`."""
    return [run_check(cid, **kwargs) for cid in CHECK_IDS]


def overall_status(results: list[dict]) -> str:
    """Worst status across the registry (na counts as ok)."""
    ranking = {"ok": 0, "na": 0, "warn": 1, "alarm": 2}
    worst = "ok"
    worst_rank = 0
    for r in results:
        rank = ranking.get(str(r.get("status")), 2)
        if rank > worst_rank:
            worst_rank = rank
            worst = "warn" if rank == 1 else "alarm"
    return worst


# ---------------------------------------------------------------------
# state-transition-only alert publishing
# ---------------------------------------------------------------------

def _load_last_states(state_path: Path | None = None) -> dict:
    path = state_path if state_path is not None else _state_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    states = payload.get("states")
    return dict(states) if isinstance(states, dict) else {}


def _save_last_states(states: dict, state_path: Path | None = None) -> bool:
    path = state_path if state_path is not None else _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(
            {"states": states, "saved_at": _iso(time.time())},
            sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


def publish_transitions(results: list[dict],
                        state_path: Path | None = None,
                        publisher=None) -> list[dict]:
    """Publish a ``watchdog_alert`` bus event for every check whose
    status CHANGED into warn/alarm, or recovered out of warn/alarm
    back to ok/na. Steady state publishes nothing (the whole point:
    an alert stream you can trust not to nag).

    ``publisher`` defaults to :func:`agent.platform.alerts.publish`;
    tests inject a recorder. Returns the list of published payloads.
    """
    if publisher is None:
        from agent.platform import alerts as _alerts
        publisher = lambda payload: _alerts.publish(  # noqa: E731
            ALERT_EVENT_TYPE, payload)
    with _LOCK:
        last = _load_last_states(state_path)
        published: list[dict] = []
        for r in results:
            cid = str(r.get("id"))
            new = str(r.get("status"))
            old = last.get(cid)
            degraded = new in ("warn", "alarm") and old != new
            recovered = (new in ("ok", "na")
                         and old in ("warn", "alarm"))
            if degraded or recovered:
                payload = {
                    "check": cid,
                    "status": new,
                    "previous": old,
                    "detail": str(r.get("detail", "")),
                    "recovered": recovered,
                }
                try:
                    publisher(payload)
                    published.append(payload)
                except Exception:
                    # A broken bus must not break the watchdog.
                    pass
            last[cid] = new
        _save_last_states(last, state_path)
    return published


# ---------------------------------------------------------------------
# cached snapshot (the /api/watchdog/status payload)
# ---------------------------------------------------------------------

def snapshot(*, cache_seconds: float = SNAPSHOT_CACHE_SECONDS,
             force: bool = False,
             publish: bool = True,
             state_path: Path | None = None,
             publisher=None,
             **check_kwargs) -> dict:
    """Full registry snapshot with a small in-process cache (default
    30 s) so the /hq strip can poll freely. When ``publish`` is True
    (default), state transitions found by a NON-cached run also land
    on the alerts bus -- state-change-only, so polling stays quiet.
    """
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    mono = time.monotonic()
    with _LOCK:
        if (not force and _SNAPSHOT_CACHE is not None
                and (mono - _SNAPSHOT_CACHE_AT) <= cache_seconds):
            out = dict(_SNAPSHOT_CACHE)
            out["cached"] = True
            return out
    results = run_checks(**check_kwargs)
    if publish:
        publish_transitions(results, state_path=state_path,
                            publisher=publisher)
    payload = {
        "checks": results,
        "overall": overall_status(results),
        "generated_at": _iso(time.time()),
        "cached": False,
    }
    with _LOCK:
        _SNAPSHOT_CACHE = dict(payload)
        _SNAPSHOT_CACHE_AT = mono
    return payload


def reset_cache_for_tests() -> None:  # claim-exempt: test-only cache reset, no HTTP surface
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    with _LOCK:
        _SNAPSHOT_CACHE = None
        _SNAPSHOT_CACHE_AT = 0.0


__all__ = [
    "CHECK_IDS",
    "STATUSES",
    "ALERT_EVENT_TYPE",
    "RUNTIME_WARN_SECONDS",
    "RUNTIME_ALARM_SECONDS",
    "CALENDAR_WARN_SECONDS",
    "CALENDAR_ALARM_SECONDS",
    "INTAKE_P0_ALARM_SECONDS",
    "INTAKE_P1_WARN_SECONDS",
    "INTAKE_OPEN_WARN_SECONDS",
    "SPRINT_QUIET_WARN_SECONDS",
    "SNAPSHOT_CACHE_SECONDS",
    "STATE_FILENAME",
    "check_runtime_heartbeat",
    "check_calendar_feed",
    "check_broker_health",
    "check_risk_state",
    "check_intake_sla",
    "check_sprint_pulse",
    "check_ledger_drift",
    "run_check",
    "run_checks",
    "overall_status",
    "publish_transitions",
    "snapshot",
    "reset_cache_for_tests",
]
