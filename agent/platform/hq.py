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
DEFAULT_HANDOFFS_DIR = REPO_ROOT / "company" / "handoffs"

# ---------------------------------------------------------------------
# F015 -- Org & Flow (org_state)
# ---------------------------------------------------------------------

# Tier display order + labels for the org chart. `executive-adjacent`
# (currently only research_lead) renders as the "R&D" group per the
# CEO's 2026-07-23 org-web request. Unknown tiers append after these
# so a future ledger tier never silently disappears.
_ORG_TIER_ORDER = ("executive", "design", "engineering", "business",
                   "executive-adjacent")
_ORG_TIER_LABELS = {
    "executive": "Executive",
    "design": "Design",
    "engineering": "Engineering",
    "business": "Business",
    "executive-adjacent": "R&D",
}

# Default report line per tier, used when a role row carries no
# explicit `reports_to` array. Source: company/roles/*.md review-chain
# sections -- CEO sits at the top; CTO + CPO report to CEO; design
# roles hand work up through CPO; engineering through CTO; business
# roles answer to the CEO. Explicit ledger `reports_to` (research_lead
# dual-reports CTO + CPO; user_advocate reports to CPO) always wins.
_ORG_DEFAULT_REPORTS_TO = {
    "executive": ["ceo"],
    "design": ["cpo"],
    "engineering": ["cto"],
    "business": ["ceo"],
    "executive-adjacent": ["cto", "cpo"],
}

# The review-chain pipeline, verbatim from
# company/protocols/review-chain.md §Stages (stages 1-10 incl. the 7b
# research-conditional stage added by D086). `conditional` stages fire
# only when their criterion is met; the org view renders them with a
# `*` marker.
_REVIEW_CHAIN_STAGES = (
    {"stage": "spec", "owner": "cpo", "conditional": False,
     "fires_when": "always"},
    {"stage": "research", "owner": "ux_researcher", "conditional": True,
     "fires_when": "always for P0/P1; skipped on fast path"},
    {"stage": "design", "owner": "ui_designer", "conditional": False,
     "fires_when": "always (+ brand for copy)"},
    {"stage": "architecture", "owner": "cto", "conditional": True,
     "fires_when": "always for P0/P1; skipped on fast path"},
    {"stage": "build", "owner": "frontend / backend / ai_ml",
     "conditional": False, "fires_when": "always"},
    {"stage": "qa", "owner": "qa", "conditional": False,
     "fires_when": "always"},
    {"stage": "security", "owner": "security", "conditional": True,
     "fires_when": "CTO architecture flag security_relevant: true"},
    {"stage": "research (7b)", "owner": "research_lead",
     "conditional": True,
     "fires_when": "CTO architecture flag research_relevant: true"},
    {"stage": "legal", "owner": "legal", "conditional": True,
     "fires_when": "CTO architecture flag legal_relevant: true"},
    {"stage": "signoff", "owner": "ceo", "conditional": False,
     "fires_when": "always for P0; CPO-delegable for P1/P2"},
    {"stage": "ship", "owner": "devops", "conditional": False,
     "fires_when": "always"},
)

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
        "intake_items_open": 0,
        "experiments_in_flight": 0,
        "published_findings_last_30d": 0,
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
        "intake": [],
        "experiments": [],
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
    intake = list(payload.get("intake") or [])
    experiments = list(payload.get("experiments") or [])
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

    kpis["intake_items_open"] = _count_open_intake(intake, kpis)
    kpis["experiments_in_flight"] = _count_experiments_in_flight(
        experiments, kpis)
    kpis["published_findings_last_30d"] = _count_published_findings_30d(
        experiments, kpis)

    return {
        "meta": meta,
        "roles": roles,
        "sprints": sprints,
        "features": features,
        "decisions": decisions[-10:] if len(decisions) > 10 else decisions,
        "decisions_total": len(decisions),
        "kpis": kpis,
        "blockers": ceo_blockers,
        "intake": intake,
        "experiments": experiments,
    }


def _count_open_intake(intake: list[dict], kpis: dict) -> int:
    """R&D pulse: count intake items that haven't reached ``closed``.

    Preferred pattern (same as ``active_roles`` / ``total_roles``):
    trust the ledger's recorded value if the persona owning the intake
    queue already computed it; otherwise derive at render time so a
    stale ledger doesn't lie to the dashboard.
    """
    recorded = kpis.get("intake_items_open")
    if recorded not in (None, 0):
        return int(recorded)
    return sum(1 for i in intake
               if str(i.get("status") or "").lower() != "closed")


def _count_experiments_in_flight(experiments: list[dict],
                                 kpis: dict) -> int:
    """R&D pulse: experiments whose status is not closed/shipped/done.

    ``closed-negative`` also counts as "not in flight" -- the campaign
    landed, even if the answer was unwelcome.
    """
    recorded = kpis.get("experiments_in_flight")
    if recorded not in (None, 0):
        return int(recorded)
    terminal_prefixes = ("closed", "shipped", "done")
    in_flight = 0
    for e in experiments:
        status = str(e.get("status") or "").lower()
        if not status:
            continue
        if any(status == p or status.startswith(p + "-")
               for p in terminal_prefixes):
            continue
        in_flight += 1
    return in_flight


