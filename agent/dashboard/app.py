"""FastAPI dashboard for the EURUSD AI trading agent.

Pages:
  /             — overview: goal progress, my trades vs agent trades side-by-side.
  /chart        — interactive chart with agent panel (Lightweight Charts).
  /trades       — full trade log with My Trades / Agent Trades tabs.
  /trade/{id}   — full narrative for a single agent trade (rules-engine reasoning).
  /lesson/{id}  — one lesson + agent's side-by-side diff.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3 as _sq
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agent.analysis.explain import explain_journaled_trade
from agent.config import load_config
from agent.conversation.context import ContextBuilder
from agent.dashboard.chart_data import load_annotations, load_candles
from agent.journal.db import Journal
from agent.llm.chat import DEFAULT_CHAT_MODEL, ChatService
from agent.llm.cloud_vision import (
    get_best_vision_provider,
    get_vision_provider,
    get_vision_provider_chain,
    get_vision_status,
)
from agent.llm.ollama import OllamaClient, OllamaUnavailable
from agent.llm.vision import ChartVision
from agent.llm.voice import VoiceService

log = logging.getLogger(__name__)

cfg = load_config()
app = FastAPI(title="EURUSD AI Agent Dashboard")

_human_drawings: dict[str, list[dict]] = {}
_ai_thought_logged: set[str] = set()  # dedup: "{session_id}:{timeframe}"

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _to_local(iso_str: str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Convert a UTC ISO timestamp to the configured display TZ.
    Bars/journal stay in UTC; this is purely cosmetic for the dashboard."""
    if not iso_str:
        return "—"
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(cfg.display_timezone)
    except Exception:
        from datetime import timezone
        tz = timezone.utc
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(tz).strftime(fmt)
    except Exception:
        return iso_str[:16]


# Jinja filter so templates can write `{{ t.entry_time | localtime }}`
templates.env.filters["localtime"] = _to_local
templates.env.filters["localtime_short"] = lambda s: _to_local(s, "%m-%d %H:%M")
if (BASE_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ChatService is process-wide so chat history is preserved across requests
# (per session_id stored in the journal).  For multi-user we'd cache per-user.
_chat_service: ChatService | None = None
_context_builder: ContextBuilder | None = None
_chart_vision: ChartVision | None = None
_voice_service: VoiceService | None = None

# Temp dir for generated audio files (served back to the browser)
VOICE_AUDIO_DIR = Path("/tmp/eurusd_voice_audio")
VOICE_AUDIO_DIR.mkdir(parents=True, exist_ok=True)


REALISTIC_BACKTEST_DB = Path(__file__).resolve().parents[2] / "data" / "agent_realistic_apr_may.db"
BACKTEST_V8_DB = Path(__file__).resolve().parents[2] / "data" / "backtest_2024_2026_v8.db"
CHART_SCREENSHOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "chart_screenshots"


def _journal() -> Journal:
    return Journal(cfg.journal_db)


def _load_agent_trades() -> list[dict]:
    """Load trades from the realistic 0.01-lot backtest DB."""
    import sqlite3 as _sq
    db_path = REALISTIC_BACKTEST_DB
    if not db_path.exists():
        return []
    conn = _sq.connect(str(db_path))
    conn.row_factory = _sq.Row
    rows = conn.execute("SELECT * FROM trades ORDER BY entry_time").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _compute_trade_stats(trades: list[dict], pnl_key: str = "pnl", pips_key: str = "pnl_pips") -> dict:
    """Compute summary stats for a list of trades."""
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "net_pnl": 0.0, "net_pips": 0.0,
            "total_pnl_won": 0.0, "total_pnl_lost": 0.0,
            "total_pips_won": 0.0, "total_pips_lost": 0.0,
            "avg_pips": 0.0, "profit_factor": 0.0,
            "best_pnl": 0.0, "worst_pnl": 0.0,
            "best_pips": 0.0, "worst_pips": 0.0,
            "best_date": "—", "worst_date": "—",
        }
    pips_vals = [(t.get(pips_key) or 0) for t in trades]
    pnl_vals = [(t.get(pnl_key) or 0) for t in trades]
    wins = sum(1 for p in pnl_vals if p > 0)
    losses = len(trades) - wins
    gross_win = sum(p for p in pnl_vals if p > 0)
    gross_loss = abs(sum(p for p in pnl_vals if p < 0))
    pips_won = sum(p for p in pips_vals if p > 0)
    pips_lost = sum(p for p in pips_vals if p < 0)

    best_idx = max(range(len(trades)), key=lambda i: pnl_vals[i])
    worst_idx = min(range(len(trades)), key=lambda i: pnl_vals[i])
    best_date = trades[best_idx].get("trade_date") or trades[best_idx].get("entry_time", "")[:10]
    worst_date = trades[worst_idx].get("trade_date") or trades[worst_idx].get("entry_time", "")[:10]

    return {
        "total": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / len(trades) * 100) if trades else 0.0,
        "net_pnl": sum(pnl_vals),
        "net_pips": sum(pips_vals),
        "total_pnl_won": gross_win,
        "total_pnl_lost": -gross_loss,
        "total_pips_won": pips_won,
        "total_pips_lost": pips_lost,
        "avg_pips": sum(pips_vals) / len(trades) if trades else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else 0.0,
        "best_pnl": max(pnl_vals),
        "worst_pnl": min(pnl_vals),
        "best_pips": max(pips_vals),
        "worst_pips": min(pips_vals),
        "best_date": best_date,
        "worst_date": worst_date,
    }


def _get_current_price() -> float:
    """Get latest price from cached H1 candle data."""
    try:
        candles = load_candles("H1", limit=1)
        if candles:
            return candles[-1]["close"]
    except Exception:
        pass
    return 0.0


