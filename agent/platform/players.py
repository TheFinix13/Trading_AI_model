"""F002 -- Public `/players` + `/players/:id` data plane.

Data sources
------------

* **Static bio content** -- `company/roster/players/<id>.md`
  (10 files, authored by AI/ML Engineer + Brand Designer). Parsed
  once per module import into an in-memory dict; the platform
  server does not hot-reload bios, but tests can reset the cache
  via :func:`_reset_bio_cache`.
* **Live activity** -- `squad_live/events.jsonl` (same file the
  F001 performance module reads; same file the `/v2` pitch UI
  polls). Only ``propose`` (a.k.a. ``proposal``), ``open``, and
  ``close`` rows contribute. Missing / unreadable file degrades
  to zeros; the F005 empty-state affordance covers that case in
  the UI.

Contract
--------

* :func:`list_players` -> ``[{id, name, playstyle_tag, status,
  tier, symbols, signature_blurb, proposals, wins, net_pips}]``
  ordered by roster canonical order (Isagi first, Kunigami last).
* :func:`get_player(id, live_dir=None)` -> ``{id, name,
  canon_player, playstyle_tag, status, tier, weapon, symbols,
  home_tf, signature_blurb, playstyle_prose, signature_setup,
  evolution, stats, recent_activity, source_hint, generated_at}``.
  Unknown id -> ``None``; the route handler returns a 404 shell
  with the ten valid names.

Read-only invariant
-------------------

Nothing under ``live_dir`` or ``company/roster/players/`` is
written to by any function in this module. The tests assert this
by taking directory checksums before / after every call.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Canonical roster order + slug -> static metadata. Slugs match the
# markdown filenames under company/roster/players/. `agent_key` is the
# events.jsonl agent-identifier the striker writes under (matches
# `agent.squad.agents.aXX_<name>.py`'s agent_id default).
_ROSTER: tuple[dict, ...] = (
    {
        "id": "isagi",
        "name": "Isagi",
        "canon_player": "isagi_yoichi",
        "agent_key": "isagi_yoichi",
        "playstyle_tag": "Metavision zone reader",
        "status": "active",
        "tier": 1,
        "weapon": "metavision_seed_zone_d1_against",
        "symbols": ("EURUSD", "GBPUSD", "USDCAD"),
        "home_tf": "H4",
    },
    {
        "id": "bachira",
        "name": "Bachira",
        "canon_player": "bachira_meguru",
        "agent_key": "bachira_meguru",
        "playstyle_tag": "Rebel dribbler (tight-stop specialist)",
        "status": "active",
        "tier": 2,
        "weapon": "monstrous_dribble_rebel_baseline_zone",
        "symbols": ("EURUSD", "GBPUSD", "USDCAD"),
        "home_tf": "H4",
    },
    {
        "id": "rin",
        "name": "Rin",
        "canon_player": "itoshi_rin",
        "agent_key": "itoshi_rin",
        "playstyle_tag": "Cold geometric precision",
        "status": "active",
        "tier": 2,
        "weapon": "precision_geometry_strict_rr_zone",
        "symbols": ("EURUSD",),
        "home_tf": "H4",
    },
    {
        "id": "chigiri",
        "name": "Chigiri",
        "canon_player": "chigiri_hyoma",
        "agent_key": "chigiri_hyoma",
        "playstyle_tag": "Speed continuation striker",
        "status": "active",
        "tier": 2,
        "weapon": "speed_atr_breakout_continuation",
        "symbols": ("EURUSD", "GBPUSD"),
        "home_tf": "H4",
    },
    {
        "id": "reo",
        "name": "Reo",
        "canon_player": "reo_mikage",
        "agent_key": "reo_mikage",
        "playstyle_tag": "Chameleon copier",
        "status": "active",
        "tier": 2,
        "weapon": "chameleon_per_tick_mirror_v1",
        "symbols": ("EURUSD", "GBPUSD", "USDCAD"),
        "home_tf": "H4",
    },
    {
        "id": "nagi",
        "name": "Nagi",
        "canon_player": "nagi_seishiro",
        "agent_key": "nagi_seishiro",
        "playstyle_tag": "Confluence-only perfect trap",
        "status": "active",
        "tier": 2,
        "weapon": "perfect_trap_chemical_reaction_v1",
        "symbols": ("EURUSD", "GBPUSD", "USDCAD"),
        "home_tf": "H4",
    },
    {
        "id": "barou",
        "name": "Barou",
        "canon_player": "barou_shoei",
        "agent_key": "barou_shoei",
        "playstyle_tag": "USDCAD lone-wolf king",
        "status": "active",
        "tier": 2,
        "weapon": "lone_wolf_baseline_zone_usdcad",
        "symbols": ("USDCAD",),
        "home_tf": "H4",
    },
    {
        "id": "karasu",
        "name": "Karasu",
        "canon_player": "karasu_tabito",
        "agent_key": "karasu_tabito",
        "playstyle_tag": "News-window defender (side channel)",
        "status": "standby",
        "tier": 2,
        "weapon": "news_window_defender",
        "symbols": ("EURUSD", "GBPUSD", "USDCAD"),
        "home_tf": "N/A",
    },
    {
        "id": "sae",
        "name": "Sae",
        "canon_player": "sae_itoshi",
        "agent_key": "sae_itoshi",
        "playstyle_tag": "Event-window specialist (disabled by default)",
        "status": "standby",
        "tier": 1,
        "weapon": "event_release_impulse",
        "symbols": ("EURUSD", "GBPUSD", "USDCAD"),
        "home_tf": "M5",
    },
    {
        "id": "kunigami",
        "name": "Kunigami",
        "canon_player": "kunigami_rensuke",
        "agent_key": "kunigami_rensuke",
        "playstyle_tag": "Anti-tilt discipline (retired from proposing)",
        "status": "retired",
        "tier": 2,
        "weapon": "anti_tilt_recovery_discipline",
        "symbols": ("EURUSD", "GBPUSD", "USDCAD"),
        "home_tf": "N/A",
    },
)

# Directory for bio markdown, plus its default location.
_DEFAULT_BIO_DIR = REPO_ROOT / "company" / "roster" / "players"

_VALID_IDS: tuple[str, ...] = tuple(r["id"] for r in _ROSTER)


# --------------------------------------------------------------------
# ID normalisation
# --------------------------------------------------------------------

_ID_STRIP_RE = re.compile(r"[^a-z0-9]+")


def normalize_id(raw: str | None) -> str | None:
    """Fold ``Isagi``, ``isagi/``, ``isagi-v1``, ``isagi_yoichi`` to
    the canonical short slug ``isagi``. Returns ``None`` if the input
    is empty or doesn't resolve to a known striker.
    """
    if not raw:
        return None
    lower = str(raw).strip().lower()
    lower = _ID_STRIP_RE.sub("-", lower).strip("-")
    if not lower:
        return None
    # exact match on canonical id
    if lower in _VALID_IDS:
        return lower
    # match on the canon_player key ("isagi_yoichi" -> "isagi")
    for entry in _ROSTER:
        cp = entry["canon_player"].replace("_", "-")
        if lower == cp:
            return entry["id"]
    # allow trailing suffixes: "isagi-v1", "isagi-yoichi", ...
    first = lower.split("-", 1)[0]
    if first in _VALID_IDS:
        return first
    return None


def valid_ids() -> tuple[str, ...]:
    """Return the canonical tuple of striker slugs, in roster order."""
    return _VALID_IDS


def roster_meta() -> tuple[dict, ...]:
    """Read-only view over the roster metadata rows."""
    return tuple({**r, "symbols": list(r["symbols"])} for r in _ROSTER)


# --------------------------------------------------------------------
# Bio markdown parsing
# --------------------------------------------------------------------

_bio_cache: dict[str, dict] = {}


def _reset_bio_cache() -> None:
    """Test hook: drop the parsed-bio cache so a fresh `bio_dir` is
    picked up on the next call. Production code never calls this."""
    _bio_cache.clear()


def _parse_bio_markdown(md_path: Path) -> dict:
    """Parse the sections we surface out of a bio markdown file.

    Expected sections (H2 headings, appearing in order):

    * ``## Playstyle prose``   -> ``playstyle_prose`` (verbatim body)
    * ``## Signature setup``   -> ``signature_setup`` (verbatim body,
      typically an ASCII code fence)
    * ``## Evolution history`` -> ``evolution`` (list of ``{note}``)

    Missing files / sections yield empty defaults; the UI degrades
    gracefully via the F005 empty state.
    """
    if not md_path.is_file():
        return {
            "playstyle_prose": "",
            "signature_setup": "",
            "evolution": [],
            "signature_blurb": "",
        }
    text = md_path.read_text(encoding="utf-8")
    sections: dict[str, list[str]] = {}
    header_meta: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        m_h = re.match(r"^##\s+(.+?)\s*$", line)
        if m_h:
            current = m_h.group(1).strip().lower()
            sections[current] = []
            continue
        m_bullet = re.match(
            r"^- \*\*(?P<key>[^*:]+):\*\*\s*(?P<val>.*)$", line,
        )
        if m_bullet and current is None:
            key = m_bullet.group("key").strip().lower()
            val = m_bullet.group("val").strip()
            header_meta[key] = val
            continue
        if current is not None:
            sections[current].append(line)
    prose = "\n".join(sections.get("playstyle prose", [])).strip()
    setup = "\n".join(sections.get("signature setup", [])).strip()
    evolution_raw = sections.get("evolution history", [])
    evolution: list[dict] = []
    for line in evolution_raw:
        m = re.match(r"^-\s+(.+?)\s*$", line)
        if m:
            evolution.append({"note": m.group(1).strip()})
    return {
        "playstyle_prose": prose,
        "signature_setup": setup,
        "evolution": evolution,
        "signature_blurb": header_meta.get("signature_blurb", ""),
    }


def _load_bio(id_: str, bio_dir: Path | None = None) -> dict:
    """Return the parsed bio for ``id_``, cached per (id, dir) key."""
    the_dir = bio_dir if bio_dir is not None else _DEFAULT_BIO_DIR
    cache_key = f"{the_dir}::{id_}"
    hit = _bio_cache.get(cache_key)
    if hit is not None:
        return hit
    parsed = _parse_bio_markdown(the_dir / f"{id_}.md")
    _bio_cache[cache_key] = parsed
    return parsed


# --------------------------------------------------------------------
# Live events ingestion
# --------------------------------------------------------------------

def _read_events(live_dir: Path | None) -> list[dict]:
    """Return every row of ``<live_dir>/events.jsonl`` as a dict.

    Missing dir or missing file -> ``[]``. Malformed rows are skipped
    defensively (the /v2 ticker uses the same file and never crashes
    on schema drift, so we match that posture).
    """
    if not live_dir or not live_dir.is_dir():
        return []
    events_file = live_dir / "events.jsonl"
    if not events_file.is_file():
        return []
    rows: list[dict] = []
    with events_file.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _row_agent_key(row: dict) -> str:
    """Row schema is unstable across squad_live vs. research replay caches:
    ``agent`` in the live-loop dumps, ``agent_id`` in the older caches.
    Pick whichever is present."""
    return str(row.get("agent") or row.get("agent_id") or "").strip()


def _filter_rows_for(agent_key: str, rows: list[dict]) -> list[dict]:
    return [r for r in rows if _row_agent_key(r) == agent_key]


def _stats_for_agent(agent_key: str, rows: list[dict]) -> dict:
    """Compute the striker's career stats from event rows.

    Contract:

    * ``proposals``     : count of ``propose``/``proposal`` rows.
    * ``wins``          : ``close`` rows with numeric ``pnl_pips`` > 0.
    * ``losses``        : ``close`` rows with numeric ``pnl_pips`` <= 0.
    * ``trades``        : wins + losses (i.e. resolved closes only).
    * ``win_rate_pct``  : wins / trades * 100, or 0.0 when no trades.
    * ``net_pips``      : sum of numeric ``pnl_pips`` across closes.
    * ``avg_pips``      : net_pips / trades, or 0.0 when no trades.
    * ``best_trade_pips`` / ``worst_trade_pips`` : extremes across
      closes; both 0.0 when no trades.
    * ``best_pair``     : symbol with the highest net-pips sum, or
      ``None`` when no trades.
    * ``days_active``   : distinct UTC-date prefixes across ALL rows
      for this agent (proposals count -- a striker who proposed but
      never had a fill is still 'active' that day).
    """
    my_rows = _filter_rows_for(agent_key, rows)
    proposals = sum(
        1 for r in my_rows
        if r.get("type") in ("propose", "proposal")
    )
    closes = [
        r for r in my_rows
        if r.get("type") == "close"
        and isinstance(r.get("pnl_pips"), (int, float))
    ]
    wins = sum(1 for r in closes if float(r["pnl_pips"]) > 0)
    losses = len(closes) - wins
    trades = len(closes)
    net = round(sum(float(r["pnl_pips"]) for r in closes), 1)
    avg = round(net / trades, 2) if trades else 0.0
    win_rate = round(100.0 * wins / trades, 1) if trades else 0.0
    best_trade = round(max((float(r["pnl_pips"]) for r in closes), default=0.0), 1)
    worst_trade = round(min((float(r["pnl_pips"]) for r in closes), default=0.0), 1)
    # best pair
    by_pair: dict[str, float] = {}
    for r in closes:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        by_pair[sym] = by_pair.get(sym, 0.0) + float(r["pnl_pips"])
    best_pair = None
    if by_pair:
        best_pair = max(by_pair.items(), key=lambda kv: kv[1])[0]
    days_active = len({
        (str(r.get("t") or r.get("timestamp") or ""))[:10]
        for r in my_rows
        if (str(r.get("t") or r.get("timestamp") or ""))[:10]
    })
    return {
        "proposals": proposals,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate,
        "net_pips": net,
        "avg_pips": avg,
        "best_trade_pips": best_trade,
        "worst_trade_pips": worst_trade,
        "best_pair": best_pair,
        "days_active": days_active,
    }


def _recent_activity(agent_key: str, rows: list[dict], n: int = 5) -> list[dict]:
    """Last ``n`` rows for this striker, newest first.

    Rows are already appended in time order to events.jsonl by the
    paper loop, so we sort defensively by the ``t``/``timestamp``
    field and pick the tail. Each row is compressed to the fields
    the bio card renders (t, type, symbol, dir, pnl_pips, conviction).
    """
    my_rows = _filter_rows_for(agent_key, rows)
    def _ts(r: dict) -> str:
        return str(r.get("t") or r.get("timestamp") or "")
    my_rows.sort(key=_ts)
    tail = my_rows[-n:][::-1]
    out: list[dict] = []
    for r in tail:
        item = {
            "t": _ts(r),
            "type": str(r.get("type") or ""),
            "symbol": str(r.get("symbol") or "").upper() or None,
        }
        if r.get("dir"):
            item["dir"] = str(r["dir"]).lower()
        if isinstance(r.get("pnl_pips"), (int, float)):
            item["pnl_pips"] = round(float(r["pnl_pips"]), 1)
        if isinstance(r.get("conviction"), (int, float)):
            item["conviction"] = round(float(r["conviction"]), 3)
        out.append(item)
    return out


# --------------------------------------------------------------------
# Source hint
# --------------------------------------------------------------------

def _source_hint(rows: list[dict], my_rows: int, status: str) -> str:
    if status == "retired":
        return "Retired from proposing -- Sentinel R5 side channel only."
    if status == "standby" and my_rows == 0:
        return "On standby -- no live rows yet. Enable to see activity."
    if not rows:
        return "No shadow-paper events on tape yet -- come back after the next H4 bar close."
    if my_rows == 0:
        return "Live tape found, but this striker has no rows yet."
    return f"{my_rows} live rows on tape from the v2 shadow-paper squad."


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------

def get_player(
    id_: str | None,
    *,
    live_dir: Path | str | None = None,
    bio_dir: Path | str | None = None,
) -> dict | None:
    """Return the full player payload, or ``None`` for unknown id."""
    canonical = normalize_id(id_)
    if canonical is None:
        return None
    row_meta = next((r for r in _ROSTER if r["id"] == canonical), None)
    if row_meta is None:  # pragma: no cover - guarded above
        return None
    the_bio_dir = Path(bio_dir) if bio_dir is not None else None
    bio = _load_bio(canonical, bio_dir=the_bio_dir)
    live = Path(live_dir) if live_dir is not None else None
    rows = _read_events(live)
    stats = _stats_for_agent(row_meta["agent_key"], rows)
    activity = _recent_activity(row_meta["agent_key"], rows)
    my_row_count = sum(
        1 for r in rows if _row_agent_key(r) == row_meta["agent_key"]
    )
    return {
        "id": row_meta["id"],
        "name": row_meta["name"],
        "canon_player": row_meta["canon_player"],
        "playstyle_tag": row_meta["playstyle_tag"],
        "status": row_meta["status"],
        "tier": row_meta["tier"],
        "weapon": row_meta["weapon"],
        "symbols": list(row_meta["symbols"]),
        "home_tf": row_meta["home_tf"],
        "signature_blurb": bio["signature_blurb"],
        "playstyle_prose": bio["playstyle_prose"],
        "signature_setup": bio["signature_setup"],
        "evolution": bio["evolution"],
        "stats": stats,
        "recent_activity": activity,
        "source_hint": _source_hint(rows, my_row_count, row_meta["status"]),
        "generated_at": _now_iso(),
    }


def list_players(
    *,
    live_dir: Path | str | None = None,
    bio_dir: Path | str | None = None,
) -> list[dict]:
    """Return the roster index in canonical order.

    Each row carries ``id``, ``name``, ``playstyle_tag``, ``status``,
    ``tier``, ``symbols``, ``signature_blurb`` from the bio, and
    three "top-line stats" (proposals / wins / net_pips) so the
    index card can show at-a-glance numbers without a per-player
    fetch.
    """
    live = Path(live_dir) if live_dir is not None else None
    rows = _read_events(live)
    the_bio_dir = Path(bio_dir) if bio_dir is not None else None
    out: list[dict] = []
    for entry in _ROSTER:
        bio = _load_bio(entry["id"], bio_dir=the_bio_dir)
        stats = _stats_for_agent(entry["agent_key"], rows)
        out.append({
            "id": entry["id"],
            "name": entry["name"],
            "playstyle_tag": entry["playstyle_tag"],
            "status": entry["status"],
            "tier": entry["tier"],
            "symbols": list(entry["symbols"]),
            "signature_blurb": bio["signature_blurb"],
            "proposals": stats["proposals"],
            "wins": stats["wins"],
            "net_pips": stats["net_pips"],
        })
    return out


def list_state(
    *,
    live_dir: Path | str | None = None,
    bio_dir: Path | str | None = None,
) -> dict:
    """Payload for GET /api/players/list -- wraps ``list_players``
    in the same envelope shape the other platform APIs use."""
    return {
        "generated_at": _now_iso(),
        "players": list_players(live_dir=live_dir, bio_dir=bio_dir),
        "total": len(_ROSTER),
    }
