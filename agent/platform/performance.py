"""F001 -- Public `/performance` data plane.

Reads closed-trade history from two read-only sources and produces
the derived stats + equity curve the `/performance` page renders:

* **v1 live-demo agent** -- parses ``[TRADE CLOSED]`` / ``[TP HIT]`` /
  ``[SOFT SL]`` / ``[CATASTROPHE SL]`` / ``[MARGIN STOP-OUT]`` /
  ``[EA/EXPERT CLOSE]`` / ``[CLOSED (cause unconfirmed)]`` lines
  from the daily log files under
  ``<log-root>/<PAIR>/<PAIR>_YYYY-MM-DD.log``. Line format is set
  in ``agent/live/trade_events.py::log_trade_closed`` and is
  authoritative:

      [TAG] SYM ticket=N alpha DIR exit=P pnl=+X.XX (+Xp, +X.XXR) cause=Y

* **v2 shadow-paper squad** -- reads the paper-loop's
  ``squad_live/state.json`` (via ``paper_loop.live_status``) for a
  live/idle badge and the ``squad_live/events.jsonl`` file for
  actual closed shadow fills. Only ``close``-type events with a
  concrete ``pnl_pips`` field contribute to stats.

The module is deliberately read-only: neither source is written to,
neither module imports the live agent or the squad runtime. Missing
data files degrade to empty / partial payloads with a
``source_hint`` string that says exactly what was found.

Contract keys (`get_state()`):

* ``days_live``        -- distinct UTC dates on which >=1 trade closed
* ``net_pips``         -- pip sum across every closed trade in scope
* ``worst_dd_pips``    -- deepest peak-to-trough draw-down on the
                          time-ordered cumulative-pip curve
* ``win_rate_pct``     -- fraction of trades with pnl_pips > 0
* ``sharpe_or_null``   -- daily-return Sharpe of the pip-based series,
                          or ``None`` when < ``MIN_DAYS_FOR_SHARPE``
                          daily returns are available (per F001 §6)
* ``sharpe_days_needed`` -- when sharpe is null, how many more daily
                          returns are needed
* ``equity_curve``     -- list of {ts, cum_pips} in time order
* ``per_pair``         -- one row per FX pair present in scope
* ``source_hint``      -- friendly string naming which sources were
                          used ("v1 live", "v2 shadow-paper", or
                          "combined view")
* ``generated_at``     -- UTC ISO8601 timestamp (Z-suffixed)

Missing / unavailable data yields ``equity_curve=[]``,
``per_pair=[]``, and a ``source_hint`` that says "no data yet" --
the F005 empty-state affordance covers that case in the UI.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# F001 §6: Sharpe is only shown when at least this many daily returns
# are available. Below the floor we surface a "need N more days"
# affordance instead of a possibly-misleading number.
MIN_DAYS_FOR_SHARPE = 30

# Symbol dirs under a log root are UPPERCASE 6-letter FX pairs.
_SYM_DIR_RE = re.compile(r"^[A-Z]{6}$")

# Sample line the parser targets (see agent/live/trade_events.py):
#   2026-07-15 09:22:03,547 INFO ... - [TAG] EURUSD ticket=12345
#       zone_d1_against LONG exit=1.09321 pnl=+2.98 (+30.5p, +1.20R)
#       cause=tp
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
_CLOSE_TAGS = (
    "TRADE CLOSED", "TP HIT", "SOFT SL", "CATASTROPHE SL",
    "CLOSED (cause unconfirmed)", "MARGIN STOP-OUT", "EA/EXPERT CLOSE",
)
_TAG_RE = re.compile(
    r"\[(?P<tag>TRADE CLOSED|TP HIT|SOFT SL|CATASTROPHE SL|"
    r"CLOSED \(cause unconfirmed\)|MARGIN STOP-OUT|EA/EXPERT CLOSE)\]\s+"
    r"(?P<symbol>[A-Z]{6})\s+ticket=(?P<ticket>\d+)\s+"
    r"(?P<alpha>\S+)\s+"
    r"(?P<dir>LONG|SHORT)\s+"
    r"exit=(?P<exit>-?\d+\.\d+)\s+"
    r"pnl=(?P<pnl>[+-]?\d+\.\d+)\s+"
    r"\((?P<pips>[+-]?\d+\.?\d*)p,\s*(?P<r>[+-]?\d+\.\d+)R\)\s+"
    r"cause=(?P<cause>\w+)"
)


def _now_iso() -> str:
    """UTC ISO8601 with second precision; Z-suffixed per ledger convention."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat(
        ).replace("+00:00", "Z")