def _load_v8_trades() -> list[dict]:
    """Load all closed trades from the v8 backtest DB with signal data joined."""
    if not BACKTEST_V8_DB.exists():
        return []
    conn = _sq.connect(str(BACKTEST_V8_DB))
    conn.row_factory = _sq.Row
    rows = conn.execute("""
        SELECT t.*, s.confluences, s.confluence_tfs_json, s.features_json,
               s.ml_score, s.timeframe AS sig_tf, s.detected_at,
               s.decision_reason, s.rr AS sig_rr, s.stop_pips AS sig_stop_pips
        FROM trades t LEFT JOIN signals s ON t.signal_id = s.id
        WHERE t.exit_reason != 'end_of_data'
        ORDER BY t.entry_time DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


_CONFLUENCE_NARRATIVES: dict[str, dict] = {
    "zone": {
        "long": "Price returned to a key demand zone — an area where buyers stepped in before and pushed price sharply higher.",
        "short": "Price returned to a key supply zone — an area where sellers had previously rejected price and drove it lower.",
    },
    "fvg": {
        "long": "A fair value gap (imbalance) was left behind by a strong bullish move, indicating unfilled buy orders below.",
        "short": "A fair value gap (imbalance) was left behind by a strong bearish move, indicating unfilled sell orders above.",
    },
    "bos": {
        "long": "Market structure broke to the upside — a higher high confirmed that buyers are in control.",
        "short": "Market structure broke to the downside — a lower low confirmed that sellers are in control.",
    },
    "fib_382": {
        "default": "Price pulled back to the 38.2% Fibonacci retracement — a shallow pullback typical of strong trends."
    },
    "fib_500": {
        "default": "Price retraced to the 50% level — right in the middle of the prior move, a key equilibrium point."
    },
    "fib_618": {
        "default": "Price reached the 61.8% golden Fibonacci retracement — the deepest pullback that still respects the trend."
    },
    "fib_786": {
        "default": "Price pulled all the way back to the 78.6% Fibonacci level — a deep retracement often seen before final reversals."
    },
    "liquidity_wick": {
        "long": "A long lower wick appeared — price was pushed down to grab stop-losses from trapped sellers, then snapped back up.",
        "short": "A long upper wick appeared — price was pushed up to grab stop-losses from trapped buyers, then snapped back down.",
    },
    "sweep_PDL": {
        "default": "Price swept below the previous day's low, grabbing liquidity from traders who had their stops placed there."
    },
    "sweep_PDH": {
        "default": "Price swept above the previous day's high, triggering buy-stops and trapping breakout traders."
    },
    "sweep_PDM": {
        "default": "Price tested the previous day's mid-point — a key psychological level where orders cluster."
    },
    "sweep_PWL": {
        "default": "Price swept below last week's low — a significant liquidity grab targeting weekly stop-losses."
    },
    "sweep_PWM": {
        "default": "Price tested last week's mid-point, an area that often acts as a magnet for price."
    },
    "sweep_swing_high": {
        "default": "Price swept above a recent swing high, grabbing liquidity from buy-stops placed above the obvious resistance."
    },
    "sweep_swing_low": {
        "default": "Price swept below a recent swing low, grabbing liquidity from sell-stops placed below the obvious support."
    },
    "sweep_equal_highs": {
        "default": "Price ran above equal highs — a liquidity pool where many traders had buy-stops stacked at the same level."
    },
    "sweep_equal_lows": {
        "default": "Price ran below equal lows — a liquidity pool where many traders had sell-stops stacked at the same level."
    },
    "near_PDH": {
        "default": "Price was near the previous day's high — a level the market often retests before deciding direction."
    },
    "near_PDL": {
        "default": "Price was near the previous day's low — a level that frequently acts as a support/resistance pivot."
    },
    "near_PDM": {
        "default": "Price was near the previous day's midpoint — often a magnet level where price consolidates."
    },
    "near_PWL": {
        "default": "Price was near last week's low — a high-impact reference level for weekly traders."
    },
    "near_PWM": {
        "default": "Price was near last week's midpoint — a frequently-tested equilibrium area."
    },
    "session_london": {
        "default": "This occurred during the London session — the highest-volume forex session, where EURUSD makes its biggest moves."
    },
    "session_ny": {
        "default": "This occurred during the New York session — the second-highest volume session and a key reversal window for EURUSD."
    },
    "phase_distribution": {
        "long": "Price was in a distribution phase — smart money was selling at highs before the expected reversal lower.",
        "short": "Price was in a distribution phase — the market was distributing before a move down, aligning with the short bias.",
    },
    "phase_accumulation": {
        "long": "Price was in an accumulation phase — smart money was quietly building long positions before a breakout.",
        "short": "Price was in an accumulation phase — the market was consolidating at lows before the next move.",
    },
    "htf_bias_long": {
        "default": "The higher-timeframe trend (Daily/H4) was bullish, supporting the upside direction."
    },
    "htf_bias_short": {
        "default": "The higher-timeframe trend (Daily/H4) was bearish, supporting the downside direction."
    },
}

_SESSION_LABELS = {
    "session_london": "London", "session_ny": "New York",
    "session_london_ny_overlap": "London/NY Overlap",
}
_SWEEP_LABELS = {
    "sweep_PDL": "Swept Previous Day Low", "sweep_PDH": "Swept Previous Day High",
    "sweep_PDM": "Near Previous Day Mid", "sweep_PWL": "Swept Previous Week Low",
    "sweep_PWM": "Near Previous Week Mid",
    "sweep_swing_high": "Swept Swing High", "sweep_swing_low": "Swept Swing Low",
    "sweep_equal_highs": "Swept Equal Highs", "sweep_equal_lows": "Swept Equal Lows",
}


def generate_trade_narrative(trade: dict) -> str:
    """Convert a trade's technical confluences into a plain English narrative.

    Reads like a human trader explaining the trade to a friend who understands
    basic trading concepts but not the jargon-heavy shorthand."""
    direction = trade.get("direction", "long")
    confluences = []
    try:
        confluences = json.loads(trade.get("confluences") or "[]")
    except (json.JSONDecodeError, TypeError):
        pass

    features = {}
    try:
        features = json.loads(trade.get("features_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    tf_label = (trade.get("sig_tf") or trade.get("mode", "")).replace("backtest_", "")
    entry_price = trade.get("entry_price", 0)
    exit_price = trade.get("exit_price", 0)
    pnl = trade.get("pnl", 0) or 0
    pnl_pips = trade.get("pnl_pips", 0) or 0
    is_win = pnl > 0
    exit_reason = trade.get("exit_reason", "")

    # Opening context
    dir_word = "buying" if direction == "long" else "selling"
    dir_adj = "bullish" if direction == "long" else "bearish"
    parts = []

    # Build the story: what was the market context?
    has_sweep = any(c.startswith("sweep_") for c in confluences)
    has_fvg = "fvg" in confluences
    has_zone = "zone" in confluences
    has_fib = any(c.startswith("fib_") for c in confluences)
    has_session = any(c.startswith("session_") for c in confluences)
    has_phase = any(c.startswith("phase_") for c in confluences)

    # Paragraph 1: the setup story
    story_parts = []
    if has_zone:
        zone_text = _CONFLUENCE_NARRATIVES["zone"].get(direction, "")
        story_parts.append(zone_text)

    sweep_confs = [c for c in confluences if c.startswith("sweep_")]
    for sc in sweep_confs:
        text = _CONFLUENCE_NARRATIVES.get(sc, {}).get("default", "")
        if text:
            story_parts.append(text)

    if has_fvg:
        fvg_text = _CONFLUENCE_NARRATIVES["fvg"].get(direction, "")
        if fvg_text:
            story_parts.append(fvg_text)

    fib_confs = [c for c in confluences if c.startswith("fib_")]
    for fc in fib_confs:
        text = _CONFLUENCE_NARRATIVES.get(fc, {}).get("default", "")
        if text:
            story_parts.append(text)

    if has_session:
        for sc in confluences:
            if sc.startswith("session_"):
                text = _CONFLUENCE_NARRATIVES.get(sc, {}).get("default", "")
                if text:
                    story_parts.append(text)

    phase_confs = [c for c in confluences if c.startswith("phase_")]
    for pc in phase_confs:
        text = _CONFLUENCE_NARRATIVES.get(pc, {}).get(direction, "")
        if not text:
            text = _CONFLUENCE_NARRATIVES.get(pc, {}).get("default", "")
        if text:
            story_parts.append(text)

    near_confs = [c for c in confluences if c.startswith("near_")]
    for nc in near_confs:
        text = _CONFLUENCE_NARRATIVES.get(nc, {}).get("default", "")
        if text:
            story_parts.append(text)

    if "bos" in confluences:
        bos_text = _CONFLUENCE_NARRATIVES["bos"].get(direction, "")
        if bos_text:
            story_parts.append(bos_text)

    if "liquidity_wick" in confluences:
        lw_text = _CONFLUENCE_NARRATIVES["liquidity_wick"].get(direction, "")
        if lw_text:
            story_parts.append(lw_text)

    # Compose into narrative paragraphs
    if story_parts:
        parts.append(f"What happened: On the {tf_label} timeframe, "
                     f"{'several signals lined up for a ' + dir_adj + ' trade. ' if len(story_parts) > 1 else 'a clear ' + dir_adj + ' setup formed. '}"
                     + " ".join(story_parts))
    else:
        parts.append(f"What happened: A {dir_adj} setup was detected on the {tf_label} timeframe "
                     f"with {len(confluences)} confluences.")

    # Paragraph 2: the entry
    parts.append(
        f"We entered {direction.upper()} at {entry_price:.5f} on the {tf_label} chart"
        + (f", with a stop at {trade.get('stop_price', 0):.5f} and target at {trade.get('tp_price', 0):.5f}" if trade.get("stop_price") else "")
        + "."
    )

    rr = trade.get("sig_rr") or features.get("rr", 0) or 0
    if rr:
        parts.append(f"The risk-to-reward was {rr:.1f}:1.")

    # Paragraph 3: the result
    if exit_reason == "tp":
        parts.append(
            f"Result: Price hit our take-profit target — a clean winner. "
            f"Gained {abs(pnl_pips):.1f} pips (${abs(pnl):.2f})."
        )
    elif exit_reason == "sl":
        parts.append(
            f"Result: Price hit our stop-loss. "
            f"Lost {abs(pnl_pips):.1f} pips (${abs(pnl):.2f}). "
            f"The setup was valid but the market didn't follow through this time."
        )
    elif exit_price:
        result_word = "gained" if is_win else "lost"
        parts.append(
            f"Result: Trade was closed ({exit_reason}). "
            f"We {result_word} {abs(pnl_pips):.1f} pips (${abs(pnl):.2f})."
        )

    return " ".join(parts)


def _compute_streak(trades: list[dict]) -> dict:
    """Compute current win/loss streak from most recent trades."""
    if not trades:
        return {"type": "none", "count": 0}
    sorted_trades = sorted(trades, key=lambda t: t.get("entry_time", ""), reverse=True)
    first_pnl = (sorted_trades[0].get("pnl") or 0)
    if first_pnl == 0:
        return {"type": "none", "count": 0}
    streak_type = "win" if first_pnl > 0 else "loss"
    count = 0
    for t in sorted_trades:
        pnl = t.get("pnl") or 0
        if (streak_type == "win" and pnl > 0) or (streak_type == "loss" and pnl <= 0):
            count += 1
        else:
            break
    return {"type": streak_type, "count": count}


def _compute_period_stats(trades: list[dict], start_date: str, end_date: str) -> dict:
    """Filter trades to a date range and compute stats."""
    filtered = [
        t for t in trades
        if start_date <= (t.get("entry_time") or "")[:10] <= end_date
    ]
    stats = _compute_trade_stats(filtered)
    stats["trades_count"] = len(filtered)
    return stats


def _human_trades_filtered(journal: Journal) -> list[dict]:
    """Return only real human trades (not ai_chart_thought or annotation metadata)."""
    all_lessons = journal.all_lessons()
    return [
        l for l in all_lessons
        if l.get("source") not in ("ai_chart_thought", "human_annotation", "agent_annotation_rejected")
        and l.get("outcome") not in ("ai_chart_thought", "annotation")
    ]


def _chat() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service


def _vision(provider_name: str | None = None):
    """Return a vision provider. When ``provider_name`` is None/"auto", uses the
    cached best provider (Claude > Gemini > local Ollama)."""
    global _chart_vision
    if provider_name and provider_name != "auto":
        return get_vision_provider(provider_name)
    if _chart_vision is None:
        _chart_vision = get_best_vision_provider()
    return _chart_vision


def _ctx_builder() -> ContextBuilder:
    global _context_builder
    if _context_builder is None:
        _context_builder = ContextBuilder.from_config()
    return _context_builder


def _voice() -> VoiceService:
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service


def _cleanup_old_audio(max_age_seconds: int = 3600) -> None:
    """Remove audio files older than max_age_seconds from the temp dir."""
    cutoff = time.time() - max_age_seconds
    for f in VOICE_AUDIO_DIR.glob("*.mp3"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Load all v8 backtest trades (with signal data joined)
    all_trades = _load_v8_trades()
    all_stats = _compute_trade_stats(all_trades)

    now = datetime.utcnow()

    # This week stats
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")
    week_trades = [t for t in all_trades if week_start <= (t.get("entry_time") or "")[:10] <= week_end]
    week_stats = _compute_trade_stats(week_trades)

    # This month stats
    month_start = now.strftime("%Y-%m-01")
    month_trades = [t for t in all_trades if month_start <= (t.get("entry_time") or "")[:10] <= week_end]
    month_stats = _compute_trade_stats(month_trades)

    # Monthly P&L for best/worst month
    monthly_pnl: dict[str, float] = {}
    for t in all_trades:
        month_key = (t.get("entry_time") or "")[:7]
        if month_key:
            monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + (t.get("pnl") or 0)
    best_month = max(monthly_pnl.items(), key=lambda x: x[1]) if monthly_pnl else ("—", 0)
    worst_month = min(monthly_pnl.items(), key=lambda x: x[1]) if monthly_pnl else ("—", 0)

    starting_balance = 100.0
    current_balance = starting_balance + all_stats["net_pnl"]
    total_return_pct = all_stats["net_pnl"] / starting_balance * 100

    streak = _compute_streak(all_trades)

    # Recent trades with narratives (top 20)
    recent_trades = []
    for t in all_trades[:20]:
        confs = []
        try:
            confs = json.loads(t.get("confluences") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass
        tf = (t.get("sig_tf") or t.get("mode", "")).replace("backtest_", "")
        narrative = generate_trade_narrative(t)

        hold_duration = ""
        if t.get("entry_time") and t.get("exit_time"):
            try:
                entry_dt = datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00"))
                exit_dt = datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00"))
                delta = exit_dt - entry_dt
                hours = delta.total_seconds() / 3600
                hold_duration = f"{int(delta.total_seconds() / 60)}m" if hours < 1 else \
                                f"{hours:.1f}h" if hours < 24 else f"{delta.days}d {int(hours % 24)}h"
            except Exception:
                pass

        badges = [c for c in confs if not c.startswith("phase_")]

        recent_trades.append({
            **t,
            "tf": tf,
            "narrative": narrative,
            "hold_duration": hold_duration,
            "badges": badges,
            "is_win": (t.get("pnl") or 0) > 0,
            "sqs": round((t.get("ml_score") or 0) * 100, 1),
        })

    # Strategy leaderboard
    strategy_map: dict[str, list[dict]] = {}
    tf_map: dict[str, list[dict]] = {}
    for t in all_trades:
        confs = []
        try:
            confs = json.loads(t.get("confluences") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass
        strategy = _identify_strategy(confs)
        strategy_map.setdefault(strategy, []).append(t)
        tf = (t.get("sig_tf") or t.get("mode", "")).replace("backtest_", "")
        tf_map.setdefault(tf, []).append(t)

    def _build_rankings(group_map: dict[str, list[dict]]) -> list[dict]:
        ranked = []
        for name, trades_list in group_map.items():
            stats = _compute_trade_stats(trades_list)
            ml_scores = [t.get("ml_score") or 0 for t in trades_list if t.get("ml_score")]
            avg_sqs = sum(ml_scores) / len(ml_scores) * 100 if ml_scores else 0
            rr_vals = [t.get("sig_rr") or 0 for t in trades_list if t.get("sig_rr")]
            avg_r = sum(rr_vals) / len(rr_vals) if rr_vals else 0
            status = "hot" if stats["win_rate"] >= 55 and stats["total"] >= 3 else \
                     "cold" if stats["win_rate"] < 45 and stats["total"] >= 3 else \
                     "dormant" if stats["total"] < 3 else "neutral"
            ranked.append({
                "name": name, "sqs": round(avg_sqs, 1),
                "win_rate": round(stats["win_rate"], 1),
                "avg_r": round(avg_r, 2), "trades": stats["total"],
                "net_pnl": round(stats["net_pnl"], 2), "status": status,
            })
        ranked.sort(key=lambda x: x["sqs"], reverse=True)
        return ranked

    strategy_rankings = _build_rankings(strategy_map)
    tf_rankings = _build_rankings(tf_map)

    # Risk status
    today = now.strftime("%Y-%m-%d")
    today_trades = [t for t in all_trades if (t.get("entry_time") or "")[:10] == today]
    today_pnl = sum(t.get("pnl") or 0 for t in today_trades)
    daily_dd_pct = abs(min(today_pnl, 0)) / current_balance * 100 if current_balance > 0 else 0
    dd_limit_pct = cfg.risk.daily_dd_halt_pct * 100

    # Daily P&L for the top bar
    daily_pnl = sum(t.get("pnl") or 0 for t in today_trades)
    daily_pnl_pips = sum(t.get("pnl_pips") or 0 for t in today_trades)

    # Mode label for status badge
    mode_label = "Paper Mode" if cfg.mode == "paper" else \
                 "Active" if cfg.mode == "live" else "Backtest"

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "current_price": _get_current_price(),
            "current_balance": current_balance,
            "daily_pnl": daily_pnl,
            "daily_pnl_pips": daily_pnl_pips,
            "mode_label": mode_label,
            "week_stats": week_stats,
            "month_stats": month_stats,
            "all_stats": all_stats,
            "total_return_pct": total_return_pct,
            "best_month": best_month,
            "worst_month": worst_month,
            "streak": streak,
            "recent_trades": recent_trades,
            "strategy_rankings": strategy_rankings,
            "tf_rankings": tf_rankings,
            "daily_dd_pct": daily_dd_pct,
            "dd_limit_pct": dd_limit_pct,
            "today_pnl": today_pnl,
            "kill_active": cfg.kill_switch_file.exists(),
            "mode": cfg.mode,
            "symbol": cfg.symbol,
            "display_tz": cfg.display_timezone,
        },
    )


@app.get("/api/equity")
def api_equity(mode: str | None = None):
    journal = _journal()
    rows = journal.equity_curve(mode=mode)
    return JSONResponse(rows)


@app.get("/api/trades")
def api_trades(mode: str | None = None):
    journal = _journal()
    rows = journal.all_trades(mode=mode)
    return JSONResponse(rows)


@app.get("/api/performance/summary")
def api_performance_summary():
    """Performance cards data: this week, this month, all-time."""
    trades = _load_v8_trades()
    now = datetime.utcnow()

    # This week (Mon-Sun)
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")
    week_stats = _compute_period_stats(trades, week_start, week_end)

    # This month
    month_start = now.strftime("%Y-%m-01")
    month_stats = _compute_period_stats(trades, month_start, week_end)

    # All time
    all_stats = _compute_trade_stats(trades)

    # Monthly P&L for best/worst month
    monthly_pnl: dict[str, float] = {}
    for t in trades:
        month_key = (t.get("entry_time") or "")[:7]
        if month_key:
            monthly_pnl[month_key] = monthly_pnl.get(month_key, 0) + (t.get("pnl") or 0)
    best_month = max(monthly_pnl.items(), key=lambda x: x[1]) if monthly_pnl else ("—", 0)
    worst_month = min(monthly_pnl.items(), key=lambda x: x[1]) if monthly_pnl else ("—", 0)

    streak = _compute_streak(trades)

    starting_balance = 100.0
    total_return_pct = (all_stats["net_pnl"] / starting_balance * 100) if starting_balance else 0

    return JSONResponse({
        "week": week_stats,
        "month": month_stats,
        "all_time": {**all_stats, "total_return_pct": total_return_pct,
                     "best_month": best_month[0], "best_month_pnl": best_month[1],
                     "worst_month": worst_month[0], "worst_month_pnl": worst_month[1]},
        "streak": streak,
    })


@app.get("/api/rankings/current")
def api_rankings_current():
    """Strategy, timeframe, and session leaderboard from trade data."""
    trades = _load_v8_trades()

    # Strategy ranking by confluence pattern
    strategy_map: dict[str, list[dict]] = {}
    tf_map: dict[str, list[dict]] = {}
    session_map: dict[str, list[dict]] = {}

    for t in trades:
        confs = []
        try:
            confs = json.loads(t.get("confluences") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass

        # Identify primary strategy from confluences
        strategy = _identify_strategy(confs)
        strategy_map.setdefault(strategy, []).append(t)

        # Group by timeframe
        tf = (t.get("sig_tf") or t.get("mode", "")).replace("backtest_", "")
        tf_map.setdefault(tf, []).append(t)

        # Group by session
        for c in confs:
            if c.startswith("session_"):
                label = _SESSION_LABELS.get(c, c.replace("session_", "").title())
                session_map.setdefault(label, []).append(t)

    def _rank_group(group_map: dict[str, list[dict]]) -> list[dict]:
        ranked = []
        for name, group_trades in group_map.items():
            stats = _compute_trade_stats(group_trades)
            ml_scores = [t.get("ml_score") or 0 for t in group_trades if t.get("ml_score")]
            avg_sqs = sum(ml_scores) / len(ml_scores) * 100 if ml_scores else 0
            avg_r = 0
            rr_vals = []
            for gt in group_trades:
                rr = gt.get("sig_rr") or 0
                if rr:
                    rr_vals.append(rr)
            avg_r = sum(rr_vals) / len(rr_vals) if rr_vals else 0
            status = "hot" if stats["win_rate"] >= 55 and stats["total"] >= 3 else \
                     "cold" if stats["win_rate"] < 45 and stats["total"] >= 3 else \
                     "dormant" if stats["total"] < 3 else "neutral"
            ranked.append({
                "name": name,
                "sqs": round(avg_sqs, 1),
                "win_rate": round(stats["win_rate"], 1),
                "avg_r": round(avg_r, 2),
                "trades": stats["total"],
                "net_pnl": round(stats["net_pnl"], 2),
                "net_pips": round(stats["net_pips"], 1),
                "status": status,
            })
        ranked.sort(key=lambda x: x["sqs"], reverse=True)
        return ranked

    return JSONResponse({
        "strategies": _rank_group(strategy_map),
        "timeframes": _rank_group(tf_map),
        "sessions": _rank_group(session_map),
    })


def _identify_strategy(confluences: list[str]) -> str:
    """Identify the primary strategy from a list of confluence tags."""
    has_sweep = any(c.startswith("sweep_") for c in confluences)
    has_fvg = "fvg" in confluences
    has_zone = "zone" in confluences
    has_fib = any(c.startswith("fib_") for c in confluences)
    has_bos = "bos" in confluences
    has_lw = "liquidity_wick" in confluences

    if has_lw or (has_sweep and not has_fvg and not has_bos):
        return "Liquidity Grab Reversal"
    if has_fvg and has_zone:
        return "FVG + Zone Retest"
    if has_bos and (has_fvg or has_sweep):
        return "BOS Continuation"
    if has_fib and has_zone:
        return "Fib Retracement"
    if has_zone:
        return "S/D Zone Retest"
    if has_fvg:
        return "Fair Value Gap"
    if has_bos:
        return "Structure Break"
    return "Mixed Confluence"


@app.get("/api/trades/recent")
def api_trades_recent(limit: int = 20):
    """Recent trades with full narratives."""
    trades = _load_v8_trades()[:limit]
    results = []
    for t in trades:
        confs = []
        try:
            confs = json.loads(t.get("confluences") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass

        narrative = generate_trade_narrative(t)
        tf = (t.get("sig_tf") or t.get("mode", "")).replace("backtest_", "")

        # Compute hold duration
        hold_duration = ""
        if t.get("entry_time") and t.get("exit_time"):
            try:
                entry_dt = datetime.fromisoformat(t["entry_time"].replace("Z", "+00:00"))
                exit_dt = datetime.fromisoformat(t["exit_time"].replace("Z", "+00:00"))
                delta = exit_dt - entry_dt
                hours = delta.total_seconds() / 3600
                if hours < 1:
                    hold_duration = f"{int(delta.total_seconds() / 60)}m"
                elif hours < 24:
                    hold_duration = f"{hours:.1f}h"
                else:
                    hold_duration = f"{delta.days}d {int(hours % 24)}h"
            except Exception:
                pass

        # Build confluence badges
        badges = []
        for c in confs:
            if c.startswith("phase_"):
                continue
            badge_type = "sweep" if c.startswith("sweep_") else \
                         "session" if c.startswith("session_") else \
                         "fib" if c.startswith("fib_") else \
                         "near" if c.startswith("near_") else c
            badges.append({"tag": c, "type": badge_type})

        results.append({
            "id": t.get("id"),
            "date": _to_local(t.get("entry_time")),
            "entry_time": t.get("entry_time"),
            "exit_time": t.get("exit_time"),
            "direction": t.get("direction"),
            "timeframe": tf,
            "result": "WIN" if (t.get("pnl") or 0) > 0 else "LOSS",
            "pnl": round(t.get("pnl") or 0, 2),
            "pnl_pips": round(t.get("pnl_pips") or 0, 1),
            "entry_price": t.get("entry_price"),
            "exit_price": t.get("exit_price"),
            "stop_price": t.get("stop_price"),
            "tp_price": t.get("tp_price"),
            "exit_reason": t.get("exit_reason"),
            "narrative": narrative,
            "confluences": badges,
            "hold_duration": hold_duration,
            "sqs": round((t.get("ml_score") or 0) * 100, 1),
            "rr": round(t.get("sig_rr") or 0, 1),
        })
    return JSONResponse(results)


@app.get("/api/risk/status")
def api_risk_status():
    """Drawdown meter, open positions, kill switch status."""
    trades = _load_v8_trades()
    starting_balance = 100.0
    net_pnl = sum(t.get("pnl") or 0 for t in trades)
    current_balance = starting_balance + net_pnl

    # Daily drawdown: sum of today's losses
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_trades = [t for t in trades if (t.get("entry_time") or "")[:10] == today]
    today_pnl = sum(t.get("pnl") or 0 for t in today_trades)
    daily_dd_pct = abs(min(today_pnl, 0)) / current_balance * 100 if current_balance > 0 else 0
    dd_limit_pct = cfg.risk.daily_dd_halt_pct * 100

    # Open positions (trades without exit_time in raw data)
    open_positions = 0
    if BACKTEST_V8_DB.exists():
        try:
            conn = _sq.connect(str(BACKTEST_V8_DB))
            conn.row_factory = _sq.Row
            open_rows = conn.execute(
                "SELECT * FROM trades WHERE exit_time IS NULL"
            ).fetchall()
            open_positions = len(open_rows)
            conn.close()
        except Exception:
            pass

    return JSONResponse({
        "daily_dd_pct": round(daily_dd_pct, 2),
        "dd_limit_pct": dd_limit_pct,
        "dd_status": "critical" if daily_dd_pct >= dd_limit_pct * 0.8 else
                     "warning" if daily_dd_pct >= dd_limit_pct * 0.5 else "ok",
        "current_balance": round(current_balance, 2),
        "starting_balance": starting_balance,
        "equity": round(current_balance, 2),
        "open_positions": open_positions,
        "max_open_positions": cfg.risk.max_open_positions,
        "kill_switch_active": cfg.kill_switch_file.exists(),
        "today_pnl": round(today_pnl, 2),
        "today_trades": len(today_trades),
    })


@app.get("/api/watchlist")
def api_watchlist():
    """Forming setups and upcoming sessions."""
    from zoneinfo import ZoneInfo

    now = datetime.utcnow()
    items = []

    # Upcoming sessions
    try:
        ny_tz = ZoneInfo("America/New_York")
        london_tz = ZoneInfo("Europe/London")
        ny_now = datetime.now(ny_tz)
        london_now = datetime.now(london_tz)

        sessions = [
            ("London Open", 8, 0, london_tz, london_now),
            ("NY Open", 9, 30, ny_tz, ny_now),
            ("London Close", 16, 30, london_tz, london_now),
            ("NY Close", 17, 0, ny_tz, ny_now),
        ]
        for name, hour, minute, tz, tz_now in sessions:
            session_time = tz_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if session_time < tz_now:
                session_time += timedelta(days=1)
            delta = session_time - tz_now
            hours_until = delta.total_seconds() / 3600
            if hours_until <= 12:
                if hours_until < 1:
                    time_str = f"{int(delta.total_seconds() / 60)}m"
                else:
                    h = int(hours_until)
                    m = int((hours_until - h) * 60)
                    time_str = f"{h}h {m}m" if m else f"{h}h"
                items.append({
                    "type": "session",
                    "title": name,
                    "subtitle": f"in {time_str}",
                    "status": "upcoming",
                })
    except Exception as e:
        log.debug("Watchlist session calc error: %s", e)

    # Zones price is approaching (from chart annotations)
    for tf in ["H1", "M15"]:
        try:
            annotations = load_annotations(tf, limit=200)
            candles = load_candles(tf, limit=1)
            if not candles:
                continue
            current_price = candles[-1]["close"]
            for zone in annotations.get("zones", [])[:6]:
                dist_pips = abs(current_price - (zone["top"] + zone["bottom"]) / 2) * 10000
                if dist_pips < 30:
                    dir_label = "demand" if zone["direction"] == "long" else "supply"
                    items.append({
                        "type": "zone",
                        "title": f"{tf} {dir_label.title()} Zone",
                        "subtitle": f"{zone['bottom']:.5f}–{zone['top']:.5f} ({dist_pips:.0f} pips away)",
                        "status": "approaching" if dist_pips < 15 else "nearby",
                    })
        except Exception as e:
            log.debug("Watchlist zone scan error on %s: %s", tf, e)

    return JSONResponse({"items": items[:10]})


@app.post("/api/kill")
def kill():
    cfg.kill_switch_file.write_text("halt\n")
    return {"kill_active": True}


@app.post("/api/resume")
def resume():
    if cfg.kill_switch_file.exists():
        cfg.kill_switch_file.unlink()
    return {"kill_active": False}


@app.get("/api/health")
def health():
    chat_ok = False
    try:
        chat_ok = _chat().is_available()
    except Exception:
        pass
    return {"ok": True, "mode": cfg.mode, "symbol": cfg.symbol, "llm_available": chat_ok}


@app.get("/trade/{trade_id}", response_class=HTMLResponse)
def trade_detail(request: Request, trade_id: int):
    """Rich, plain-English narrative for one trade — pulled from the journal.

    The page answers "WHY did the bot take this trade?" with a structured breakdown:
      1. Top-line summary (entry/exit/result in NY time + dollars)
      2. Each confluence as a titled paragraph with the actual numbers
      3. Market state at entry (regime / location / MA / session)
      4. Force-closed warning when the trade was incomplete (end_of_data)
      5. Raw feature snapshot for power-users / ML auditing
    """
    journal = _journal()
    row = journal._conn.execute(
        """SELECT t.*, s.confluences, s.confluence_tfs_json,
                  s.features_json, s.ml_score, s.timeframe AS sig_tf,
                  s.detected_at, s.stop_pips AS sig_stop_pips, s.rr AS sig_rr,
                  s.decision_reason, s.entry_confirmation_json
           FROM trades t LEFT JOIN signals s ON t.signal_id = s.id
           WHERE t.id = ?""", (trade_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Trade #{trade_id} not found")
    t = dict(row)

    confluences = json.loads(t.get("confluences") or "[]")
    features = json.loads(t.get("features_json") or "{}")
    confluence_tfs = json.loads(t.get("confluence_tfs_json") or "{}")
    entry_confirmation = json.loads(t.get("entry_confirmation_json") or "null")
    sorted_features = sorted(
        features.items(),
        key=lambda kv: -abs(float(kv[1] or 0)) if isinstance(kv[1], (int, float)) else 0,
    )

    is_winner = (t.get("pnl") or 0) > 0 if t.get("exit_time") else None
    narrative = explain_journaled_trade(
        t, confluences, features,
        display_tz_name=cfg.display_timezone,
        confluence_tfs=confluence_tfs,
        entry_confirmation=entry_confirmation,
    )

    return templates.TemplateResponse(
        request,
        "trade.html",
        {
            "trade": t,
            "confluences": confluences,
            "features": sorted_features,
            "is_winner": is_winner,
            "symbol": cfg.symbol,
            "mode": cfg.mode,
            "narrative": narrative,
            "display_tz": cfg.display_timezone,
        },
    )


# ----- human lessons ----------------------------------------------------------

@app.get("/trades", response_class=HTMLResponse)
def trades_page(request: Request):
    journal = _journal()
    human_trades = _human_trades_filtered(journal)
    human_trades.sort(key=lambda t: t.get("trade_date", ""), reverse=True)
    human_stats = _compute_trade_stats(human_trades, pnl_key="pnl_pips", pips_key="pnl_pips")
    human_stats["net_pnl"] = human_stats["net_pips"] * 0.10

    agent_trades = _load_agent_trades()
    real_agent = [t for t in agent_trades if t.get("exit_reason") != "end_of_data"]
    real_agent.reverse()
    agent_stats = _compute_trade_stats(real_agent)

    return templates.TemplateResponse(
        request, "trades.html",
        {
            "human_trades": human_trades,
            "agent_trades": real_agent,
            "human_stats": human_stats,
            "agent_stats": agent_stats,
            "mode": cfg.mode,
            "display_tz": cfg.display_timezone,
        },
    )


@app.get("/lessons", response_class=HTMLResponse)
def lessons_index(request: Request):
    journal = _journal()
    rows = journal.all_lessons()
    rows.reverse()
    for r in rows:
        try:
            r["confluences_parsed"] = json.loads(r.get("confluences_json") or "[]")
        except Exception:
            r["confluences_parsed"] = []
    return templates.TemplateResponse(
        request, "lessons.html",
        {"lessons": rows, "mode": cfg.mode, "n_lessons": len(rows)},
    )


@app.get("/lesson/{lesson_id}", response_class=HTMLResponse)
def lesson_detail(request: Request, lesson_id: int):
    journal = _journal()
    lesson = journal.get_lesson(lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail=f"Lesson #{lesson_id} not found")
    try:
        lesson["confluences_parsed"] = json.loads(lesson.get("confluences_json") or "[]")
    except Exception:
        lesson["confluences_parsed"] = []
    diffs = journal.disagreements_for_lesson(lesson_id)
    for d in diffs:
        try:
            d["agent_confluences_parsed"] = json.loads(d.get("agent_confluences_json") or "[]")
        except Exception:
            d["agent_confluences_parsed"] = []
    return templates.TemplateResponse(
        request, "lesson.html",
        {"lesson": lesson, "diffs": diffs, "mode": cfg.mode},
    )


# ----- interactive chart ------------------------------------------------------

@app.get("/chart", response_class=HTMLResponse)
def chart_page(request: Request):
    return templates.TemplateResponse(
        request, "chart.html",
        {"mode": cfg.mode, "symbol": cfg.symbol},
    )


@app.get("/api/chart/candles")
def api_chart_candles(timeframe: str = "M15", limit: int = 500):
    if timeframe not in {"M5", "M15", "H1", "H4", "D1"}:
        raise HTTPException(status_code=400, detail=f"unsupported timeframe: {timeframe}")
    limit = min(max(limit, 50), 5000)
    candles = load_candles(timeframe, limit=limit)
    return JSONResponse(candles)


@app.get("/api/chart/annotations")
def api_chart_annotations(timeframe: str = "M15", limit: int = 500):
    if timeframe not in {"M5", "M15", "H1", "H4", "D1"}:
        raise HTTPException(status_code=400, detail=f"unsupported timeframe: {timeframe}")
    limit = min(max(limit, 50), 5000)
    annotations = load_annotations(timeframe, limit=limit)
    _log_ai_chart_thought(timeframe, annotations)
    return JSONResponse(annotations)


def _log_ai_chart_thought(timeframe: str, annotations: dict) -> None:
    """Persist what the agent detected as an 'AI thought' in the journal.

    Only logs once per timeframe per process session to avoid spamming
    on every chart load / refresh.
    """
    session_key = f"proc:{os.getpid()}:{timeframe}"
    if session_key in _ai_thought_logged:
        return
    _ai_thought_logged.add(session_key)

    try:
        journal = _journal()
        zones = annotations.get("zones", [])
        levels = annotations.get("levels", [])
        bos = annotations.get("bos_markers", [])
        fvgs = annotations.get("fvgs", [])

        level_summary = {lv["label"]: lv["price"] for lv in levels}
        thought = {
            "timeframe": timeframe,
            "n_zones": len(zones),
            "n_levels": len(levels),
            "n_bos": len(bos),
            "n_fvgs": len(fvgs),
            "summary_of_levels": level_summary,
        }

        today = datetime.now().strftime("%Y-%m-%d")
        journal._conn.execute(
            """INSERT INTO human_lessons
               (trade_date, symbol, direction, entry_price, outcome, notes, raw_text, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (today, cfg.symbol, "none", 0.0,
             "ai_chart_thought",
             f"AI analysis on {timeframe}: {len(zones)} zones, {len(levels)} levels, "
             f"{len(bos)} BOS, {len(fvgs)} FVGs",
             json.dumps(thought, default=str),
             "ai_chart_thought"),
        )
        journal._conn.commit()
        log.info("Logged AI chart thought for %s: %d zones, %d levels, %d BOS, %d FVGs",
                 timeframe, len(zones), len(levels), len(bos), len(fvgs))
    except Exception as e:
        log.warning("Failed to log AI chart thought: %s", e)


class RefreshDataRequest(BaseModel):
    timeframes: list[str] = ["D1", "H4", "H1", "M15", "M5"]


@app.post("/api/chart/refresh_data")
def api_refresh_data(req: RefreshDataRequest):
    """Re-download price data for the requested timeframes and return status."""
    import subprocess
    import sys

    valid_tfs = {"M1", "M5", "M15", "H1", "H4", "D1"}
    tfs = [tf for tf in req.timeframes if tf in valid_tfs]
    if not tfs:
        raise HTTPException(status_code=400, detail="no valid timeframes")

    try:
        result = subprocess.run(
            [sys.executable, "scripts/download_data.py",
             "--timeframes", *tfs, "--refresh", "--source", "yfinance"],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": "."},
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        ok = result.returncode == 0
        return {
            "ok": ok,
            "timeframes": tfs,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "download timed out (120s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class AgentDeleteRequest(BaseModel):
    type: str
    id: str | None = None
    timeframe: str = "M15"
    reason: str = "user_rejected"
    data: dict | None = None


@app.post("/api/chart/agent_delete")
def api_agent_delete(req: AgentDeleteRequest):
    """Record user's rejection of an agent annotation as a negative training signal."""
    if req.type not in {"zone", "level", "bos", "fvg"}:
        raise HTTPException(status_code=400, detail=f"unsupported annotation type: {req.type}")
    journal = _journal()
    rid = journal.log_agent_rejection(
        annotation_type=req.type,
        timeframe=req.timeframe,
        annotation_id=req.id,
        reason=req.reason,
        annotation_data=req.data,
    )
    log.info("Agent annotation rejected [%s] %s id=%s reason=%s → correction #%d",
             req.timeframe, req.type, req.id, req.reason, rid)
    return {"ok": True, "correction_id": rid}


class HumanDrawRequest(BaseModel):
    timeframe: str
    type: str
    data: dict


class ChartFeedbackRequest(BaseModel):
    event: str  # chart_loaded | timeframe_switch | user_drew | agent_deleted | user_message
    timeframe: str = "M15"
    context: dict | None = None
    message: str | None = None


@app.post("/api/chart/human_draw")
def api_human_draw(req: HumanDrawRequest):
    """Store a human-drawn annotation and log it for future AI reaction."""
    key = req.timeframe
    if key not in _human_drawings:
        _human_drawings[key] = []
    entry = {"type": req.type, "data": req.data}
    _human_drawings[key].append(entry)
    log.info("Human drawing [%s] %s: %s", key, req.type, req.data)
    return {"ok": True, "count": len(_human_drawings[key])}


# ----- chart feedback (agent panel) ------------------------------------------

PANEL_SYSTEM_PROMPT = (
    "You are an experienced EURUSD trader analyzing charts alongside your trading partner. "
    "You have your own analysis and opinions based on the data — you are NOT a yes-man. "
    "When you disagree with your partner's drawings or analysis, say so clearly and explain "
    "why with specific price levels and evidence. When your partner makes a good point, "
    "acknowledge it and update your thinking. Be conversational, direct, and specific. "
    "Never hallucinate — if you're unsure, say so. Reference specific prices, timeframes, "
    "and candle patterns. Keep responses concise (2-4 sentences max). You're equals at "
    "the desk — challenge each other to find the best trades.\n\n"
    "RULES:\n"
    "- Provide your reasoning FIRST, then ask for the user's perspective.\n"
    "- When concepts clash, point to specific evidence: price levels, wick behavior, "
    "body closes, timeframe context.\n"
    "- Ask probing questions when you see something different than your partner.\n"
    "- Accept corrections when the user gives a good reason, but don't roll over without one.\n"
    "- If the user deletes one of your annotations, briefly defend why you placed it "
    "(impulse size, context, retest quality) and ask for their read — but ultimately accept.\n"
    "- Never make up reasons. If the data doesn't support a claim, say 'I'm not sure about that.'\n"
    "- You have access to the user's recent chart analyses. Reference their previously "
    "identified zones and levels when discussing current price action. For example: "
    "'Your demand zone at 1.1720 from yesterday is still in play…'"
)


def _build_past_analyses_context(n: int = 3) -> str:
    """Summarize recent chart analyses for inclusion in the LLM prompt."""
    try:
        journal = _journal()
        analyses = journal.get_latest_analyses(n=n)
    except Exception:
        return ""
    if not analyses:
        return ""
    parts = ["[RECENT CHART ANALYSES]"]
    for a in analyses:
        date = a.get("date", "?")
        tf = a.get("timeframe", "?")
        created = (a.get("created_at") or "")[:16]
        parts.append(f"— {date} {tf} (at {created})")

        levels_raw = a.get("extracted_levels", "[]")
        try:
            levels = json.loads(levels_raw) if isinstance(levels_raw, str) else levels_raw
        except (json.JSONDecodeError, TypeError):
            levels = []
        if isinstance(levels, list):
            for lv in levels[:5]:
                if isinstance(lv, dict):
                    parts.append(
                        f"  Level: {lv.get('label', '?')} @ {lv.get('price', '?')} "
                        f"({lv.get('kind', '?')})"
                    )
                elif isinstance(lv, str):
                    parts.append(f"  Zone: {lv}")

        zones_raw = a.get("extracted_zones", "[]")
        try:
            zones = json.loads(zones_raw) if isinstance(zones_raw, str) else zones_raw
        except (json.JSONDecodeError, TypeError):
            zones = []
        if isinstance(zones, list):
            for z in zones[:4]:
                if isinstance(z, str):
                    parts.append(f"  Zone: {z}")

        narr = a.get("narrative", "")
        if narr:
            parts.append(f"  Narrative: {narr[:200]}")
    parts.append("[/RECENT CHART ANALYSES]")
    return "\n".join(parts)


def _build_chart_context(tf: str) -> str:
    """Assemble a concise context block from current chart annotations."""
    parts = [f"Timeframe: {tf}"]
    try:
        annotations = load_annotations(tf, limit=500)
        n_demand = sum(1 for z in annotations.get("zones", []) if z["direction"] == "long")
        n_supply = sum(1 for z in annotations.get("zones", []) if z["direction"] == "short")
        parts.append(f"Agent zones: {n_demand} demand, {n_supply} supply")
        for z in annotations.get("zones", [])[:4]:
            parts.append(f"  {z['label']}: {z['bottom']:.5f}–{z['top']:.5f}")

        levels = annotations.get("levels", [])
        if levels:
            lv_str = ", ".join(f"{l['label']}={l['price']:.5f}" for l in levels)
            parts.append(f"Daily levels: {lv_str}")

        n_fvgs = len(annotations.get("fvgs", []))
        n_bos = len(annotations.get("bos_markers", []))
        parts.append(f"FVGs: {n_fvgs}, BOS markers: {n_bos}")
    except Exception as e:
        log.debug("Chart context build error: %s", e)

    try:
        candles = load_candles(tf, limit=3)
        if candles:
            last = candles[-1]
            parts.append(
                f"Latest candle: O={last['open']:.5f} H={last['high']:.5f} "
                f"L={last['low']:.5f} C={last['close']:.5f}"
            )
    except Exception:
        pass
    return "\n".join(parts)


def _panel_user_prompt(req: ChartFeedbackRequest, chart_ctx: str) -> str:
    """Build the user prompt for the panel LLM call based on the event type."""
    if req.event == "chart_loaded":
        return (
            f"[CHART]\n{chart_ctx}\n[/CHART]\n\n"
            f"I just opened the {req.timeframe} chart. "
            f"Give me a quick read — where is price, what zones matter, and what's the bias?"
        )
    if req.event == "timeframe_switch":
        return (
            f"[CHART]\n{chart_ctx}\n[/CHART]\n\n"
            f"Switching to {req.timeframe}. What do you see on this timeframe?"
        )
    if req.event == "user_drew":
        drawing = req.context or {}
        data = drawing.get("data", {})
        draw_type = drawing.get("type", "annotation")
        details = json.dumps(data, default=str)

        price_hint = ""
        if data.get("price"):
            price_hint = f" at {data['price']:.5f}"
        elif data.get("top") and data.get("bottom"):
            price_hint = f" spanning {data['bottom']:.5f}–{data['top']:.5f}"

        return (
            f"[CHART]\n{chart_ctx}\n[/CHART]\n\n"
            f"My trading partner just drew a {draw_type}{price_hint} on the {req.timeframe} chart. "
            f"Details: {details}.\n\n"
            f"Compare this with YOUR OWN analysis from the chart data above. "
            f"If it aligns, acknowledge it and add your perspective. "
            f"If it conflicts with your zones, levels, or structure read, say so clearly — "
            f"explain what you see differently with specific prices and evidence, then ask "
            f"a probing question about their reasoning. Keep it 2-4 sentences."
        )
    if req.event == "agent_deleted":
        drawing = req.context or {}
        data = drawing.get("data", {})
        ann_type = drawing.get("type", "annotation")
        details = json.dumps(data, default=str)

        direction = data.get("direction", "")
        price_info = ""
        if data.get("top") and data.get("bottom"):
            pips = abs(float(data["top"]) - float(data["bottom"])) * 10000
            price_info = (
                f" The zone was {data['bottom']:.5f}–{data['top']:.5f} "
                f"({pips:.1f} pips wide)."
            )
        elif data.get("price"):
            price_info = f" The level was at {data['price']:.5f}."

        return (
            f"[CHART]\n{chart_ctx}\n[/CHART]\n\n"
            f"My trading partner just deleted one of my {ann_type} annotations on {req.timeframe}. "
            f"Details: {details}.{price_info}\n\n"
            f"IMPORTANT: Do NOT just say 'okay'. First, explain your reasoning for why you "
            f"placed that annotation — what impulse, retest, structure, or price action justified it. "
            f"Then ask what they see differently in that area. Keep it 2-3 sentences. "
            f"Ultimately accept the deletion, but make your case first."
        )
    # user_message
    return (
        f"[CHART]\n{chart_ctx}\n[/CHART]\n\n"
        f"{req.message or 'What do you see?'}"
    )


def _fallback_reply(req: ChartFeedbackRequest, chart_ctx: str) -> str:
    """Static fallback when Ollama is unavailable."""
    if req.event == "chart_loaded":
        return (
            f"Looking at {req.timeframe}. "
            f"(LLM offline — start Ollama for detailed analysis: "
            f"ollama pull {DEFAULT_CHAT_MODEL})"
        )
    if req.event == "timeframe_switch":
        return f"Switched to {req.timeframe}. (LLM offline for detailed commentary)"
    if req.event == "user_drew":
        return "Drawing noted. (LLM offline — install Ollama for AI feedback)"
    if req.event == "agent_deleted":
        return "Annotation removed — I'll keep that in mind. (LLM offline)"
    if req.event == "user_message":
        return (
            f"(LLM offline — to enable chat run: "
            f"brew install ollama && ollama pull {DEFAULT_CHAT_MODEL})"
        )
    return "(Processing…)"


def _log_chart_interaction(req: ChartFeedbackRequest) -> None:
    """Log drawing/deletion events to human_lessons for learning feedback."""
    try:
        journal = _journal()
        today = datetime.now().strftime("%Y-%m-%d")
        ctx = req.context or {}
        data = ctx.get("data", {})

        if req.event == "user_drew":
            price = data.get("price", 0) or data.get("top", 0) or 0
            journal._conn.execute(
                """INSERT INTO human_lessons
                   (trade_date, symbol, direction, entry_price, outcome, notes, raw_text, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (today, cfg.symbol, "none", float(price),
                 "annotation",
                 f"User drew {ctx.get('type', 'unknown')} on {req.timeframe}",
                 json.dumps(ctx, default=str),
                 "human_annotation"),
            )
            journal._conn.commit()
        elif req.event == "agent_deleted":
            journal._conn.execute(
                """INSERT INTO human_lessons
                   (trade_date, symbol, direction, entry_price, outcome, notes, raw_text, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (today, cfg.symbol, "none", 0.0,
                 "annotation",
                 f"User rejected agent annotation on {req.timeframe}",
                 json.dumps(ctx, default=str),
                 "agent_annotation_rejected"),
            )
            journal._conn.commit()
    except Exception as e:
        log.warning("Failed to log chart interaction: %s", e)


@app.post("/api/chart/feedback")
async def api_chart_feedback(req: ChartFeedbackRequest):
    """Agent commentary for the chart panel — responds to drawing events,
    timeframe switches, chart loads, and direct user messages."""
    chart_ctx = _build_chart_context(req.timeframe)
    past_ctx = _build_past_analyses_context(n=3)
    user_prompt = _panel_user_prompt(req, chart_ctx)
    if past_ctx:
        user_prompt = past_ctx + "\n\n" + user_prompt

    # Generate LLM response
    try:
        client = OllamaClient()
        if not client.is_alive():
            raise OllamaUnavailable("Ollama offline")
        reply = client.chat(
            model=DEFAULT_CHAT_MODEL,
            messages=[
                {"role": "system", "content": PANEL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=300,
        )
    except OllamaUnavailable:
        reply = _fallback_reply(req, chart_ctx)

    # Log drawing interactions for learning
    if req.event in ("user_drew", "agent_deleted"):
        _log_chart_interaction(req)

    # Synthesize voice if TTS is available
    audio_url = None
    try:
        voice = _voice()
        if voice.tts_available() and not reply.startswith("(LLM offline"):
            audio_bytes = await voice.synthesize(reply)
            audio_id = uuid.uuid4().hex[:12]
            audio_path = VOICE_AUDIO_DIR / f"{audio_id}.mp3"
            audio_path.write_bytes(audio_bytes)
            audio_url = f"/api/voice/audio/{audio_id}.mp3"
            _cleanup_old_audio()
    except Exception as e:
        log.debug("Panel TTS synthesis failed: %s", e)

    return {"reply": reply, "audio_url": audio_url}


# ----- chat -------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    journal = _journal()
    if req.session_id is None:
        session_id = journal.create_chat_session(title=req.message[:60])
    else:
        session_id = req.session_id

    try:
        ctx = _ctx_builder().build(req.message)
    except Exception:
        ctx = None
    journal.append_chat_message(session_id, "user", req.message,
                                 {"context": ctx} if ctx else None)
    try:
        chat = _chat()
        if not chat.is_available():
            raise OllamaUnavailable("Ollama daemon offline or model missing")
        reply = chat.ask(req.message, context=ctx)
    except OllamaUnavailable as e:
        reply = (f"(Local LLM unavailable: {e})\n\n"
                 f"To enable chat, run:\n"
                 f"  brew install ollama && brew services start ollama\n"
                 f"  ollama pull {(_chat().model if _chat_service else 'qwen2.5:7b-instruct')}")
    journal.append_chat_message(session_id, "assistant", reply)
    return {"session_id": session_id, "reply": reply}


@app.post("/api/chart_analyze")
async def api_chart_analyze(
    image: UploadFile = File(...),
    note: str = Form(""),
    session_id: int | None = Form(None),
    timeframe: str = Form(""),
    vision_provider: str = Form("auto"),
):
    """Vision pass on an uploaded chart screenshot.

    Workflow:
      1. Receive a PNG/JPEG from the dashboard's chat file-drop input.
      2. Run the vision LLM with the trader's-eye system prompt; get back a
         structured `ChartReading` (timeframe, direction, key levels, narrative).
      3. Persist the user's upload and the assistant's structured response into
         the chat session so it's part of the conversation history.

    The structured reading is what later questions in the same session can
    reference (e.g. "what's the next likely move?" → chat LLM has the prior
    vision narrative in its context window).
    """
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="upload must be an image")
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty file upload")

    journal = _journal()
    title = (note.strip() or f"Chart upload: {image.filename}")[:60]
    if session_id is None:
        session_id = journal.create_chat_session(title=title)

    user_msg = note.strip() or f"[uploaded chart: {image.filename}]"
    journal.append_chat_message(session_id, "user", user_msg, {
        "upload": {"filename": image.filename, "size": len(raw),
                   "content_type": image.content_type},
    })

    # Build a short price-context block so the vision LLM can sanity-check the
    # numbers it reads off the chart against what EURUSD is actually trading at
    # in our data cache. Without this, llava-style models happily report "1.23"
    # on a 1.17xxx chart because they don't know the symbol's real range.
    price_context = ""
    try:
        price_context = _ctx_builder()._latest_price_snapshot() or ""
    except Exception:
        pass

    augmented_note = note.strip()
    if timeframe:
        augmented_note = (
            f"IMPORTANT: The user confirms this chart is on the {timeframe} timeframe. "
            f"Use this as the timeframe in your response.\n\n{augmented_note}"
        ).strip()
    if price_context:
        augmented_note = (
            f"{augmented_note}\n\n"
            f"Reference data (from local cache, NOT visible in the image):\n"
            f"{price_context}"
        ).strip()

    # --- vision analysis with fallback chain ---
    # If a specific provider was requested, try only that one.
    # Otherwise build a chain (Claude → Gemini → Local) and try each until one succeeds.
    reading = None
    vision = None
    last_error: Exception | None = None

    if vision_provider and vision_provider != "auto":
        providers_to_try = []
        p = get_vision_provider(vision_provider)
        if p and p.is_available():
            providers_to_try = [p]
    else:
        providers_to_try = get_vision_provider_chain()

    if not providers_to_try:
        msg = (
            "(No vision provider available)\n\n"
            "To enable chart analysis, either:\n"
            "  • Set GEMINI_API_KEY in .env (free: https://aistudio.google.com/apikey)\n"
            "  • Set ANTHROPIC_API_KEY in .env (https://console.anthropic.com/)\n"
            "  • Run locally: ollama pull llava-phi3"
        )
        journal.append_chat_message(session_id, "assistant", msg)
        return JSONResponse(
            status_code=503,
            content={"session_id": session_id, "error": "no vision provider available", "reply": msg},
        )

    for provider in providers_to_try:
        provider_label = getattr(provider, "provider_name", "local")
        try:
            reading = provider.analyse(raw, extra_context=augmented_note)
            vision = provider
            log.info("Vision analysis succeeded with %s", provider_label)
            break
        except Exception as e:
            last_error = e
            log.warning("Vision provider %s failed, trying next: %s", provider_label, e)

    if reading is None:
        log.exception("All vision providers failed; last error: %s", last_error)
        msg = f"(All vision providers failed — last error: {last_error})"
        journal.append_chat_message(session_id, "assistant", msg)
        return JSONResponse(
            status_code=500,
            content={"session_id": session_id, "error": str(last_error), "reply": msg},
        )

    rd = reading.to_dict()

    # -- Persist screenshot to disk --
    today = datetime.now().strftime("%Y-%m-%d")
    screenshot_rel = None
    try:
        day_dir = CHART_SCREENSHOTS_DIR / today
        day_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now().strftime("%H-%M-%S")
        tf_label = rd.get("timeframe", "unknown").replace("/", "-")
        fname = f"{tf_label}_{ts_str}.png"
        screenshot_path = day_dir / fname
        screenshot_path.write_bytes(raw)
        screenshot_rel = str(screenshot_path.relative_to(CHART_SCREENSHOTS_DIR.parent.parent))
        log.info("Saved chart screenshot to %s", screenshot_path)
    except Exception as e:
        log.warning("Failed to save chart screenshot: %s", e)

    # -- Extract structured data for persistence --
    extracted_levels = json.dumps(rd.get("key_levels", []))
    extracted_zones = json.dumps(rd.get("active_zones", []))
    narrative_text = rd.get("narrative", "")
    trade_idea_text = json.dumps(rd.get("trade_idea", {}))
    session_context = rd.get("session_context", "")

    # -- Save to chart_analyses table --
    analysis_id = None
    try:
        analysis_id = journal.save_chart_analysis(
            date=today,
            timeframe=rd.get("timeframe", "unknown"),
            session=session_context,
            screenshot_path=screenshot_rel,
            analysis_json=json.dumps(rd),
            extracted_levels=extracted_levels,
            extracted_zones=extracted_zones,
            narrative=narrative_text,
            trade_idea=trade_idea_text,
        )
        log.info("Saved chart analysis #%d for %s %s", analysis_id, today, rd.get("timeframe"))
    except Exception as e:
        log.warning("Failed to save chart analysis to DB: %s", e)

    summary_lines = [
        f"**Chart read** (model: `{reading.model}`)",
        f"- Timeframe: `{rd['timeframe']}`",
        f"- Direction bias: `{rd['direction_bias']}`",
        f"- Estimated current price: `{rd['current_price_estimate']}`",
        f"- Session: `{rd['session_context']}`",
    ]
    if rd["key_levels"]:
        summary_lines.append("- Key levels:")
        for lv in rd["key_levels"][:8]:
            summary_lines.append(
                f"  - {lv.get('label','?')} @ {lv.get('price')} ({lv.get('kind','?')})"
            )
    if rd["active_zones"]:
        summary_lines.append("- Active zones: " + "; ".join(rd["active_zones"][:4]))
    if rd["narrative"]:
        summary_lines.append("")
        summary_lines.append(f"> {rd['narrative']}")
    if rd["trade_idea"]:
        ti = rd["trade_idea"]
        summary_lines.append("")
        summary_lines.append(
            f"**Trade idea:** {ti.get('direction','wait')} | entry={ti.get('entry')} "
            f"stop={ti.get('stop')} tp={ti.get('tp')}"
        )
        if ti.get("rationale"):
            summary_lines.append(f"_{ti['rationale']}_")
    summary = "\n".join(summary_lines)

    provider_label = getattr(vision, "provider_name", "local")

    journal.append_chat_message(session_id, "assistant", summary, {"vision": rd})
    return {
        "session_id": session_id,
        "reply": summary,
        "reading": rd,
        "analysis_id": analysis_id,
        "provider": provider_label,
    }


@app.post("/api/chart_analyze_multi")
async def api_chart_analyze_multi(
    request: Request,
    vision_provider: str = Form("auto"),
    note: str = Form(""),
    session_id: int | None = Form(None),
):
    """Multi-timeframe vision analysis: accepts 2-5 chart screenshots and returns
    per-chart analysis plus cross-timeframe confluence data."""
    form = await request.form()
    image_fields = []
    for key in form:
        if key.startswith("image"):
            val = form[key]
            if hasattr(val, "read"):
                image_fields.append(val)
    if len(image_fields) < 2:
        raise HTTPException(status_code=400, detail="upload at least 2 chart images")
    if len(image_fields) > 5:
        raise HTTPException(status_code=400, detail="maximum 5 images allowed")

    images_data: list[bytes] = []
    for img_upload in image_fields:
        raw_bytes = await img_upload.read()
        if not raw_bytes:
            continue
        ct = getattr(img_upload, "content_type", "") or ""
        if ct and not ct.startswith("image/"):
            continue
        images_data.append(raw_bytes)

    if len(images_data) < 2:
        raise HTTPException(status_code=400, detail="need at least 2 valid image files")

    journal = _journal()
    title = (note.strip() or f"Multi-TF analysis ({len(images_data)} charts)")[:60]
    if session_id is None:
        session_id = journal.create_chat_session(title=title)

    user_msg = note.strip() or f"[uploaded {len(images_data)} charts for multi-TF analysis]"
    journal.append_chat_message(session_id, "user", user_msg, {
        "upload": {"n_images": len(images_data), "type": "multi_tf"},
    })

    price_context = ""
    try:
        price_context = _ctx_builder()._latest_price_snapshot() or ""
    except Exception:
        pass

    augmented_note = note.strip()
    if price_context:
        augmented_note = (
            f"{augmented_note}\n\n"
            f"Reference data (from local cache, NOT visible in the images):\n"
            f"{price_context}"
        ).strip()

    # Select provider(s)
    if vision_provider and vision_provider != "auto":
        providers_to_try = []
        p = get_vision_provider(vision_provider)
        if p and p.is_available():
            providers_to_try = [p]
    else:
        providers_to_try = get_vision_provider_chain()

    if not providers_to_try:
        msg = (
            "(No vision provider available for multi-TF analysis)\n\n"
            "Set GEMINI_API_KEY or ANTHROPIC_API_KEY in .env, or run ollama pull llava-phi3"
        )
        journal.append_chat_message(session_id, "assistant", msg)
        return JSONResponse(status_code=503, content={
            "session_id": session_id, "error": "no vision provider", "reply": msg,
        })

    reading = None
    vision = None
    last_error: Exception | None = None

    for provider in providers_to_try:
        provider_label = getattr(provider, "provider_name", "local")
        has_multi = hasattr(provider, "analyse_multi")

        if has_multi:
            try:
                reading = provider.analyse_multi(
                    images_data, extra_context=augmented_note,
                )
                vision = provider
                log.info("Multi-TF analysis succeeded with %s", provider_label)
                break
            except Exception as e:
                last_error = e
                log.warning("Multi-TF provider %s failed: %s", provider_label, e)
        else:
            # Local Ollama fallback: analyse each image separately, combine
            try:
                from agent.llm.vision import MultiTimeframeReading
                charts = []
                for img_bytes in images_data:
                    single = provider.analyse(img_bytes, extra_context=augmented_note)
                    charts.append({
                        "timeframe": single.timeframe,
                        "direction_bias": single.direction_bias,
                        "key_levels": single.key_levels,
                        "zones": single.active_zones,
                        "narrative": single.narrative,
                    })
                # Build a synthetic combined result
                biases = [c["direction_bias"] for c in charts if c["direction_bias"] != "neutral"]
                overall = biases[0] if biases and all(b == biases[0] for b in biases) else "neutral"
                tfs = [c["timeframe"] for c in charts]

                all_levels = {}
                for c in charts:
                    for lv in c.get("key_levels", []):
                        price = lv.get("price")
                        if price is not None:
                            all_levels.setdefault(round(float(price), 4), []).append(c["timeframe"])

                confluences = []
                for price, ctfs in all_levels.items():
                    if len(ctfs) >= 2:
                        confluences.append({
                            "description": f"Level near {price:.4f} appears on {', '.join(ctfs)}",
                            "timeframes": ctfs,
                            "price_range": [price - 0.0005, price + 0.0005],
                            "significance": "high" if len(ctfs) >= 3 else "medium",
                        })

                reading = MultiTimeframeReading(
                    charts=charts,
                    cross_timeframe_confluences=confluences,
                    overall_bias=overall,
                    overall_narrative=f"Analyzed {len(charts)} timeframes ({', '.join(tfs)}). "
                        + ("Bias is consistent across timeframes." if biases and all(b == biases[0] for b in biases)
                           else "Mixed signals across timeframes."),
                    model=f"local:{getattr(provider, 'model', 'ollama')}",
                )
                vision = provider
                log.info("Multi-TF analysis (sequential) succeeded with %s", provider_label)
                break
            except Exception as e:
                last_error = e
                log.warning("Multi-TF sequential provider %s failed: %s", provider_label, e)

    if reading is None:
        log.exception("All vision providers failed for multi-TF; last error: %s", last_error)
        msg = f"(Multi-TF analysis failed — last error: {last_error})"
        journal.append_chat_message(session_id, "assistant", msg)
        return JSONResponse(status_code=500, content={
            "session_id": session_id, "error": str(last_error), "reply": msg,
        })

    rd = reading.to_dict()
    provider_label = getattr(vision, "provider_name", "local")

    summary_lines = [
        f"**Multi-Timeframe Analysis** (model: `{reading.model}`)",
        f"- Charts analyzed: {len(rd['charts'])}",
        f"- Overall bias: `{rd['overall_bias']}`",
    ]
    for chart in rd["charts"]:
        summary_lines.append(
            f"- **{chart.get('timeframe', '?')}**: {chart.get('direction_bias', '?')} bias"
        )
    if rd["cross_timeframe_confluences"]:
        summary_lines.append("")
        summary_lines.append("**Cross-Timeframe Confluences:**")
        for conf in rd["cross_timeframe_confluences"][:5]:
            sig = conf.get("significance", "")
            tfs_str = ", ".join(conf.get("timeframes", []))
            summary_lines.append(f"  - [{sig}] {conf.get('description', '')} ({tfs_str})")
    if rd["overall_narrative"]:
        summary_lines.append("")
        summary_lines.append(f"> {rd['overall_narrative']}")
    if rd["trade_idea"]:
        ti = rd["trade_idea"]
        summary_lines.append("")
        summary_lines.append(
            f"**Trade idea:** {ti.get('direction', 'wait')} | entry={ti.get('entry')} "
            f"stop={ti.get('stop')} tp={ti.get('tp')}"
        )
        if ti.get("rationale"):
            summary_lines.append(f"_{ti['rationale']}_")

    summary = "\n".join(summary_lines)
    journal.append_chat_message(session_id, "assistant", summary, {"multi_tf_vision": rd})

    return {
        "session_id": session_id,
        "reply": summary,
        "reading": rd,
        "provider": provider_label,
    }


# ----- chart analyses API -----------------------------------------------------


@app.get("/api/chart/analyses")
def api_chart_analyses(date: str | None = None, limit: int = 20):
    """Return saved chart analyses, optionally filtered by date.

    Defaults to returning analyses from the last 3 days if no date is specified.
    """
    journal = _journal()
    if date:
        rows = journal.get_chart_analyses(date=date, limit=limit)
    else:
        from datetime import timedelta
        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
        rows = []
        for d in dates:
            rows.extend(journal.get_analyses_for_date(d))
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        rows = rows[:limit]
    for r in rows:
        for field in ("extracted_levels", "extracted_zones", "trade_idea", "analysis_json"):
            val = r.get(field)
            if isinstance(val, str):
                try:
                    r[field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
    return JSONResponse(rows)


@app.get("/api/chart/screenshots/{date_str}/{filename}")
def api_chart_screenshot(date_str: str, filename: str):
    """Serve a saved chart screenshot image."""
    if ".." in date_str or ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="invalid path")
    path = CHART_SCREENSHOTS_DIR / date_str / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(path, media_type="image/png")


# ----- vision status ----------------------------------------------------------


@app.get("/api/vision/status")
def api_vision_status():
    """Check which vision providers are available and which is active."""
    return JSONResponse(get_vision_status())


# ----- voice -----------------------------------------------------------------


class SpeakRequest(BaseModel):
    text: str


@app.post("/api/voice/transcribe")
async def api_voice_transcribe(audio: UploadFile = File(...)):
    """Transcribe uploaded audio (WebM/WAV from browser mic) to text."""
    voice = _voice()
    if not voice.is_available():
        return JSONResponse(
            status_code=503,
            content={
                "error": "Voice STT unavailable — whisper model not loaded yet. "
                         "First call downloads ~150MB model; try again in a moment.",
            },
        )
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")

    ext = "webm"
    if audio.filename:
        ext = audio.filename.rsplit(".", 1)[-1] if "." in audio.filename else "webm"
    elif audio.content_type:
        ext = audio.content_type.split("/")[-1].split(";")[0]

    start = time.time()
    try:
        text = await voice.transcribe(raw, format=ext)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Transcription failed: {e}"})
    duration_ms = int((time.time() - start) * 1000)
    return {"text": text, "duration_ms": duration_ms}


@app.post("/api/voice/speak")
async def api_voice_speak(req: SpeakRequest):
    """Synthesize text to speech. Returns MP3 audio bytes."""
    voice = _voice()
    if not voice.tts_available():
        return JSONResponse(
            status_code=503,
            content={"error": "TTS unavailable — edge-tts not installed"},
        )
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="empty text")

    try:
        audio_bytes = await voice.synthesize(req.text)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"TTS failed: {e}"})

    audio_id = uuid.uuid4().hex[:12]
    audio_path = VOICE_AUDIO_DIR / f"{audio_id}.mp3"
    audio_path.write_bytes(audio_bytes)
    _cleanup_old_audio()
    return FileResponse(audio_path, media_type="audio/mpeg", filename=f"{audio_id}.mp3")


@app.post("/api/voice/chat")
async def api_voice_chat(
    audio: UploadFile = File(...),
    session_id: int | None = Form(None),
):
    """Full voice round-trip: transcribe → LLM chat → synthesize response."""
    voice = _voice()
    journal = _journal()

    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio upload")

    ext = "webm"
    if audio.filename:
        ext = audio.filename.rsplit(".", 1)[-1] if "." in audio.filename else "webm"

    # Step 1: Transcribe
    if not voice.is_available():
        return JSONResponse(
            status_code=503,
            content={"error": "Voice STT unavailable — whisper model not yet loaded"},
        )
    try:
        user_text = await voice.transcribe(raw, format=ext)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Transcription failed: {e}"})

    if not user_text.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "No speech detected in audio", "user_text": ""},
        )

    # Step 2: Chat (same flow as /api/chat)
    if session_id is None:
        session_id = journal.create_chat_session(title=user_text[:60])

    try:
        ctx = _ctx_builder().build(user_text)
    except Exception:
        ctx = None
    journal.append_chat_message(
        session_id, "user", user_text,
        {"context": ctx, "input_mode": "voice"} if ctx else {"input_mode": "voice"},
    )
    try:
        chat = _chat()
        if not chat.is_available():
            raise OllamaUnavailable("Ollama daemon offline or model missing")
        agent_text = chat.ask(user_text, context=ctx)
    except OllamaUnavailable as e:
        agent_text = f"(Local LLM unavailable: {e})"
    journal.append_chat_message(session_id, "assistant", agent_text)

    # Step 3: Synthesize response audio
    audio_url = None
    if voice.tts_available() and not agent_text.startswith("(Local LLM unavailable"):
        try:
            audio_bytes = await voice.synthesize(agent_text)
            audio_id = uuid.uuid4().hex[:12]
            audio_path = VOICE_AUDIO_DIR / f"{audio_id}.mp3"
            audio_path.write_bytes(audio_bytes)
            audio_url = f"/api/voice/audio/{audio_id}.mp3"
            _cleanup_old_audio()
        except Exception as e:
            log.warning("TTS synthesis failed: %s", e)

    return {
        "session_id": session_id,
        "user_text": user_text,
        "agent_text": agent_text,
        "audio_url": audio_url,
    }


@app.get("/api/voice/audio/{filename}")
async def api_voice_audio(filename: str):
    """Serve a previously-generated audio file."""
    if not filename.endswith(".mp3") or "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    path = VOICE_AUDIO_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio file not found or expired")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/api/voice/status")
def api_voice_status():
    """Check voice service readiness."""
    voice = _voice()
    return {
        "stt_available": voice.is_available(),
        "tts_available": voice.tts_available(),
        "whisper_model": voice._whisper_model_size,
        "tts_voice": voice._tts_voice,
    }