def _count_published_findings_30d(experiments: list[dict],
                                  kpis: dict) -> int:
    """R&D pulse: condensed findings that have shipped in the last 30d.

    The ledger's ``condensed_finding_status: "published"`` on an
    experiment is the flag; ``condensed_finding_published_at`` (ISO
    date) gates the 30-day window when present. If the ledger has
    already recorded ``kpis.published_findings_last_30d`` explicitly
    that takes precedence.
    """
    recorded = kpis.get("published_findings_last_30d")
    if recorded not in (None, 0):
        return int(recorded)
    now = datetime.now(timezone.utc)
    count = 0
    for e in experiments:
        if str(e.get("condensed_finding_status") or "") != "published":
            continue
        published_at = e.get("condensed_finding_published_at")
        if not published_at:
            count += 1
            continue
        days = _iso_days_ago(published_at, now=now)
        if days is not None and days <= 30:
            count += 1
    return count


# ---------------------------------------------------------------------
# F015 -- Org & Flow data plane
# ---------------------------------------------------------------------

def _load_ledger_roles(path: Path) -> tuple[list[dict], str | None]:
    """Read the ledger and return ``(roles, error_reason)``.

    Mirrors :func:`hq_state`'s degradation contract: any failure
    returns an empty role list plus a human-readable reason instead of
    raising, so /api/hq/org can render a friendly banner.
    """
    if not path.is_file():
        return [], f"ledger file not found at {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"ledger unreadable: {exc.__class__.__name__}"
    if not isinstance(payload, dict):
        return [], "ledger top-level is not a JSON object"
    return list(payload.get("roles") or []), None


def _resolve_reports_to(role: dict) -> list[str]:
    """Explicit ledger ``reports_to`` wins; else the tier default.

    The CEO is the root of the chart and reports to nobody.
    """
    if role.get("id") == "ceo":
        return []
    explicit = role.get("reports_to")
    if isinstance(explicit, list) and explicit:
        return [str(r) for r in explicit]
    tier = str(role.get("tier") or "business")
    return list(_ORG_DEFAULT_REPORTS_TO.get(tier, ["ceo"]))


def _group_roles_by_tier(roles: list[dict]) -> list[dict]:
    """Return the tier groups in display order, each with its roles.

    Unknown tiers append after the canonical five so a future ledger
    tier still renders (labelled by its raw id).
    """
    by_tier: dict[str, list[dict]] = {}
    for r in roles:
        tier = str(r.get("tier") or "business")
        by_tier.setdefault(tier, []).append({
            "id": r.get("id"),
            "title": r.get("title") or r.get("id"),
            "tier": tier,
            "persona_name": r.get("persona_name"),
            "active": bool(r.get("active")),
            "current_task": r.get("current_task"),
            "reports_to": _resolve_reports_to(r),
        })
    ordered = [t for t in _ORG_TIER_ORDER if t in by_tier]
    ordered += [t for t in by_tier if t not in _ORG_TIER_ORDER]
    return [{
        "id": tier,
        "label": _ORG_TIER_LABELS.get(tier, tier),
        "roles": by_tier[tier],
    } for tier in ordered]


def _handoff_sort_key(h: dict) -> str:
    return str(h.get("timestamp") or "")


def _load_recent_handoffs(handoffs_dir: Path,
                          limit: int) -> tuple[list[dict], int]:
    """Parse ``company/handoffs/*.json`` and return the most recent
    ``limit`` entries (newest-first by ``timestamp``) plus the total
    count of parseable handoffs. Malformed / non-dict files are
    skipped silently -- a broken handoff artefact must never take the
    org view down.
    """
    if not handoffs_dir.is_dir():
        return [], 0
    parsed: list[dict] = []
    for path in sorted(handoffs_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        parsed.append({
            "from_role": raw.get("from_role"),
            "to_role": raw.get("to_role"),
            "feature_id": raw.get("feature_id"),
            "timestamp": raw.get("timestamp"),
            "scope": raw.get("scope"),
            "verdict": raw.get("verdict"),
            "file": path.name,
        })
    parsed.sort(key=_handoff_sort_key, reverse=True)
    return parsed[:limit], len(parsed)


def org_state(ledger_path: Path | None = None,
              handoffs_dir: Path | None = None,
              handoff_limit: int = 8) -> dict:
    """Return the Org & Flow payload for ``/api/hq/org``.

    Three blocks, per the CEO's 2026-07-23 org-web request:

    * ``tiers`` -- the 19 roles from the ledger grouped by tier
      (Executive / Design / Engineering / Business / R&D), each role
      carrying ``active``, ``persona_name`` and its resolved
      ``reports_to`` line (ledger ``reports_to`` wins; tier default
      otherwise; CEO reports to nobody).
    * ``review_chain`` -- the 11-stage pipeline verbatim from
      ``company/protocols/review-chain.md`` (conditional stages
      flagged so the UI can star them).
    * ``handoffs`` -- the most recent ``handoff_limit`` artefacts from
      ``company/handoffs/*.json``, newest-first, plus
      ``handoffs_total``.

    Missing / malformed ledger degrades to ``unconfigured: True`` with
    empty ``tiers`` -- the static ``review_chain`` still renders so
    the page is never blank.
    """
    the_ledger = Path(ledger_path) if ledger_path is not None \
        else DEFAULT_LEDGER_PATH
    the_handoffs = Path(handoffs_dir) if handoffs_dir is not None \
        else DEFAULT_HANDOFFS_DIR
    roles, reason = _load_ledger_roles(the_ledger)
    handoffs, handoffs_total = _load_recent_handoffs(
        the_handoffs, handoff_limit)
    return {
        "generated_at": _now_iso(),
        "unconfigured": reason is not None,
        "unconfigured_reason": reason,
        "tiers": _group_roles_by_tier(roles),
        "roles_total": len(roles),
        "review_chain": [dict(s) for s in _REVIEW_CHAIN_STAGES],
        "handoffs": handoffs,
        "handoffs_total": handoffs_total,
    }