def _parse_v1_daily_log(path: Path) -> list[dict]:
    """Parse a single v1 daily log file into closed-trade dicts.

    Robust to log-line noise (logger name / level prefixes vary): the
    tag regex matches on the ``[TAG] SYM ticket=... cause=Y`` payload,
    so surrounding prefixes are ignored. Malformed lines are silently
    skipped -- the operator's tail -f still sees them, but they don't
    poison the derived stats.
    """
    out: list[dict] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in content.splitlines():
        m = _TAG_RE.search(line)
        if not m:
            continue
        try:
            pips = float(m.group("pips"))
        except ValueError:
            continue
        ts_match = _TS_RE.match(line)
        ts_raw = ts_match.group(1) if ts_match else ""
        # Normalise " " -> "T" so ISO parsers work; keep original if
        # the timestamp is missing (defensive).
        ts_iso = ts_raw.replace(" ", "T") if ts_raw else ""
        out.append({
            "ts": ts_iso,
            "symbol": m.group("symbol"),
            "ticket": int(m.group("ticket")),
            "alpha": m.group("alpha"),
            "direction": m.group("dir").lower(),
            "exit": float(m.group("exit")),
            "pnl": float(m.group("pnl")),
            "pnl_pips": pips,
            "r_multiple": float(m.group("r")),
            "exit_reason": m.group("cause"),
            "tag": m.group("tag"),
            "source": "v1",
        })
    return out


def _collect_v1_trades(log_root: Path) -> list[dict]:
    """Walk every symbol dir under `log_root` for closed-trade lines.

    Iterates ``<log_root>/<PAIR>/<PAIR>_*.log`` files.  Missing root
    yields an empty list without raising.
    """
    trades: list[dict] = []
    if not log_root.is_dir():
        return trades
    for sym_dir in sorted(log_root.iterdir()):
        if not sym_dir.is_dir() or not _SYM_DIR_RE.match(sym_dir.name):
            continue
        for log_file in sorted(sym_dir.glob(f"{sym_dir.name}_*.log")):
            trades.extend(_parse_v1_daily_log(log_file))
    return trades


def _collect_v2_trades(live_dir: Path) -> list[dict]:
    """Parse `squad_live/events.jsonl` for ``close`` events.

    The paper-loop writes one JSON row per event; we pick out closes
    that carry a numeric ``pnl_pips``. Same row schema as the /v2
    ticker consumes, so parity is enforced by the /v2 tests.

    Missing / unreadable file yields an empty list. Malformed JSON
    rows are skipped defensively.
    """
    trades: list[dict] = []
    if not live_dir or not live_dir.is_dir():
        return trades
    events_file = live_dir / "events.jsonl"
    if not events_file.is_file():
        return trades
    try:
        with events_file.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("type") != "close":
                    continue
                pips = row.get("pnl_pips")
                if not isinstance(pips, (int, float)):
                    continue
                symbol = str(row.get("symbol") or "").upper()
                if not _SYM_DIR_RE.match(symbol):
                    continue
                ts = str(row.get("t") or row.get("timestamp") or "")
                trades.append({
                    "ts": ts,
                    "symbol": symbol,
                    "ticket": row.get("ticket"),
                    "alpha": row.get("agent") or "shadow-paper",
                    "direction": str(row.get("dir") or "").lower(),
                    "exit": row.get("exit_price"),
                    "pnl": row.get("pnl"),
                    "pnl_pips": float(pips),
                    "r_multiple": row.get("r"),
                    "exit_reason": row.get("exit_reason"),
                    "tag": "SHADOW-PAPER CLOSE",
                    "source": "v2",
                })
    except OSError:
        return trades
    return trades


def _sort_trades(trades: list[dict]) -> list[dict]:
    """Time-order the merged trade stream. Missing timestamps sort last
    (deterministic — same-key stable sort preserves insertion order)."""
    def key(t: dict):
        ts = t.get("ts") or ""
        # Empty timestamps: sort them AFTER dated ones so cumulative
        # curve isn't distorted.
        return (ts == "", ts)
    return sorted(trades, key=key)


def _equity_curve(trades: list[dict]) -> list[dict]:
    """Cumulative-pip series -- one point per closed trade."""
    curve: list[dict] = []
    cum = 0.0
    for t in trades:
        cum += float(t.get("pnl_pips", 0.0))
        curve.append({
            "ts": t.get("ts") or "",
            "cum_pips": round(cum, 1),
        })
    return curve


def _worst_dd(curve: list[dict]) -> float:
    """Deepest peak-to-trough draw-down (in pips, positive number)."""
    worst = 0.0
    peak = 0.0
    for point in curve:
        v = float(point.get("cum_pips", 0.0))
        peak = max(peak, v)
        worst = max(worst, peak - v)
    return round(worst, 1)


