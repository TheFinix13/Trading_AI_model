"""M001 squad replay -> football-pitch event timeline (v2 page data plane).

Parses one replay cache directory (the JSONL artifacts the research
repo's walk-forward harness writes) into a single time-ordered list of
"match events" the pitch UI can play back:

* ``proposal``   -- an agent published a trade intent (a pass/shot).
* ``blocked``    -- the aggregator or Sentinel rejected it (a tackle /
                    the wall). ``by`` names the winning agent or rule.
* ``open``       -- a proposal was executed (shot on target).
* ``close``      -- the trade resolved: pnl > 0 is a GOAL, else a miss.
* ``thought``    -- an agent's inner monologue line (speech bubble).
                    Parsed from an OPTIONAL ``thoughts.jsonl`` in the
                    cache dir; the G7 review caches do not ship one, so
                    this type is designed into the schema for the future
                    live paper loop and degrades to absent when the file
                    is missing. Expected row shape: ``{"agent_id",
                    "timestamp", "symbol"?, "text"|"thought"|"content"}``.
* ``tick_summary`` -- one row per H4 tick, emitted by the live squad
                    engine into an OPTIONAL ``events.jsonl``. Serves as
                    proof-of-life on quiet bars (0 proposals) so the /v2
                    ticker keeps moving even when nothing traded. Does
                    NOT count toward the per-agent trade / goal tally.

Every event carries a light payload for playback plus a heavy ``detail``
dict (full rationale, tqs_components, mae/mfe, ...). ``get_events``
strips ``detail`` to keep the paged payloads small; the UI fetches it
lazily per event via ``get_event_detail`` (the
``/api/v2/match/<id>/event/<n>`` endpoint).

HARD RULE: this module reads artifact FILES only. It never imports
research-repo code. The default artifact location is the sibling
``finance-research-experiments`` checkout, overridable via
``--research-reviews`` on the server CLI, so a VM clone layout works
the same as the Mac layout.

The same event schema is designed to be fed later by a LIVE paper-mode
squad loop appending to the same three JSONL files -- the UI polls a
cursor, so "replay" and "live tail" are the same client code.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Roster: canon players -> pitch formation (x, y in percent of pitch,
# y grows toward the opponent goal). Kunigami sits deep: retired from
# proposing 2026-07-06, retained as the Sentinel R5 anti-tilt channel.
# ---------------------------------------------------------------------------

ROSTER: dict[str, dict] = {
    "isagi_yoichi":     {"name": "Isagi",    "num": 11, "x": 50, "y": 58,
                         "color": "#58a6ff", "role": "playmaker · metavision"},
    "bachira_meguru":   {"name": "Bachira",  "num": 8,  "x": 30, "y": 64,
                         "color": "#bc8cff", "role": "dribbler · zone rebel"},
    "itoshi_rin":       {"name": "Rin",      "num": 10, "x": 70, "y": 64,
                         "color": "#39d2c0", "role": "precision · lone reads"},
    "nagi_seishiro":    {"name": "Nagi",     "num": 7,  "x": 62, "y": 82,
                         "color": "#d29922", "role": "finisher · confluence"},
    "barou_shoei":      {"name": "Barou",    "num": 9,  "x": 38, "y": 82,
                         "color": "#f85149", "role": "striker · solo king"},
    "chigiri_hyoma":    {"name": "Chigiri",  "num": 14, "x": 12, "y": 72,
                         "color": "#ff7b72", "role": "speed · momentum"},
    "reo_mikage":       {"name": "Reo",      "num": 6,  "x": 50, "y": 38,
                         "color": "#3fb950", "role": "midfield general · copier"},
    "kunigami_rensuke": {"name": "Kunigami", "num": 5,  "x": 50, "y": 16,
                         "color": "#8b949e", "role": "defender · Sentinel R5"},
}

# Rejection reasons that are Sentinel/system rules rather than a peer
# out-competing the proposal. Shown as the "wall", not a tackle.
_RULE_PREFIXES = ("r1_", "r2_", "r3_", "r4_", "r5_", "r6_", "kunigami_")

_CACHE_FILES = ("proposals_all.jsonl", "proposals_rejected.jsonl",
                "trades.jsonl")

# Optional artifacts a cache MAY carry; they feed extra event types but
# their absence is normal (the G7 review caches have none, and older
# live paper runs pre-date events.jsonl).
_OPTIONAL_FILES = ("thoughts.jsonl", "events.jsonl")

_timeline_cache: dict[str, tuple[tuple, list[dict], dict]] = {}
_cache_lock = threading.Lock()


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def list_matches(reviews_dir: Path) -> list[dict]:
    """Replay cache dirs that contain a full artifact set, newest first."""
    out = []
    if not reviews_dir.exists():
        return out
    for child in sorted(reviews_dir.iterdir()):
        if not child.is_dir() or not child.name.startswith("g7_replay_cache_"):
            continue
        if not all((child / f).exists() for f in _CACHE_FILES):
            continue
        label = child.name.removeprefix("g7_replay_cache_")
        out.append({
            "id": child.name,
            "label": label,
            "mtime": child.stat().st_mtime,
        })
    out.sort(key=lambda m: -m["mtime"])
    return out


def _cache_key(cache_dir: Path) -> tuple:
    parts = []
    for f in _CACHE_FILES + _OPTIONAL_FILES:
        p = cache_dir / f
        s = p.stat() if p.exists() else None
        parts.append((f, int(s.st_mtime_ns) if s else 0,
                      int(s.st_size) if s else 0))
    return tuple(parts)


def build_timeline(cache_dir: Path) -> tuple[list[dict], dict]:
    """(events sorted by time, per-agent summary). Cached on file stats."""
    key = _cache_key(cache_dir)
    with _cache_lock:
        hit = _timeline_cache.get(str(cache_dir))
        if hit is not None and hit[0] == key:
            return hit[1], hit[2]

    events: list[dict] = []

    for p in _read_jsonl(cache_dir / "proposals_all.jsonl"):
        agent = p.get("agent_id", "?")
        rat = p.get("rationale") if isinstance(p.get("rationale"), dict) else {}
        events.append({
            "t": p.get("timestamp", ""),
            "type": "proposal",
            "agent": agent,
            "symbol": p.get("symbol", "?"),
            "dir": p.get("direction", "?"),
            "conviction": round(float(p.get("conviction", 0.0)), 3),
            "detail": {
                "entry": p.get("entry"),
                "stop": p.get("stop"),
                "regime_fit": p.get("regime_fit"),
                "agent_tier": p.get("agent_tier"),
                "signal_reason": rat.get("signal_reason"),
                "doctrine_ref": rat.get("doctrine_ref"),
                "empirical_prior": rat.get("empirical_prior"),
                "base_conviction": rat.get("base_conviction"),
                "final_conviction": rat.get("final_conviction"),
                "peer_confluence_isagi": rat.get("peer_confluence_isagi"),
                "peer_confluence_lift": rat.get("peer_confluence_lift"),
                "htf_align": rat.get("htf_align"),
                "atr_pips": rat.get("atr_pips"),
            },
        })

    for r in _read_jsonl(cache_dir / "proposals_rejected.jsonl"):
        reason = r.get("rejection_reason", "?")
        is_rule = reason.startswith(_RULE_PREFIXES)
        events.append({
            "t": r.get("timestamp", ""),
            "type": "blocked",
            "agent": r.get("loser_agent_id", "?"),
            "symbol": r.get("symbol", "?"),
            "by": ("SENTINEL" if is_rule
                   else r.get("winner_agent_id", "?")),
            "rule": is_rule,
            "reason": reason,
            "detail": {
                "winner_conviction": r.get("winner_conviction"),
                "loser_conviction": r.get("loser_conviction"),
                "winner_tier": r.get("winner_tier"),
                "loser_tier": r.get("loser_tier"),
                "winner_direction": r.get("winner_direction"),
                "loser_direction": r.get("loser_direction"),
                "tick_id": r.get("tick_id"),
            },
        })

    for t in _read_jsonl(cache_dir / "trades.jsonl"):
        agent = t.get("agent_id", "?")
        symbol = t.get("symbol", "?")
        pnl = float(t.get("pnl_pips", 0.0))
        tqs = None
        tc = t.get("tqs_components")
        if isinstance(tc, dict) and tc.get("tqs") is not None:
            tqs = round(float(tc["tqs"]), 3)
        events.append({
            "t": t.get("entry_time", ""),
            "type": "open",
            "agent": agent,
            "symbol": symbol,
            "dir": t.get("direction", "?"),
            "detail": {
                "entry": t.get("entry"),
                "stop": t.get("stop"),
                "take_profit": t.get("take_profit"),
                "source_conviction": t.get("source_conviction"),
                "source_sl_pips": t.get("source_sl_pips"),
            },
        })
        events.append({
            "t": t.get("exit_time", ""),
            "type": "close",
            "agent": agent,
            "symbol": symbol,
            "goal": pnl > 0,
            "pnl_pips": round(pnl, 1),
            "tqs": tqs,
            "exit_reason": t.get("exit_reason", "?"),
            "r": t.get("r_multiple"),
            "detail": {
                "r_multiple": t.get("r_multiple"),
                "mae_pips": t.get("mae_pips"),
                "mfe_pips": t.get("mfe_pips"),
                "bars_held": t.get("bars_held"),
                "exit_price": t.get("exit_price"),
                "tqs_components": tc if isinstance(tc, dict) else None,
            },
        })

    # Optional thoughts stream (absent in the G7 review caches — see the
    # module docstring). One row -> one lightweight `thought` event.
    for th in _read_jsonl(cache_dir / "thoughts.jsonl"):
        text = th.get("text") or th.get("thought") or th.get("content") or ""
        events.append({
            "t": th.get("timestamp", ""),
            "type": "thought",
            "agent": th.get("agent_id", "?"),
            "symbol": th.get("symbol"),
            "text": str(text)[:200],
        })

    # Optional per-tick summary stream (events.jsonl). Live squad emits
    # one row per H4 tick per symbol so the /v2 ticker keeps moving on
    # bars with 0 proposals. Older caches don't ship this file. Only
    # rows tagged type=='tick_summary' are recognised; other rows are
    # skipped defensively so the file can grow to hold other event
    # types later without breaking older UIs.
    for ts_row in _read_jsonl(cache_dir / "events.jsonl"):
        if ts_row.get("type") != "tick_summary":
            continue
        players_ev = ts_row.get("players_evaluated") or []
        players_pr = ts_row.get("players_who_proposed") or []
        events.append({
            "t": ts_row.get("timestamp", ""),
            "type": "tick_summary",
            "symbol": ts_row.get("symbol", "?"),
            "tick_id": int(ts_row.get("tick_id", 0)),
            "players_evaluated": (
                list(players_ev) if isinstance(players_ev, list) else []
            ),
            "players_who_proposed": (
                list(players_pr) if isinstance(players_pr, list) else []
            ),
            "proposal_count": int(ts_row.get("proposal_count", 0)),
            "post_sentinel_count": int(ts_row.get("post_sentinel_count", 0)),
            "workspace_thought_count": int(
                ts_row.get("workspace_thought_count", 0)
            ),
            # Compact per-tick preview of the squad's head so the /v2
            # workspace panel can update on click of a tick_summary row
            # in historical replays. Absent on older caches -> empty list.
            "thoughts_top5": (
                list(ts_row.get("thoughts_top5") or [])
                if isinstance(ts_row.get("thoughts_top5"), list) else []
            ),
        })

    events.sort(key=lambda e: _parse_ts(e["t"]) if e["t"] else datetime.min)

    summary = _summarise(cache_dir, events)
    with _cache_lock:
        _timeline_cache[str(cache_dir)] = (key, events, summary)
    return events, summary


def _summarise(cache_dir: Path, events: list[dict]) -> dict:
    per_agent: dict[str, dict] = {}

    def rec(agent: str) -> dict:
        return per_agent.setdefault(agent, {
            "proposals": 0, "blocked": 0, "trades": 0,
            "goals": 0, "pips": 0.0, "tqs_sum": 0.0, "tqs_n": 0,
        })

    for e in events:
        if e["type"] == "proposal":
            rec(e["agent"])["proposals"] += 1
        elif e["type"] == "blocked":
            rec(e["agent"])["blocked"] += 1
        elif e["type"] == "close":
            d = rec(e["agent"])
            d["trades"] += 1
            d["pips"] += e["pnl_pips"]
            if e["goal"]:
                d["goals"] += 1
            if e.get("tqs") is not None:
                d["tqs_sum"] += e["tqs"]
                d["tqs_n"] += 1

    for d in per_agent.values():
        d["mean_tqs"] = (round(d["tqs_sum"] / d["tqs_n"], 4)
                         if d["tqs_n"] else None)
        d["win_rate"] = (round(d["goals"] / d["trades"], 3)
                         if d["trades"] else None)
        d["pips"] = round(d["pips"], 1)
        del d["tqs_sum"], d["tqs_n"]

    ws = {}
    ws_path = cache_dir / "workspace_counts.json"
    if ws_path.exists():
        try:
            ws = json.loads(ws_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ws = {}

    return {
        "n_events": len(events),
        "t_start": events[0]["t"] if events else None,
        "t_end": events[-1]["t"] if events else None,
        "per_agent": per_agent,
        "workspace": ws,
        "roster": ROSTER,
    }


def get_events(cache_dir: Path, cursor: int, limit: int) -> dict:
    """Cursor-paged slice of the timeline (the playback API payload).

    Heavy ``detail`` dicts are stripped here — the UI fetches them
    lazily per event through :func:`get_event_detail`.
    """
    events, summary = build_timeline(cache_dir)
    cursor = max(0, int(cursor))
    limit = max(1, min(int(limit), 2000))
    window = [{k: v for k, v in e.items() if k != "detail"}
              for e in events[cursor:cursor + limit]]
    return {
        "cursor": cursor,
        "next_cursor": cursor + len(window),
        "total": summary["n_events"],
        "events": window,
    }


def get_event_detail(cache_dir: Path, index: int) -> dict | None:
    """The full payload of one event by timeline index (drill-down)."""
    events, _ = build_timeline(cache_dir)
    if 0 <= index < len(events):
        return events[index]
    return None
