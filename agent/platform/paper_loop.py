"""Shadow-only paper loop shell for the v2 squad (STUB team).

The squad's real agent logic lives in the research repo and is NOT yet
validated for porting (G7 gate pending). Until it graduates, this loop
replays an existing replay cache in accelerated wall-clock time,
appending raw rows to a LIVE output directory in the exact same
three-JSONL schema the review caches use. That proves the end-to-end
live plumbing (writer -> mtime-cached parser -> live-tail API -> LIVE
page) so the validated squad can drop in later as a different row
source.

HARD GUARANTEES:

* Shadow-only. This module never talks to a broker, never imports MT5,
  never places orders. It only copies JSON rows between files.
* The research repo is read-only source material; output goes under the
  local log root (``<log-root>/squad_live/`` by default).
* A ``kill.txt`` in the output directory stops the loop at the next
  tick.
* ``state.json`` in the output directory records per-file cursors so a
  restarted loop resumes where it left off instead of double-appending.

Parity contract: replaying a cache end-to-end produces an output dir
whose parsed event stream is byte-equivalent to parsing the source
cache directly (rows are appended verbatim, per-file relative order
preserved, so ``squad_events.build_timeline`` sees identical input).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.news.calendar import (
    DEFAULT_CACHE_PATH as NEWS_CACHE_PATH,
    cache_fetched_at,
    filter_events,
    load_calendar,
)

# (filename, timestamp field used to pace the replay clock)
SOURCE_FILES: tuple[tuple[str, str], ...] = (
    ("proposals_all.jsonl", "timestamp"),
    ("proposals_rejected.jsonl", "timestamp"),
    ("trades.jsonl", "entry_time"),
)

STATE_FILE = "state.json"
KILL_FILE = "kill.txt"
POLL_HEARTBEAT_FILE = "poll_heartbeat.txt"
# Rolling snapshot of the last N workspace thoughts, written by
# ``agent.squad.engine.SquadEngine._write_workspace_snapshot`` on every
# H4 bar close. Read by :func:`live_workspace` for the /v2 dashboard.
WORKSPACE_SNAPSHOT_FILE = "workspace_snapshot.json"

# Replay-cache naming knowledge (mirrors squad_events._CACHE_FILES /
# list_matches). Kept here so cache selection is self-contained without
# importing squad_events, which does heavier work at import time.
CACHE_PREFIX = "g7_replay_cache_"
G7RETRY1_PREFIX = "g7_replay_cache_g7retry1-"
AGGREGATORS: tuple[str, ...] = ("phi41", "arm4")
_REQUIRED_CACHE_FILES = ("proposals_all.jsonl", "proposals_rejected.jsonl",
                         "trades.jsonl")


def _cache_is_valid(path: Path) -> bool:
    """A dir is a playable cache iff it has all three JSONL artifacts."""
    if not path.is_dir():
        return False
    return all((path / f).exists() for f in _REQUIRED_CACHE_FILES)


def _newest_matching(reviews_dir: Path, prefix: str) -> Path | None:
    if not reviews_dir.exists():
        return None
    cands = [c for c in reviews_dir.iterdir()
             if c.is_dir() and c.name.startswith(prefix)
             and _cache_is_valid(c)]
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0]


def select_source_cache(
        reviews_dir: Path,
        *,
        cache: str | None = None,
        aggregator: str | None = None) -> tuple[Path, str]:
    """Resolve the replay cache to feed into the paper loop.

    Precedence (higher wins):
      1. Explicit ``cache`` id or path (from CLI ``--cache`` /
         ``--source-cache`` or ``[paper_loop] cache`` in
         ``platform.toml``).
      2. ``aggregator`` shorthand — resolves to
         ``g7_replay_cache_g7retry1-<aggregator>``. Accepts values in
         :data:`AGGREGATORS` (phi41 is the G7-verdict-bearing arm,
         arm4 the companion).
      3. Newest ``g7_replay_cache_g7retry1-*`` under ``reviews_dir``
         (the default when nothing is specified, so a fresh G7 second
         attempt is auto-selected).
      4. Newest ``g7_replay_cache_*`` under ``reviews_dir`` (legacy
         fallback for older labs).

    Returns ``(path, reason)`` where ``reason`` is a short label safe
    to log at startup so the operator can confirm what's playing
    (e.g. ``"explicit"``, ``"aggregator=phi41"``,
    ``"newest g7retry1"``, ``"newest replay cache"``).

    Raises :class:`FileNotFoundError` when the caller asked for a
    specific cache/aggregator that doesn't exist, or when neither of
    the auto-pick fallbacks finds anything usable. Raises
    :class:`ValueError` for an unknown ``aggregator`` value.
    """
    reviews_dir = Path(reviews_dir)

    if cache:
        p = Path(cache)
        if not p.is_absolute():
            p = reviews_dir / cache
        if not _cache_is_valid(p):
            raise FileNotFoundError(
                f"cache '{cache}' not found or missing required JSONL "
                f"files: {p}")
        return p, "explicit"

    if aggregator:
        if aggregator not in AGGREGATORS:
            raise ValueError(
                f"aggregator must be one of {AGGREGATORS}, "
                f"got {aggregator!r}")
        p = reviews_dir / f"{G7RETRY1_PREFIX}{aggregator}"
        if not _cache_is_valid(p):
            raise FileNotFoundError(
                f"aggregator '{aggregator}' cache not found under "
                f"{reviews_dir} (expected {p.name})")
        return p, f"aggregator={aggregator}"

    p = _newest_matching(reviews_dir, G7RETRY1_PREFIX)
    if p is not None:
        return p, "newest g7retry1"

    p = _newest_matching(reviews_dir, CACHE_PREFIX)
    if p is not None:
        return p, "newest replay cache"

    raise FileNotFoundError(
        f"no {CACHE_PREFIX}* directories found under {reviews_dir}")


def notify_event(row: dict, source_file: str, notifier=None) -> None:
    """TELEGRAM EXTENSION POINT — wired to the DEDICATED squad bot.

    Called for every row the paper loop emits. ``notifier`` is a
    :class:`agent.platform.squad_notify.SquadNotifier` (or None). The
    user decided the squad gets its own bot (separate token + chat), so
    routing lives in ``squad_notify``: closed trades page as GOAL/miss,
    proposals/rejections never page, league tables are throttled. No
    notifier (or an unconfigured one) means this is a silent no-op, and
    the notifier itself fails open — a Telegram outage can never crash
    the loop.
    """
    if notifier is not None:
        notifier.notify_row(row, source_file)


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


def _load_rows(path: Path, ts_field: str) -> list[tuple[datetime, str]]:
    """(timestamp, verbatim-json-line) per row, original order preserved."""
    if not path.exists():
        return []
    out: list[tuple[datetime, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            ts = _parse_ts(row[ts_field]) if row.get(ts_field) else datetime.min
            out.append((ts, line))
    return out


class PaperLoop:
    """Replay a source cache into a live output dir at accelerated pace."""

    def __init__(self, source_cache: Path, out_dir: Path,
                 tick_seconds: float = 2.0, notifier=None) -> None:
        self.source_cache = Path(source_cache)
        self.out_dir = Path(out_dir)
        self.tick_seconds = float(tick_seconds)
        self.notifier = notifier  # squad_notify.SquadNotifier or None
        self.rows: dict[str, list[tuple[datetime, str]]] = {
            fname: _load_rows(self.source_cache / fname, ts_field)
            for fname, ts_field in SOURCE_FILES
        }
        self.cursors: dict[str, int] = {fname: 0 for fname, _ in SOURCE_FILES}

    # -- state -------------------------------------------------------------

    def _state_path(self) -> Path:
        return self.out_dir / STATE_FILE

    def load_state(self) -> None:
        try:
            state = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if state.get("source_cache") != str(self.source_cache):
            return  # different source -> start fresh cursors
        for fname, _ in SOURCE_FILES:
            cur = state.get("cursors", {}).get(fname)
            if isinstance(cur, int) and 0 <= cur <= len(self.rows[fname]):
                self.cursors[fname] = cur

    def save_state(self, last_ts: str | None) -> None:
        payload = {
            "source_cache": str(self.source_cache),
            "cursors": self.cursors,
            "last_event_time": last_ts,
            "saved_at": datetime.now().astimezone().isoformat(),
        }
        tmp = self._state_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(self._state_path())

    def killed(self) -> str | None:
        kill = self.out_dir / KILL_FILE
        if kill.exists():
            try:
                return kill.read_text(encoding="utf-8")[:200].strip() or "killed"
            except OSError:
                return "killed (unreadable)"
        return None

    # -- replay ------------------------------------------------------------

    def _next_file(self) -> str | None:
        """The source file whose next pending row is earliest in time.

        Ties break in SOURCE_FILES order, which matches the order
        ``squad_events.build_timeline`` ingests files, so per-file
        relative order (all that matters for parity) is preserved.
        """
        best: str | None = None
        best_ts: datetime | None = None
        for fname, _ in SOURCE_FILES:
            cur = self.cursors[fname]
            if cur >= len(self.rows[fname]):
                continue
            ts = self.rows[fname][cur][0]
            if best_ts is None or ts < best_ts:
                best, best_ts = fname, ts
        return best

    def remaining(self) -> int:
        return sum(len(self.rows[f]) - self.cursors[f]
                   for f, _ in SOURCE_FILES)

    def prepare_output(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        # Ship workspace_counts.json so the dir is a full artifact set.
        src_ws = self.source_cache / "workspace_counts.json"
        dst_ws = self.out_dir / "workspace_counts.json"
        if src_ws.exists() and not dst_ws.exists():
            dst_ws.write_text(src_ws.read_text(encoding="utf-8"),
                              encoding="utf-8")
        for fname, _ in SOURCE_FILES:
            (self.out_dir / fname).touch()

    def step(self) -> str | None:
        """Append the next row (across files, time-ordered). Returns its
        timestamp string, or None when the replay is exhausted."""
        fname = self._next_file()
        if fname is None:
            return None
        ts, line = self.rows[fname][self.cursors[fname]]
        with (self.out_dir / fname).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self.cursors[fname] += 1
        notify_event(json.loads(line), fname, self.notifier)
        ts_str = ts.isoformat() if ts != datetime.min else None
        self.save_state(ts_str)
        return ts_str or ""

    def run(self, max_steps: int | None = None,
            sleep=time.sleep, log=print) -> str:
        """Drive the replay. Returns why it stopped:
        'done' | 'killed' | 'max_steps'."""
        self.prepare_output()
        self.load_state()
        done = 0
        log(f"[paper-loop] source={self.source_cache}")
        log(f"[paper-loop] output={self.out_dir} "
            f"tick={self.tick_seconds}s remaining={self.remaining()} rows")
        if self.notifier is not None:
            self.notifier.notify_kickoff(
                source_label=self.source_cache.name,
                n_rows=self.remaining(), out_dir=str(self.out_dir))
        while True:
            reason = self.killed()
            if reason:
                log(f"[paper-loop] kill.txt present: {reason} — stopping")
                return self._stop("killed", reason=reason)
            if max_steps is not None and done >= max_steps:
                log(f"[paper-loop] reached max steps ({max_steps})")
                return self._stop("max_steps")
            ts = self.step()
            if ts is None:
                log("[paper-loop] replay exhausted — all rows emitted")
                return self._stop("done")
            done += 1
            if done % 50 == 0:
                log(f"[paper-loop] {done} rows emitted, "
                    f"{self.remaining()} remaining (sim time {ts})")
            if self.tick_seconds > 0:
                sleep(self.tick_seconds)

    def _stop(self, outcome: str, *, reason: str = "") -> str:
        if self.notifier is not None:
            self.notifier.notify_stop(outcome, reason=reason)
        return outcome


def _warmup_progress(state: dict) -> dict | None:
    """Pass through the engine's per-symbol warm-up payload (or None
    for pre-seeding state files)."""
    w = state.get("warmup")
    return w if isinstance(w, dict) and w else None


def _quiet_reason(*, fresh: bool, kill_reason: str | None,
                  state: dict) -> str:
    """One terse, honest line explaining why the pitch looks quiet.

    Priority order (highest wins): dead/stalled > kill file >
    warming up > burn-in > no events & no setups. Takes ``fresh``
    (heartbeat recency) rather than ``running`` because a killed-but-
    alive runner should report the kill, not look dead.
    """
    if not fresh:
        return "runner dead or stalled — no fresh heartbeat"
    if kill_reason is not None:
        return f"halted by kill file: {kill_reason}"
    warmup = _warmup_progress(state) or {}
    warming = [
        f"{sym} {int(w.get('bars_seen', 0))}/{int(w.get('warmup_bars', 0))}"
        for sym, w in sorted(warmup.items())
        if isinstance(w, dict)
        and int(w.get("bars_seen", 0)) <= int(w.get("warmup_bars", 0))
    ]
    if warming:
        return "warming up: " + ", ".join(warming)
    burn_in = max(
        (int(w.get("burn_in_remaining", 0))
         for w in warmup.values() if isinstance(w, dict)),
        default=0,
    )
    if burn_in > 0:
        return (
            f"burn-in: confirming live feed "
            f"({burn_in} bar{'s' if burn_in != 1 else ''} left)"
        )
    return "no scheduled events in window and no fresh setups — evaluating quietly"


def live_status(out_dir: Path, stale_after_s: float = 120.0,
                calendar_cache_path: Path | str | None = None) -> dict:
    """Status payload for /api/v2/live/status (read-only over out_dir).

    The runner (``scripts/run_squad_live.py``) writes ``state.json`` only
    on H4 bar closes, so between bars (~99 % of clock time) that file is
    stale even though the poll loop is healthy. To avoid a false
    ``MARKET STREAM IDLE`` on the /v2 badge, ``poll_heartbeat.txt`` is
    rewritten on every poll iteration and is treated as an equal
    freshness signal here: ``running=True`` iff either the state or the
    poll heartbeat is younger than ``stale_after_s`` (and no kill file
    is present).
    """
    out_dir = Path(out_dir)
    state_path = out_dir / STATE_FILE
    state: dict = {}
    state_age_s: float | None = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state_age_s = time.time() - state_path.stat().st_mtime
        except (OSError, json.JSONDecodeError):
            state = {}
    poll_path = out_dir / POLL_HEARTBEAT_FILE
    poll_age_s: float | None = None
    if poll_path.exists():
        try:
            poll_age_s = time.time() - poll_path.stat().st_mtime
        except OSError:
            poll_age_s = None
    kill = out_dir / KILL_FILE
    kill_reason = None
    if kill.exists():
        try:
            kill_reason = kill.read_text(encoding="utf-8")[:200].strip()
        except OSError:
            kill_reason = "(unreadable)"
    fresh = (
        (state_age_s is not None and state_age_s < stale_after_s)
        or (poll_age_s is not None and poll_age_s < stale_after_s)
    )
    running = fresh and kill_reason is None
    cal_path = (calendar_cache_path if calendar_cache_path is not None
                else NEWS_CACHE_PATH)
    cal_fetched = cache_fetched_at(cal_path)
    cal_age_s = (
        round((datetime.now(tz=timezone.utc) - cal_fetched).total_seconds(), 1)
        if cal_fetched is not None else None
    )
    return {
        "dir": str(out_dir),
        "exists": out_dir.is_dir(),
        "running": running,
        "state_age_seconds": (round(state_age_s, 1)
                              if state_age_s is not None else None),
        # Distinct from state_age_seconds: state.json is only rewritten
        # on H4 bar closes (~every 4 hours), while poll_heartbeat.txt is
        # rewritten on every poll iteration (~45 s cadence). The UI can
        # show both so operators can distinguish "recent bar close" from
        # "recent poll but no bar yet".
        "poll_heartbeat_age_seconds": (round(poll_age_s, 1)
                                       if poll_age_s is not None else None),
        "last_event_time": state.get("last_event_time"),
        "source_cache": state.get("source_cache"),
        # Distinguishes the history-replay paper loop from the
        # live-market squad runtime (scripts/run_squad_live.py). The
        # latter writes state["source"] = "live_market:*" or
        # "cache_replay"; the former leaves it unset / stores
        # source_cache. UI badge swaps on this field.
        "source": state.get("source") or (
            "replay_paper" if state.get("source_cache") else None
        ),
        "cursors": state.get("cursors"),
        "kill": kill_reason,
        # -- additive fields (2026-07-24, I002 "why quiet" work) --
        # Per-symbol warm-up progress from the engine's state payload
        # (None for state files written before warm-up seeding landed).
        "warmup": _warmup_progress(state),
        # Sae roster status (None on pre-Sae state files).
        "sae_enabled": state.get("sae_enabled"),
        # Age of the news-calendar cache; None = no readable cache
        # (dead feed is visible instead of silently absent).
        "calendar_fetched_age_seconds": cal_age_s,
        # One terse line the UI can show under the LIVE badge.
        "quiet_reason": _quiet_reason(
            fresh=fresh, kill_reason=kill_reason, state=state,
        ),
    }


def upcoming_events(
    cache_path: Path | str | None = None,
    *,
    now: datetime | None = None,
    currencies: tuple[str, ...] = ("USD",),
    impacts: tuple[str, ...] = ("High",),
    sae_window_before_min: int = 30,
    sae_window_after_min: int = 60,
) -> dict:
    """Read-only collector for /api/v2/live/upcoming_events.

    High-impact USD events still ahead of ``now`` from the local news
    cache (anchored path per agent.news.calendar; never a network
    call). ``in_sae_window`` marks events whose Sae firing window
    [T - 30 min, T + 60 min] covers ``now``. ``fetched_age_seconds``
    exposes the cache's age so a dead feed is visible on the page;
    note the ForexFactory feed is this-week-only, so an empty list
    late in the week is normal.
    """
    now = now or datetime.now(tz=timezone.utc)
    path = cache_path if cache_path is not None else NEWS_CACHE_PATH
    fetched = cache_fetched_at(path)
    events = filter_events(
        load_calendar(path),
        currencies=currencies,
        impact_levels=impacts,
        after=now,
    )
    rows = []
    # Cache order is whatever the writer stored; the panel wants
    # soonest-first regardless.
    events.sort(key=lambda e: e.time_utc)
    for e in events:
        assert e.time_utc is not None  # filter_events(after=) drops timeless
        window_start = e.time_utc - timedelta(minutes=sae_window_before_min)
        window_end = e.time_utc + timedelta(minutes=sae_window_after_min)
        rows.append({
            "time_utc": e.time_utc.isoformat(),
            "title": e.title,
            "currency": e.currency,
            "impact": e.impact,
            "minutes_to_event": int(
                (e.time_utc - now).total_seconds() // 60
            ),
            "in_sae_window": bool(window_start <= now <= window_end),
        })
    return {
        "exists": fetched is not None,
        "fetched_at": fetched.isoformat() if fetched else None,
        "fetched_age_seconds": (
            round((now - fetched).total_seconds(), 1) if fetched else None
        ),
        "events": rows,
    }


def live_workspace(out_dir: Path) -> dict:
    """Read the latest workspace snapshot for the /v2 LIVE panel.

    Returns a dict shaped like the on-disk file with an extra ``exists``
    boolean so the API can distinguish "snapshot not written yet" from
    "empty workspace". Fails open: on any read or JSON error we return
    ``{"exists": False, "thoughts": []}`` rather than 500 the UI.
    """
    out_dir = Path(out_dir)
    path = out_dir / WORKSPACE_SNAPSHOT_FILE
    if not path.exists():
        return {"exists": False, "thoughts": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"exists": False, "thoughts": []}
    if not isinstance(payload, dict):
        return {"exists": False, "thoughts": []}
    thoughts = payload.get("thoughts")
    if not isinstance(thoughts, list):
        thoughts = []
    return {
        "exists": True,
        "as_of": payload.get("as_of"),
        "tick_id": int(payload.get("tick_id") or 0),
        "thought_count": int(payload.get("thought_count") or 0),
        "thoughts": thoughts,
    }