def _daily_returns_pips(trades: list[dict]) -> list[float]:
    """Sum pips per UTC calendar day, return the ordered list of daily
    totals for Sharpe computation."""
    by_day: dict[str, float] = {}
    for t in trades:
        ts = t.get("ts") or ""
        if len(ts) < 10:
            continue
        day = ts[:10]
        by_day[day] = by_day.get(day, 0.0) + float(t.get("pnl_pips", 0.0))
    return [by_day[d] for d in sorted(by_day.keys())]


def _sharpe_or_null(daily_returns: list[float]) -> tuple[float | None, int]:
    """Annualised Sharpe of daily pip returns, or (None, needed) when we
    don't have enough data yet.

    The pip series is unit-consistent (pips per day) so we compute a
    simple mean/std ratio and annualise by sqrt(252) -- crude but
    honest, matches every retail benchmark. Zero-variance series
    returns (0.0, 0)."""
    n = len(daily_returns)
    if n < MIN_DAYS_FOR_SHARPE:
        return None, MIN_DAYS_FOR_SHARPE - n
    mean = sum(daily_returns) / n
    var = sum((x - mean) ** 2 for x in daily_returns) / max(1, n - 1)
    sd = math.sqrt(var)
    if sd == 0.0:
        return 0.0, 0
    return round((mean / sd) * math.sqrt(252), 2), 0


def _per_pair(trades: list[dict]) -> list[dict]:
    """One row per symbol with trades / wins / net / avg / best / worst
    aggregates. Ordered alphabetically for a stable UI render."""
    by_sym: dict[str, list[float]] = {}
    for t in trades:
        sym = t.get("symbol") or ""
        if not _SYM_DIR_RE.match(sym):
            continue
        by_sym.setdefault(sym, []).append(float(t.get("pnl_pips", 0.0)))
    out: list[dict] = []
    for sym in sorted(by_sym.keys()):
        pips = by_sym[sym]
        n = len(pips)
        wins = sum(1 for p in pips if p > 0)
        net = sum(pips)
        best = max(pips) if pips else 0.0
        worst = min(pips) if pips else 0.0
        avg = net / n if n else 0.0
        out.append({
            "symbol": sym,
            "trades": n,
            "wins": wins,
            "net_pips": round(net, 1),
            "avg_pips": round(avg, 2),
            "best_pips": round(best, 1),
            "worst_pips": round(worst, 1),
        })
    return out


def _source_hint(v1_count: int, v2_count: int) -> str:
    """Friendly single-sentence description of which sources contributed.

    UI renders this verbatim so the user knows what they're looking
    at -- prospects should never guess whether the equity curve is
    real fills, shadow fills, or a blend.
    """
    if v1_count and v2_count:
        return (f"combined view: {v1_count} closed trades from the v1 "
                f"live-demo agent + {v2_count} shadow-paper fills from "
                "the v2 squad")
    if v1_count:
        return (f"{v1_count} closed trades from the v1 live-demo agent "
                "(demo account, no real money)")
    if v2_count:
        return (f"{v2_count} shadow-paper fills from the v2 squad "
                "(no orders sent to the broker)")
    return ("no shadow-paper data yet -- the squad is still warming up")


def get_state(log_root: Path | None = None,
              live_dir: Path | None = None) -> dict:
    """Return the /performance payload. Missing paths degrade gracefully.

    ``log_root`` is the v1 log root (defaults to the current session's
    invocation dir, matching serve_platform CLI). ``live_dir`` is the
    v2 paper-loop output dir (contains events.jsonl). Both default to
    None -> empty streams; the source_hint communicates that.
    """
    v1_trades = _collect_v1_trades(log_root) if log_root else []
    v2_trades = _collect_v2_trades(live_dir) if live_dir else []
    merged = _sort_trades(v1_trades + v2_trades)

    curve = _equity_curve(merged)
    net = round(sum(float(t.get("pnl_pips", 0.0)) for t in merged), 1)
    days_live = len({(t.get("ts") or "")[:10] for t in merged
                     if (t.get("ts") or "")[:10]})
    dd = _worst_dd(curve)

    wins = sum(1 for t in merged if float(t.get("pnl_pips", 0.0)) > 0)
    win_rate = (100.0 * wins / len(merged)) if merged else 0.0

    daily = _daily_returns_pips(merged)
    sharpe, sharpe_needed = _sharpe_or_null(daily)

    return {
        "generated_at": _now_iso(),
        "days_live": days_live,
        "net_pips": net,
        "worst_dd_pips": dd,
        "win_rate_pct": round(win_rate, 1),
        "sharpe_or_null": sharpe,
        "sharpe_days_needed": sharpe_needed,
        "trades_total": len(merged),
        "equity_curve": curve,
        "per_pair": _per_pair(merged),
        "source_hint": _source_hint(len(v1_trades), len(v2_trades)),
        "v1_trades_count": len(v1_trades),
        "v2_trades_count": len(v2_trades),
    }
