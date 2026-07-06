# Runbook — Demo-MT5 Launch & Verification

> **Demo MT5 only — hard rule.** This runbook never involves live broker
> keys. The account is an Exness **demo** ($500+ recommended, see
> [08 — Live Trading & Deployment](08-live-trading-and-deployment.md)
> section 08.3). Nothing here changes strategy behaviour.

> **Branch note.** The VM agent runs the **`main`** branch. The
> **`next-gen`** branch (where this runbook and the progress dashboard
> live) is the next-generation platform line, kept fully separate from
> `main` — it will eventually host heavier trading once research from
> `finance-research-experiments` is validated through the full pipeline.
> Never deploy `next-gen` to the VM until that gate is passed.

Companion docs: [08 — Live Trading & Deployment](08-live-trading-and-deployment.md)
(full setup detail), [runbooks/vmware-windows.md](runbooks/vmware-windows.md)
(per-tab VM operation), [CHECKPOINT.md](CHECKPOINT.md) (what trades and why).

---

## 1. What actually runs

The live entrypoint is **`scripts/run_live.py`** — a thin argparse shell
around `agent/live/signal_loop.py::SignalLoop`. One process per symbol;
each process:

1. Loads the deployment router (`agent/alphas/zone_routing.py`) — the
   symbol's validated cell(s) fix the alpha, timeframe (H4), and risk
   scale. Undeployed symbols **refuse to start** (no fallback alpha).
2. Runs a startup health check (broker connect, parquet cache, kill switch).
3. Polls every ~30 s: candle close → zone alpha → risk guards → sizing →
   order → `PositionMonitor`.

```bash
# The three deployed processes (one terminal / PowerShell tab each):
python scripts/run_live.py --broker mt5 --symbol EURUSD --verbose
python scripts/run_live.py --broker mt5 --symbol GBPUSD --verbose
python scripts/run_live.py --broker mt5 --symbol USDCAD --verbose
```

Deployed cells: EURUSD/H4/all @ 1.0× risk, GBPUSD/H4/all @ 0.5×,
USDCAD/H4/all @ 0.5×, all `zone_d1_against` (H4 zone touch faded against
the D1 trend). Expect roughly 1–2 trades/week/pair — silent days are normal.

## 2. Where it runs

A **VMware Windows VM** with the MT5 terminal installed and logged into
the Exness demo account. The `MetaTrader5` Python package is Windows-only
and talks to the terminal over local IPC, so the terminal must be open in
the same interactive desktop session.

