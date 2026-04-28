"""FastAPI dashboard: open positions, today's setups, equity curve, kill switch toggle.

Two pages:
  /            — overview: balance, recent trades, kill switch, active model.
  /trade/{id}  — full narrative for a single trade: confluences in plain English,
                  feature snapshot at entry, MAE/MFE, outcome.

Per-trade explainability is the whole reason the journal was wired into the backtest;
this page is where it surfaces visually."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agent.analysis.explain import explain_journaled_trade
from agent.config import load_config
from agent.journal.db import Journal

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


def _journal() -> Journal:
    return Journal(cfg.journal_db)


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
    return {"ok": True, "mode": cfg.mode, "symbol": cfg.symbol}


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
