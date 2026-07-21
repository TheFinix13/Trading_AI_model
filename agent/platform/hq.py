"""Blue Lock Trading Co. — HQ dashboard data source.

Reads `company/ledger/company_state.json` (the machine-readable state
of the "company of agents" — see `company/README.md` for the charter
and `company/protocols/` for the review chain, persona handoff, and
escalation protocol) and exposes it as a Python dict for the /hq
route and the /api/hq/state endpoint.

This module is deliberately read-only. The ledger is written by the
personas themselves (CPO owns sprint scoping, CTO owns architecture
review entries, etc.) — the HTTP layer never mutates it. If the file
is missing, unreadable, or malformed, `hq_state()` returns a
skeleton payload with `meta.unconfigured=True` so the dashboard can
render a friendly "not configured" state instead of a 500.

Repo layout the dashboard depends on::

    company/
      README.md                         # charter
      roles/<role>.md                   # 17 role docs
      protocols/{review-chain, persona-handoff, escalation}.md
      ledger/
        company_state.json              # <-- THIS module reads this
        decisions_log.md
      sprints/sprint-0-trust-foundation/
        README.md
        F00[1-5]-*.md
        BACKLOG.md
      handoffs/<F###>-<from>-to-<to>.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LEDGER_PATH = REPO_ROOT / "company" / "ledger" / "company_state.json"

_SKELETON_META = {
    "company_name": "Blue Lock Trading Co.",
    "founded": None,
    "mission": ("The first AI trading platform that trades like a "
                "football team."),
    "one_liner": ("Watch our striker squad find setups on real "
                  "markets \u2014 every decision explained, every "
                  "risk gated."),
    "current_sprint_id": None,
    "generated_at": None,
    "schema_version": "1.0.0",
    "unconfigured": True,
    "unconfigured_reason": None,
}


def _empty_kpis() -> dict:
    return {
        "features_shipped_sprint_0": 0,
        "features_total_sprint_0": 0,
        "backlog_size": 0,
        "bugs_open": 0,
        "cycle_time_days_p50": None,
        "test_coverage_pct": None,
        "active_roles": 0,
        "total_roles": 0,
    }


def _skeleton(reason: str, generated_at: str) -> dict:
    """Payload for the "no ledger on disk" / "malformed" cases.

    Same shape as a real payload so the frontend renders empty
    sections instead of crashing on missing keys.
    """
    meta = dict(_SKELETON_META)
    meta["generated_at"] = generated_at
    meta["unconfigured_reason"] = reason
    return {
        "meta": meta,
        "roles": [],
        "sprints": [],
        "features": [],
        "decisions": [],
        "kpis": _empty_kpis(),
        "blockers": [],
    }


def _now_iso() -> str:
    """UTC ISO8601 with second precision; suffix Z per the ledger convention."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _iso_days_ago(iso_str: str, now: datetime | None = None) -> int | None:
    """Return whole-day delta between ``iso_str`` and ``now`` (UTC).

    Returns ``None`` on unparseable input rather than raising — callers
    treat missing history entries gracefully.
    """
    if not iso_str:
        return None
    try:
        if iso_str.endswith("Z"):
            iso_str = iso_str[:-1] + "+00:00"
        ts = datetime.fromisoformat(iso_str)
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(0, (now - ts).days)


def _derive_feature_ages(features: list[dict],
                         now: datetime | None = None) -> None:
    """Populate ``age_in_stage_days`` in place from the latest ``history[]``
    entry whose ``stage`` matches ``current_stage``.

    Leaves an explicit stored ``age_in_stage_days`` alone if it exists in
    the source — the ledger's persona-written value is authoritative.
    Only fills the field when it's missing / null AND the history has a
    dated entry we can use.
    """
    for f in features:
        if f.get("age_in_stage_days") is not None:
            continue
        stage = f.get("current_stage")
        history = f.get("history") or []
        entered_at = None
        for entry in reversed(history):
            if entry.get("stage") == stage:
                entered_at = entry.get("at")
                break
        if entered_at is None and history:
            entered_at = history[-1].get("at")
        if entered_at:
            f["age_in_stage_days"] = _iso_days_ago(entered_at, now=now) or 0
        else:
            f["age_in_stage_days"] = 0


def _derive_blockers(features: list[dict]) -> list[dict]:
    """Flatten every feature's ``blockers[]`` into a top-level list with
    the feature id + title annotated, so the /hq blockers panel can
    render them without cross-referencing.

    Only surfaces blockers with ``awaiting_ceo: true`` — internal
    blockers (waiting on another role) show up on the feature card,
    not the CEO-attention panel.
    """
    out: list[dict] = []
    for f in features:
        for b in (f.get("blockers") or []):
            if not b.get("awaiting_ceo"):
                continue
            out.append({
                "feature_id": f.get("id"),
                "feature_title": f.get("title"),
                "raised_by": b.get("raised_by"),
                "raised_at": b.get("raised_at"),
                "summary": b.get("summary"),
                "options": b.get("options") or [],
                "recommendation": b.get("recommendation"),
            })
    return out


def hq_state(ledger_path: Path | None = None) -> dict:
    """Return the HQ dashboard state as a JSON-ready dict.

    ``ledger_path`` defaults to
    ``<repo_root>/company/ledger/company_state.json``. Passing an
    explicit path is used by the tests and by any future multi-tenant
    deployment where /hq points at a per-user ledger.

    Missing / malformed files return a well-shaped skeleton with
    ``meta.unconfigured=True`` and ``meta.unconfigured_reason`` set —
    the frontend can render a "company not yet configured on this
    server" state instead of a 500.
    """
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    generated_at = _now_iso()

    if not path.is_file():
        return _skeleton(
            f"ledger file not found at {path}", generated_at)

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return _skeleton(
            f"ledger unreadable: {exc.__class__.__name__}", generated_at)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _skeleton(
            f"ledger malformed JSON at line {exc.lineno}", generated_at)

    if not isinstance(payload, dict):
        return _skeleton(
            "ledger top-level is not a JSON object", generated_at)

    meta = dict(_SKELETON_META)
    meta.update(payload.get("meta") or {})
    meta["generated_at"] = generated_at
    meta["unconfigured"] = False
    meta["unconfigured_reason"] = None

    roles = list(payload.get("roles") or [])
    sprints = list(payload.get("sprints") or [])
    features = [dict(f) for f in (payload.get("features") or [])]
    decisions = list(payload.get("decisions") or [])
    kpis = dict(_empty_kpis())
    kpis.update(payload.get("kpis") or {})

    _derive_feature_ages(features)
    ceo_blockers = _derive_blockers(features)

    kpis["active_roles"] = kpis.get("active_roles") or sum(
        1 for r in roles if r.get("active"))
    kpis["total_roles"] = kpis.get("total_roles") or len(roles)
    if not kpis.get("backlog_size"):
        kpis["backlog_size"] = sum(
            1 for f in features
            if f.get("current_stage") not in ("ship", "shipped", "done"))

    return {
        "meta": meta,
        "roles": roles,
        "sprints": sprints,
        "features": features,
        "decisions": decisions[-10:] if len(decisions) > 10 else decisions,
        "decisions_total": len(decisions),
        "kpis": kpis,
        "blockers": ceo_blockers,
    }