24/5 self-healing (detail in 08.4 — **not NSSM/services**, which cannot
reach MT5's desktop session):

- Windows **Autologon** so a desktop session exists after reboot.
- MT5 shortcut in the **Startup folder**.
- One **Task Scheduler** task per symbol (`AtLogOn`, interactive user)
  running `scripts/watchdog_agent.ps1`, which loops `run_live.py`
  forever (15 s backoff) so crashes self-heal too.

VM code update ritual:

```powershell
git fetch; git reset --hard origin/main; pip install -r requirements.txt
```

## 3. Required .env keys (names only — never commit values)

| Key | Purpose |
|---|---|
| `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | Exness **demo** credentials (required for `--broker mt5`/`exness`) |
| `MT5_PATH` | Optional explicit terminal path (usually auto-detected) |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | Telegram alerts; `TG_CHAT_ID` may be comma-separated for multi-chat fan-out |
| `HEALTHCHECK_URL_<SYMBOL>` (or shared `HEALTHCHECK_URL`) | External dead-man's-switch ping (healthchecks.io); unset = harmless no-op |
| `SYMBOL` | Default symbol when `--symbol` isn't passed |

## 4. Preflight checklist (before starting / restarting the agents)

- [ ] **Tests green** on the branch being deployed:
      `./.venv/bin/python -m pytest` (423 passing as of 2026-07-06).
- [ ] **Kill switch clear.** Two kill files exist:
      per-symbol `{log_root}/{SYMBOL}/kill.txt` (auto-halts, scoped so one
      pair's false alarm can't halt the others) and the global
      `kill_switch` file at the repo root (manual master stop). A leftover
      file makes startup **refuse to run** and log the recorded reason —
      delete it only after confirming it is safe to resume.
- [ ] **Telegram configured** and smoke-tested:
      `python scripts/notify_telegram.py` (exit code = pass/fail).
- [ ] **Heartbeat configured** (optional but recommended):
      `python scripts/ping_healthcheck.py --symbol EURUSD` per symbol.
- [ ] **Risk posture confirmed** (all defaults, no edit needed): 3%
      daily-DD halt, max 1 open position per symbol, **5% portfolio-wide
      open-risk ceiling** across all symbols, post-loss revenge guard on.
- [ ] **Session windows**: Friday-close and Sunday-open no-trade windows
      are on by default (`config/default.yaml`). Note: the news-blackout
      module (`agent/news/`) exists but is **not wired into the live loop
      yet** — high-impact-news blocking is currently the session windows
      plus the wide-H4-stop design, not a calendar feed.
- [ ] **MT5 terminal open and logged in** on the VM before starting agents.
- [ ] **Demo balance $500+** so min-lot H4 stops fit the 0.5–2% risk band
      (on $100 the sizer skips most trades rather than over-risk).

## 5. How to verify it's alive

| Signal | Where | Healthy looks like |
|---|---|---|
| Telegram `Agent ONLINE` | your TG chat | one message per symbol at startup; trade open/close, ladder events, halts also notify |
| Heartbeat | healthchecks.io dashboard | one ping per symbol every 15 min; a freeze pages you in ~35–50 min; emergency halts fire an immediate `/fail` |
| Daily logs | `~/Documents/TradingAgentLogs/{SYMBOL}/{SYMBOL}_YYYY-MM-DD.log` | `Routed cell: ...` at startup, heartbeat lines every 15 min |
| State sidecar | `{log_root}/{SYMBOL}/state.json` | fresh timestamps |
| Vaults | `{log_root}/{SYMBOL}/near_misses` + `/losses` | JSONL + PNG entries accumulating over time |
| Daily digest | `python scripts/daily_summary.py` | per-day trade/rejection summary |
| Weekly review | `python -m agent.reports.rejection_review --days 7` | markdown + CSV rejection digest |

## 6. Local dry-run modes (Mac, no broker, no VM)

```bash
# Paper trading — full pipeline with in-memory fills (safe anywhere):
SYMBOL=EURUSD PYTHONPATH=. .venv/bin/python scripts/run_live.py --broker paper

# Backtest / validation harness (the evidence pipeline):
./.venv/bin/python scripts/run_walk_forward.py       # rolling IS/OOS windows
./.venv/bin/python scripts/run_zone_all_tfs.py       # cell grid
./.venv/bin/python scripts/run_holdout_validation.py # IS/OOS split
```

Paper mode uses the identical router/risk/monitor path as demo — it is the
recommended first step after any code change.

## 7. Progress dashboard

One command regenerates the static progress dashboard (live-agent status,
research-program headlines, validated-vs-sim-only separation):

```bash
./.venv/bin/python scripts/build_dashboard.py && open reports/dashboard.html
```

Add `--skip-tests` to skip the embedded pytest run. The script is stdlib-only
and reads the research repo's artifacts read-only (never imports lab code).

## 8. Emergency stop

```powershell
# Halt ONE symbol (its watchdog loop will hold at the kill check):
echo "manual halt: <reason>" > $HOME\Documents\TradingAgentLogs\EURUSD\kill.txt

# Halt EVERYTHING (global master switch, repo root):
echo "manual halt: <reason>" > kill_switch
```

Delete the file(s) to resume; startup logs the recorded reason either way.
An emergency close (daily-DD breach) also closes open positions and pages
both Telegram and the healthcheck immediately.
