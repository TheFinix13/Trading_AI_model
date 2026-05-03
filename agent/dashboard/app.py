"""FastAPI dashboard: open positions, today's setups, equity curve, kill switch toggle.

Pages:
  /             — overview: balance, recent trades, kill switch, active model.
  /trade/{id}   — full narrative for a single trade (rules-engine reasoning).
  /lessons      — your discretionary trading journal (human_lessons table).
  /lesson/{id}  — one lesson + agent's side-by-side diff.
  /chat         — talk to the agent in natural language (uses local Ollama).

Per-trade explainability is the whole reason the journal was wired into the backtest;
this dashboard is where it surfaces visually."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agent.analysis.explain import explain_journaled_trade
from agent.config import load_config
from agent.conversation.context import ContextBuilder
from agent.journal.db import Journal
from agent.llm.chat import ChatService
from agent.llm.ollama import OllamaUnavailable
from agent.llm.vision import ChartVision

cfg = load_config()
app = FastAPI(title="EURUSD AI Agent Dashboard")

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


def _journal() -> Journal:
    return Journal(cfg.journal_db)


def _chat() -> ChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service


def _vision() -> ChartVision:
    global _chart_vision
    if _chart_vision is None:
        _chart_vision = ChartVision()
    return _chart_vision


def _ctx_builder() -> ContextBuilder:
    global _context_builder
    if _context_builder is None:
        _context_builder = ContextBuilder.from_config()
    return _context_builder


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    journal = _journal()
    trades = journal.all_trades()
    equity = journal.equity_curve()
    open_trades = [t for t in trades if t.get("exit_time") is None]
    closed_all = [t for t in trades if t.get("exit_time") is not None]

    # Force-closed trades pollute headline stats — they never actually hit SL or TP.
    # We count them separately and mark them in the UI but exclude from PF / win-rate.
    real = [t for t in closed_all if t.get("exit_reason") != "end_of_data"]
    n_force_closed = len(closed_all) - len(real)

    win_count = sum(1 for t in real if (t.get("pnl") or 0) > 0)
    win_rate = (win_count / len(real)) if real else 0.0
    total_pnl = sum((t.get("pnl") or 0) for t in real)
    gross_win = sum((t.get("pnl") or 0) for t in real if (t.get("pnl") or 0) > 0)
    gross_loss = abs(sum((t.get("pnl") or 0) for t in real if (t.get("pnl") or 0) < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 0.0

    last_balance = equity[-1]["balance"] if equity else cfg.demo.start_balance
    progress_pct = (last_balance - cfg.demo.start_balance) / max(
        cfg.demo.target_balance - cfg.demo.start_balance, 1
    )

    kill_active = cfg.kill_switch_file.exists()
    active_model = journal.active_model()
    n_lessons = len(journal.all_lessons())

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "open_trades": open_trades,
            "closed_trades": closed_all[-50:][::-1],
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "last_balance": last_balance,
            "demo_start": cfg.demo.start_balance,
            "demo_target": cfg.demo.target_balance,
            "progress_pct": min(max(progress_pct, 0), 1) * 100,
            "kill_active": kill_active,
            "active_model": active_model,
            "mode": cfg.mode,
            "symbol": cfg.symbol,
            "n_trades": len(real),
            "n_force_closed": n_force_closed,
            "display_tz": cfg.display_timezone,
            "n_lessons": n_lessons,
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

@app.get("/lessons", response_class=HTMLResponse)
def lessons_index(request: Request):
    journal = _journal()
    rows = journal.all_lessons()
    rows.reverse()  # newest first
    # Decorate each row with a parsed confluences list for the table.
    for r in rows:
        try:
            r["confluences_parsed"] = json.loads(r.get("confluences_json") or "[]")
        except Exception:
            r["confluences_parsed"] = []
    return templates.TemplateResponse(
        request, "lessons.html",
        {"lessons": rows, "mode": cfg.mode, "n_lessons": len(rows)},
    )


@app.get("/weekly", response_class=HTMLResponse)
def weekly_index(request: Request):
    journal = _journal()
    rows = journal.all_weekly_logs()
    return templates.TemplateResponse(
        request, "weekly.html",
        {"weeks": rows, "mode": cfg.mode, "n_weeks": len(rows)},
    )


@app.get("/weekly/{week_id}", response_class=HTMLResponse)
def weekly_detail(request: Request, week_id: int):
    journal = _journal()
    week = journal.get_weekly_log(week_id)
    if week is None:
        raise HTTPException(status_code=404, detail=f"Weekly log #{week_id} not found")
    # All lessons that came from this week (linked via weekly_log_id).
    rows = journal._conn.execute(
        "SELECT id, trade_date, direction, entry_price, tp_price, pnl_pips "
        "FROM human_lessons WHERE weekly_log_id=? ORDER BY trade_date, id",
        (week_id,)
    ).fetchall()
    lessons = [dict(r) for r in rows]
    return templates.TemplateResponse(
        request, "weekly_detail.html",
        {"week": week, "lessons": lessons, "mode": cfg.mode},
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


# ----- chat -------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: int | None = None


@app.get("/chat", response_class=HTMLResponse)
def chat_index(request: Request, session_id: int | None = None):
    journal = _journal()
    sessions = journal.list_chat_sessions(limit=20)
    history = journal.chat_history(session_id) if session_id else []
    chat_available = False
    chat_model = ""
    vision_available = False
    vision_model = ""
    try:
        c = _chat()
        chat_available = c.is_available()
        chat_model = c.model
    except Exception:
        pass
    try:
        v = _vision()
        vision_available = v.is_available()
        vision_model = v.model or ""
    except Exception:
        pass
    return templates.TemplateResponse(
        request, "chat.html",
        {
            "sessions": sessions,
            "history": history,
            "current_session_id": session_id,
            "mode": cfg.mode,
            "chat_available": chat_available,
            "chat_model": chat_model,
            "vision_available": vision_available,
            "vision_model": vision_model,
        },
    )


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
    if price_context:
        augmented_note = (
            f"{augmented_note}\n\n"
            f"Reference data (from local cache, NOT visible in the image):\n"
            f"{price_context}"
        ).strip()

    try:
        vision = _vision()
        if not vision.is_available():
            raise OllamaUnavailable("no vision model installed")
        reading = vision.analyse(raw, extra_context=augmented_note)
    except OllamaUnavailable as e:
        msg = (
            f"(Vision LLM unavailable: {e})\n\n"
            f"To enable chart analysis run:\n"
            f"  ollama pull llava-phi3   # smaller, faster (~3GB)\n"
            f"  # OR\n"
            f"  ollama pull llama3.2-vision:11b   # higher quality (~8GB)"
        )
        journal.append_chat_message(session_id, "assistant", msg)
        return JSONResponse(
            status_code=503,
            content={"session_id": session_id, "error": str(e), "reply": msg},
        )

    rd = reading.to_dict()
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

    journal.append_chat_message(session_id, "assistant", summary, {"vision": rd})
    return {"session_id": session_id, "reply": summary, "reading": rd}
