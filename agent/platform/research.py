"""F003 -- Public `/research` data plane (CPO-gated).

Reads REPORT.md files from a sibling ``finance-research-experiments``
checkout (never imported as code -- filesystem access only) and
returns only the entries a publication manifest explicitly allows to
appear on the public page. The manifest lives at
``company/research/publication_manifest.json`` and is CPO-owned per
D007 -- backend parses everything on tape but never publishes
without an explicit allow-list row.

Data sources
------------

* ``<research_root>/experiments/E*/REPORT.md`` -- the six-study
  research lane (E001..E024). Each report carries a canonical
  ``**Verdict:**`` or ``**Status:**`` header line.
* ``<research_root>/programs/*/experiments/*/REPORT.md`` -- the
  multi-agent-ensemble campaign lane (Phase AC, AD, ...).

Files named ``REPORT 2.md`` (Obsidian iCloud drift copies visible in
some working trees) are deliberately ignored -- only the canonical
``REPORT.md`` filename counts.

Contract
--------

* :func:`load_manifest` -> parsed ``publication_manifest.json``
  (empty envelope on missing file).
* :func:`parse_report(path)` -> ``{campaign_id, title, date, status,
  verdict_kind, abstract, report_path, source_size}`` from one
  REPORT.md; ``None`` on unreadable / obviously non-report file.
* :func:`list_all(research_root)` -> every parseable REPORT.md in
  the lab tree, in most-recent-first order. Used by CPO's manual
  gate (via ``scripts/`` if we build one; currently the module is
  the only reader).
* :func:`get_state(research_root, manifest_path)` -> the public
  payload for the ``/research`` route: manifest metadata + the
  subset of parsed reports the manifest allows, decorated with the
  manifest's ``brand_summary`` / ``verdict_label`` /
  ``headline_stat`` overrides so the page renders the CPO-approved
  copy rather than the raw REPORT.md content.

Read-only invariant
-------------------

Nothing in the research repo is written to by any function here.
The parser opens files for read, extracts a small header block plus
the abstract paragraph, and returns dicts. The tests assert this by
snapshotting the research_root directory before/after every call.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Default paths.
_DEFAULT_MANIFEST_PATH = REPO_ROOT / "company" / "research" / "publication_manifest.json"

# The canonical REPORT filename. Obsidian's iCloud sync can create
# ``REPORT 2.md`` duplicates in some working trees; we skip those on
# purpose.
_REPORT_FILENAME = "REPORT.md"

# Canonical verdict keywords in the pre-registered lab vocabulary. If
# a REPORT.md header line contains one of these tokens (case-
# insensitive), the parser tags it accordingly. Ordering matters:
# check the more specific tokens first (`stopped_at_stage_1` before
# `stopped`).
_VERDICT_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("combined_alive", "combined_alive"),
    ("stage_1_complete", "stage_1_complete"),
    ("stopped_at_stage_1", "stopped_at_stage_1"),
    ("stopped at stage 1", "stopped_at_stage_1"),
    ("parked_low_yield", "parked_low_yield"),
    ("pass_thin", "pass_thin"),
    ("pass (thin)", "pass_thin"),
    ("pass thin", "pass_thin"),
    ("pass", "pass"),
    ("dead", "dead"),
    ("fail", "fail"),
    ("stopped", "stopped"),
    ("parked", "parked"),
    ("complete", "complete"),
    ("in progress", "in_progress"),
    ("in_progress", "in_progress"),
)

# Header line patterns we recognise in a REPORT.md. `**Verdict:**` /
# `**Status:**` / `**Outcome:**` can appear anywhere in the top block,
# not just at column 0 -- e.g. `**Date:** ... · **Status:** complete`.
_VERDICT_LINE_RE = re.compile(
    r"\*\*(?:Verdict|Status|Outcome)\s*:\*\*\s*"
    r"(?P<val>[^\n]+?)\s*(?:·|\||\.\s|$)",
    re.IGNORECASE | re.MULTILINE,
)
_DATE_LINE_RE = re.compile(
    r"\*\*(?:Date|Date executed|Written|Date completed)\s*:\*\*\s*"
    r"(?P<val>[^*·|\n]+?)\s*(?:·|$|\*\*|\||\r|\n)",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"^#\s+(?P<val>.+?)\s*$", re.MULTILINE)
# Directory names in the lab follow the shape `E### _<slug>` or
# `phase_<slug>` or `M###_<slug>`; we use the full name (as it
# appears on disk) as the campaign_id. The manifest keys must match
# the on-disk directory name exactly.
_CAMPAIGN_ID_ALLOWED_PREFIXES = ("E", "phase_", "M001", "M002", "M003")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------
# Publication manifest
# --------------------------------------------------------------------

def load_manifest(path: Path | str | None = None) -> dict:
    """Return the parsed publication manifest, or an empty envelope
    when the file is missing / unreadable. Never raises.

    The envelope shape (with sensible defaults for missing keys):

    ``{cpo_signoff_by, cpo_signoff_at, entries: {<campaign_id>:
    {publish, verdict_kind, verdict_label, brand_summary,
    headline_stat, report_path}}}``.
    """
    the_path = Path(path) if path is not None else _DEFAULT_MANIFEST_PATH
    if not the_path.is_file():
        return {
            "cpo_signoff_by": None,
            "cpo_signoff_at": None,
            "entries": {},
            "unconfigured": True,
        }
    try:
        raw = json.loads(the_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "cpo_signoff_by": None,
            "cpo_signoff_at": None,
            "entries": {},
            "unconfigured": True,
        }
    entries_raw = raw.get("entries") or []
    entries: dict[str, dict] = {}
    if isinstance(entries_raw, list):
        for item in entries_raw:
            if isinstance(item, dict) and item.get("campaign_id"):
                entries[str(item["campaign_id"])] = item
    elif isinstance(entries_raw, dict):
        for cid, item in entries_raw.items():
            if isinstance(item, dict):
                entries[str(cid)] = item
    return {
        "cpo_signoff_by": raw.get("cpo_signoff_by"),
        "cpo_signoff_at": raw.get("cpo_signoff_at"),
        "entries": entries,
        "unconfigured": False,
    }


# --------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------

def _classify_verdict(text: str) -> str:
    """Fold a free-text verdict blurb to one of the canonical kinds."""
    if not text:
        return "unknown"
    low = text.lower()
    for token, kind in _VERDICT_KEYWORDS:
        if token in low:
            return kind
    return "unknown"


def _extract_abstract(body: str) -> str:
    """Pull the first paragraph under the `## Abstract` heading, or
    the paragraph immediately after the header block if no explicit
    abstract heading exists. Returns "" when nothing looks like prose.
    """
    m = re.search(
        r"^##\s+Abstract\s*$(?P<body>.+?)(?=^##\s+|\Z)",
        body,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if m:
        para_block = m.group("body").strip()
    else:
        # Try the paragraph after the last **Verdict/Status/Written** line.
        parts = re.split(r"\n\s*\n", body, maxsplit=6)
        para_block = ""
        for p in parts:
            stripped = p.strip()
            if (stripped
                    and not stripped.startswith("#")
                    and not stripped.startswith("**")
                    and not stripped.startswith("-")):
                para_block = stripped
                break
    # take the first paragraph only
    first = re.split(r"\n\s*\n", para_block, maxsplit=1)[0]
    return first.strip()


def _campaign_id_from_path(path: Path) -> str | None:
    """Extract a canonical id from the containing directory name.

    Uses the full directory name (e.g. ``E001_concept_ablation``,
    ``phase_ac_pitch_assignment``) so the publication manifest can
    key on precise experiment identity rather than a lossy prefix.
    """
    parent = path.parent.name
    if not parent:
        return None
    for prefix in _CAMPAIGN_ID_ALLOWED_PREFIXES:
        if parent.startswith(prefix):
            return parent
    return parent


def parse_report(path: Path | str) -> dict | None:
    """Parse one REPORT.md into a shallow dict.

    Returns ``None`` on unreadable file or a file so short it clearly
    isn't a report (protects against accidentally parsing an
    `_TEMPLATE/REPORT.md` shell as a real entry).
    """
    the_path = Path(path)
    try:
        text = the_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if len(text) < 200:  # very short files are templates / placeholders
        return None
    m_title = _TITLE_RE.search(text)
    title = m_title.group("val").strip() if m_title else the_path.stem
    m_verdict = _VERDICT_LINE_RE.search(text)
    status_raw = m_verdict.group("val").strip() if m_verdict else ""
    verdict_kind = _classify_verdict(status_raw)
    m_date = _DATE_LINE_RE.search(text)
    date = m_date.group("val").strip() if m_date else ""
    abstract = _extract_abstract(text)
    campaign_id = _campaign_id_from_path(the_path) or the_path.stem
    return {
        "campaign_id": campaign_id,
        "title": title,
        "date": date,
        "status_raw": status_raw,
        "verdict_kind": verdict_kind,
        "abstract": abstract,
        "report_path": str(the_path),
        "source_size": len(text),
    }


def _iter_report_paths(research_root: Path) -> list[Path]:
    """Return the canonical REPORT.md paths under ``research_root``,
    across both the ``experiments/`` lane and any ``programs/*/
    experiments/*/`` lane. Skips ``_TEMPLATE`` dirs and drift copies.
    """
    out: list[Path] = []
    if not research_root.is_dir():
        return out
    for base in (research_root / "experiments",
                 research_root / "programs"):
        if not base.is_dir():
            continue
        for candidate in base.rglob(_REPORT_FILENAME):
            if candidate.name != _REPORT_FILENAME:
                continue
            if "_TEMPLATE" in candidate.parts:
                continue
            out.append(candidate)
    return out


def list_all(research_root: Path | str | None) -> list[dict]:
    """Return every parseable REPORT.md under ``research_root``.

    Entries are sorted newest-first by (parsed date descending, then
    campaign_id ascending). Unparseable files are dropped silently
    -- the CPO manifest is the ground truth for what appears
    publicly, so a broken report simply won't be a candidate for
    publication.
    """
    if research_root is None:
        return []
    root = Path(research_root)
    entries: list[dict] = []
    for path in _iter_report_paths(root):
        parsed = parse_report(path)
        if parsed is not None:
            entries.append(parsed)
    def _sort_key(e: dict) -> tuple:
        d = e.get("date") or ""
        # Turn ISO-ish leading dates into sortable prefixes, else empty.
        m = re.search(r"(\d{4}-\d{2}-\d{2})", d)
        key = m.group(1) if m else ""
        return (key, e.get("campaign_id", ""))
    entries.sort(key=_sort_key, reverse=True)
    return entries


# --------------------------------------------------------------------
# Publication merge
# --------------------------------------------------------------------

def _decorate(parsed: dict, manifest_row: dict) -> dict:
    """Merge parser output with the manifest override row.

    Manifest wins on every user-facing string; parser fills anything
    the manifest didn't override. This lets Brand + Marketing write
    the plain-English summary and CPO the verdict label without
    having to touch REPORT.md files in the research repo."""
    return {
        "campaign_id": parsed.get("campaign_id"),
        "title": manifest_row.get("title") or parsed.get("title"),
        "date": manifest_row.get("date") or parsed.get("date"),
        "verdict_kind": (manifest_row.get("verdict_kind")
                         or parsed.get("verdict_kind")),
        "verdict_label": (manifest_row.get("verdict_label")
                          or parsed.get("status_raw")
                          or parsed.get("verdict_kind")),
        "summary": (manifest_row.get("brand_summary")
                    or parsed.get("abstract")),
        "headline_stat": manifest_row.get("headline_stat"),
        "report_path": (manifest_row.get("report_path")
                        or parsed.get("report_path")),
        "report_commit_sha_hint": manifest_row.get("report_commit_sha_hint"),
    }


def get_state(
    *,
    research_root: Path | str | None = None,
    manifest_path: Path | str | None = None,
) -> dict:
    """Return the /research API payload.

    ``research_root``:   sibling ``finance-research-experiments``
        checkout (or None if not on this machine).
    ``manifest_path``:   override for
        ``company/research/publication_manifest.json``.

    Contract keys:

    * ``generated_at`` -- UTC ISO8601 (Z-suffixed).
    * ``source_repo_path`` -- absolute string path of the research
      root, or ``None``.
    * ``source_exists`` -- ``True`` iff research_root is a directory.
    * ``cpo_signoff_by`` / ``cpo_signoff_at`` -- from manifest.
    * ``entries`` -- list of published entries (manifest allow-list
      intersected with parseable reports), newest-first.
    * ``all_candidates`` -- count of parseable REPORT.md files found
      (regardless of publication). Lets the UI show "1 of N
      published".
    * ``unconfigured`` -- ``True`` when the manifest is missing /
      malformed. Page falls back to a friendly empty state.
    """
    manifest = load_manifest(manifest_path)
    root = Path(research_root) if research_root else None
    source_exists = bool(root and root.is_dir())
    all_entries = list_all(root) if source_exists else []
    published: list[dict] = []
    for entry in all_entries:
        cid = entry.get("campaign_id")
        row = manifest["entries"].get(cid)
        if not row or not row.get("publish", False):
            continue
        published.append(_decorate(entry, row))
    return {
        "generated_at": _now_iso(),
        "source_repo_path": str(root) if root else None,
        "source_exists": source_exists,
        "cpo_signoff_by": manifest.get("cpo_signoff_by"),
        "cpo_signoff_at": manifest.get("cpo_signoff_at"),
        "entries": published,
        "all_candidates": len(all_entries),
        "published_total": len(published),
        "unconfigured": bool(manifest.get("unconfigured", False)),
    }
