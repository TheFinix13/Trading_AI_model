"""F013 -- Trade approval queue + live-mode toggle.

The FOURTH gate of the four-check live-order pathway:

    live_mode_enabled()                           # (1) F013
    kill_switches.is_killed(entry.symbol)         # (2) F011
    risk_budget.can_send_order(...)               # (3) F012
    approval_queue.can_send_order(approval_id)    # (4) F013  <- this file

Sprint 2 ships this MODULE and its UI/API surface only. No live-order
pathway in this sprint calls `submit(...)` from an integration surface
(D065 invariant); the squad wiring is future-sprint work.

Storage:
- In-memory `_ENTRIES` dict for O(1) lookup on approve/reject/can_send.
- Append-only JSONL audit trail at `<config_dir>/approvals.jsonl`.
- Live-mode toggle persisted in keyring under
  `namespace="bluelock", key="live_mode_enabled"`. Default missing ==
  disabled. Belt-and-braces: even if keyring is unavailable, the
  module defaults to OFF.

The audit file survives process restarts; the in-memory state does not.
That is deliberate: an unbounded queue after a crash would be worse
than "operator inspects the JSONL and re-issues if needed".
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from agent.platform import credentials

DEFAULT_TIMEOUT_SECONDS: int = 5 * 60  # 5 minutes
STATUSES: tuple[str, ...] = ("pending", "approved", "rejected", "timed_out")
AUDIT_FILENAME: str = "approvals.jsonl"

LIVE_MODE_NAMESPACE: str = "bluelock"
LIVE_MODE_KEY: str = "live_mode_enabled"

# Fields required on every submitted entry. `id`, `timestamp`,
# `timeout_at`, and `status` are added by `submit` itself and MUST NOT
# be supplied by the caller.
_REQUIRED_ENTRY_FIELDS: tuple[str, ...] = (
    "symbol", "side", "size", "entry", "stop", "take_profit",
    "rationale", "source_agent", "risk_snapshot",
)

_ALLOWED_SIDES: frozenset[str] = frozenset({"buy", "sell"})

_ENTRIES: dict[str, dict] = {}
_LOCK = threading.RLock()
_TIMEOUT_SECONDS: int = DEFAULT_TIMEOUT_SECONDS


def _audit_path() -> Path:
    return credentials._config_dir() / AUDIT_FILENAME


def _now() -> float:
    return time.time()


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _append_audit(entry: dict) -> None:
    path = _audit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass


def _validate_entry_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("entry payload must be a dict")
    missing = [k for k in _REQUIRED_ENTRY_FIELDS if k not in payload]
    if missing:
        raise ValueError(f"missing required fields: {missing}")
    if payload["side"] not in _ALLOWED_SIDES:
        raise ValueError(f"side must be one of {sorted(_ALLOWED_SIDES)}")
    for numeric in ("size", "entry", "stop", "take_profit"):
        val = payload[numeric]
        if not isinstance(val, (int, float)):
            raise ValueError(f"{numeric} must be numeric")
        if val <= 0:
            raise ValueError(f"{numeric} must be > 0")
    rs = payload["risk_snapshot"]
    if not isinstance(rs, dict) or "worst_case_loss" not in rs:
        raise ValueError("risk_snapshot must be a dict with worst_case_loss")


def submit(entry: dict) -> str:
    """Enqueue a proposal. Returns the assigned approval_id."""
    _validate_entry_payload(entry)
    now = _now()
    approval_id = "apr_" + uuid.uuid4().hex[:16]
    record = {
        "id": approval_id,
        "timestamp": _iso(now),
        "submitted_at": now,
        "symbol": str(entry["symbol"]),
        "side": str(entry["side"]),
        "size": float(entry["size"]),
        "entry": float(entry["entry"]),
        "stop": float(entry["stop"]),
        "take_profit": float(entry["take_profit"]),
        "rationale": str(entry["rationale"]),
        "source_agent": str(entry["source_agent"]),
        "risk_snapshot": dict(entry["risk_snapshot"]),
        "timeout_at": _iso(now + _TIMEOUT_SECONDS),
        "timeout_at_epoch": now + _TIMEOUT_SECONDS,
        "status": "pending",
        "resolved_at": None,
        "resolved_by": None,
        "resolution_reason": None,
    }
    with _LOCK:
        _ENTRIES[approval_id] = record
    _append_audit({"event": "submit", **record})
    return approval_id


def _resolve(approval_id: str, new_status: str, by: str,
             reason: str | None) -> bool:
    now = _now()
    with _LOCK:
        record = _ENTRIES.get(approval_id)
        if record is None:
            return False
        if record["status"] != "pending":
            return False
        record["status"] = new_status
        record["resolved_at"] = _iso(now)
        record["resolved_by"] = by
        record["resolution_reason"] = reason
    _append_audit({"event": new_status, "id": approval_id,
                   "resolved_at": _iso(now), "resolved_by": by,
                   "resolution_reason": reason})
    return True


def approve(approval_id: str, by: str = "user") -> bool:
    return _resolve(approval_id, "approved", by, None)


def reject(approval_id: str, reason: str, by: str = "user") -> bool:
    return _resolve(approval_id, "rejected", by, reason)


def timeout_reap(now: float | None = None) -> list[str]:
    """Mark every stale `pending` entry as `timed_out`. Returns
    the list of ids that were expired in this call."""
    cutoff = now if now is not None else _now()
    expired: list[str] = []
    with _LOCK:
        for approval_id, record in _ENTRIES.items():
            if record["status"] != "pending":
                continue
            if record["timeout_at_epoch"] <= cutoff:
                record["status"] = "timed_out"
                record["resolved_at"] = _iso(cutoff)
                record["resolved_by"] = "system"
                record["resolution_reason"] = "timeout"
                expired.append(approval_id)
    for approval_id in expired:
        _append_audit({"event": "timed_out", "id": approval_id,
                       "resolved_at": _iso(cutoff),
                       "resolved_by": "system",
                       "resolution_reason": "timeout"})
    return expired


def can_send_order(approval_id: str) -> bool:
    """The fourth live-mode-off gate. True iff the entry exists and its
    status is `approved`. Auto-reaps timeouts before answering."""
    timeout_reap()
    with _LOCK:
        record = _ENTRIES.get(approval_id)
    if record is None:
        return False
    return record["status"] == "approved"


def get_entry(approval_id: str) -> dict | None:
    """Return a shallow copy of the entry (for API surfaces)."""
    timeout_reap()
    with _LOCK:
        record = _ENTRIES.get(approval_id)
        if record is None:
            return None
        return dict(record)


def list_entries(status: str = "all", limit: int = 100) -> list[dict]:
    """Return entries newest-first, optionally filtered by status."""
    timeout_reap()
    with _LOCK:
        rows = list(_ENTRIES.values())
    if status != "all":
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["submitted_at"], reverse=True)
    return [dict(r) for r in rows[:max(0, int(limit))]]


def set_timeout_seconds(seconds: int) -> None:  # claim-exempt: config setter, no HTTP surface
    """Adjust the pending-entry timeout. Test / config-time only."""
    global _TIMEOUT_SECONDS
    _TIMEOUT_SECONDS = max(1, int(seconds))


def get_timeout_seconds() -> int:
    return _TIMEOUT_SECONDS


def reset_state() -> None:  # claim-exempt: test-only
    """Clear the in-memory queue AND drop the JSONL audit file.

    Callers must have set `credentials.set_config_dir(...)` to a
    throwaway directory before invoking this. Real deployments should
    never call it."""
    global _TIMEOUT_SECONDS
    with _LOCK:
        _ENTRIES.clear()
        _TIMEOUT_SECONDS = DEFAULT_TIMEOUT_SECONDS
    audit = _audit_path()
    try:
        if audit.exists():
            audit.unlink()
    except OSError:
        pass


def is_live_mode_enabled() -> bool:
    """The FIRST gate of the four-check live-order pathway.

    Default missing == disabled. Any keyring error also returns False
    (fail-closed)."""
    try:
        val = credentials.retrieve_secret(LIVE_MODE_NAMESPACE, LIVE_MODE_KEY)
    except Exception:
        return False
    if val is None:
        return False
    return str(val).strip().lower() == "true"


def set_live_mode(enabled: bool) -> bool:
    """Persist the toggle state. Returns True on success.

    The caller (the API layer) is responsible for the enable-ceremony
    guard. This function trusts its `enabled` argument."""
    value = "true" if bool(enabled) else "false"
    try:
        ok = credentials.store_secret(
            LIVE_MODE_NAMESPACE, LIVE_MODE_KEY, value)
    except Exception:
        return False
    if ok:
        _append_audit({"event": "live_mode",
                       "enabled": bool(enabled),
                       "at": _iso(_now())})
    return bool(ok)


CONFIRMATION_PHRASE: str = "ENABLE LIVE MODE"


def enable_ceremony(acknowledged: bool, confirmation: str) -> tuple[bool, str]:
    """Gate for `set_live_mode(True)` used by the HTTP API.

    Returns (ok, reason). `ok=True` only when BOTH the acknowledgement
    checkbox is True and the confirmation string matches exactly."""
    if not acknowledged:
        return False, "acknowledgement required"
    if str(confirmation).strip() != CONFIRMATION_PHRASE:
        return False, "confirmation phrase mismatch"
    ok = set_live_mode(True)
    if not ok:
        return False, "keyring write failed"
    return True, "ok"


def disable() -> bool:
    """One-click live-mode OFF -- no ceremony required (safety
    direction always frictionless)."""
    return set_live_mode(False)


def can_send_live_order(entry: dict, *,
                        live_mode_check=None,
                        kill_switch_check=None,
                        risk_budget_check=None,
                        approval_check=None) -> tuple[bool, str]:
    """Compose all four checks. Sprint 2 exports this so the P0
    invariant test can call it directly with dependency-injected
    stubs.

    Every check is a callable that returns (bool, reason). The
    live-mode-off invariant is: `can_send_live_order(...)[0] is False`
    whenever any check returns False.
    """
    from agent.platform import kill_switches as _kill
    from agent.platform import risk_budget as _risk

    def _default_live_mode() -> tuple[bool, str]:
        return (is_live_mode_enabled(), "live-mode disabled")

    def _default_kill(sym: str) -> tuple[bool, str]:
        return (not _kill.is_killed(sym), f"kill-switch on {sym}")

    def _default_risk(sym: str, strat: str, worst: float) -> tuple[bool, str]:
        ok, reason = _risk.can_send_order(sym, strat, worst)
        return (ok, reason)

    def _default_approval(aid: str) -> tuple[bool, str]:
        return (can_send_order(aid), "approval not granted")

    lm = live_mode_check or _default_live_mode
    ks = kill_switch_check or _default_kill
    rb = risk_budget_check or _default_risk
    ap = approval_check or _default_approval

    ok_lm, why_lm = lm()
    if not ok_lm:
        return False, why_lm

    symbol = str(entry.get("symbol", ""))
    ok_ks, why_ks = ks(symbol)
    if not ok_ks:
        return False, why_ks

    strategy = str(entry.get("source_agent", ""))
    worst = float(entry.get("risk_snapshot", {}).get("worst_case_loss", 0.0))
    ok_rb, why_rb = rb(symbol, strategy, worst)
    if not ok_rb:
        return False, why_rb

    aid = str(entry.get("approval_id") or entry.get("id") or "")
    ok_ap, why_ap = ap(aid)
    if not ok_ap:
        return False, why_ap

    return True, "ok"


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "STATUSES",
    "AUDIT_FILENAME",
    "LIVE_MODE_NAMESPACE",
    "LIVE_MODE_KEY",
    "CONFIRMATION_PHRASE",
    "submit",
    "approve",
    "reject",
    "timeout_reap",
    "can_send_order",
    "get_entry",
    "list_entries",
    "set_timeout_seconds",
    "get_timeout_seconds",
    "is_live_mode_enabled",
    "set_live_mode",
    "enable_ceremony",
    "disable",
    "can_send_live_order",
    "reset_state",
]
