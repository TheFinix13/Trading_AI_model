# VM scripts catalog (demo-MT5 Windows)

Quick reference for the VMware Windows deployment. Repo root below is
`$Repo = $HOME\Documents\GitHub\multi-pair-trading-agent` unless noted.
Python: `& $Repo\.venv\Scripts\python.exe` (or `python` if venv activated).

---

## Daily ops

| Script | What it does | Typical command | When |
|--------|--------------|-----------------|------|
| **`weekly_report.py`** *(new)* | One zip + `REPORT.md`: all symbols, trades, rejections, uptime/kill cascades, balance curve | `cd $Repo; python scripts/weekly_report.py --days 7` | Weekly review; attach zip instead of many logs |
| `daily_summary.py` | Paste-friendly multi-day stdout digest from live logs + vault JSONL | `python scripts/daily_summary.py` | Any time you want a quick health read |
| `compile_review_bundle.py` | Older weekly zip variant (uptime/kill timeline focus) | `python scripts/compile_review_bundle.py --days 7` | Optional; prefer `weekly_report.py` on VM |

---

## Launch / restart

| Script | What it does | Typical command | When |
|--------|--------------|-----------------|------|
| **`run_live.py`** | Live entrypoint → `SignalLoop` (router, MT5/paper) | `python scripts/run_live.py --broker mt5 --symbol EURUSD --verbose` | One process per symbol; manual start |
| **`run_live.py` startup self-recovery** *(behaviour, not a separate script)* | On startup, `_preflight_kill_switch` may **auto-remove a stale per-symbol daily-DD kill** (`kill.txt`) if the reason is a clean daily-DD auto-halt and the file’s **UTC creation date is before today**; master `kill_switch` and manual/same-day kills still **block** startup | (automatic when watchdog/scheduler starts `run_live.py`) | After midnight UTC rollover when yesterday’s DD halt should clear |
| **`watchdog_agent.ps1`** | Infinite loop: run `run_live.py` for one symbol, 15 s backoff on exit | `powershell -File scripts\watchdog_agent.ps1 -Symbol EURUSD` | Task Scheduler at logon (one task per symbol) |
| `deploy_windows.ps1` | Clone/setup: Python, venv, deps, `.env` template | `.\scripts\deploy_windows.ps1` | First-time VM or bare-metal setup (Admin) |

**Code update on VM:** `git fetch; git reset --hard origin/main; pip install -r requirements.txt` then reboot or restart watchdog tasks.

---

## Monitoring / reports

| Script | What it does | Typical command | When |
|--------|--------------|-----------------|------|
| **`ping_healthcheck.py`** *(highlight)* | One-shot dead-man’s-switch ping (healthchecks.io URL from `.env`) | `python scripts/ping_healthcheck.py --symbol EURUSD` | Preflight + after URL changes |
| **`notify_telegram.py`** *(highlight)* | One-shot Telegram smoke test / ad-hoc message / DD-halt format preview | `python scripts/notify_telegram.py` | Preflight before going live |
| `serve_live_dashboard.py` | Read-only local HTTP over log root (`state.json`, logs) | `python scripts/serve_live_dashboard.py` | Optional local glance on VM |
| `serve_platform.py` | Hub + `/v1` live view + `/v2` squad pitch (research artifacts read-only) | Second clone on `next-gen` only — **not** on trading clone | Demo / progress wall |
| `report_target_ladders.py` | Ladder rung reach rates from vault JSONL | `python scripts/report_target_ladders.py --symbol EURUSD` | Ad-hoc ladder QA |
| `resolve_near_misses.py` | Score near-miss vault hypotheticals vs bars | `python scripts/resolve_near_misses.py --symbol EURUSD` | Offline vault maintenance |

**Live signals (no script):** Telegram `Agent ONLINE` + trade events; heartbeat every ~15 min in daily logs; `HEALTHCHECK_URL_*` external freeze detection.

---

## Emergency

| Action / script | What it does | When |
|-----------------|--------------|------|
| Per-symbol `{log_root}/{SYMBOL}/kill.txt` | Auto or manual halt for that pair | After DD halt or manual stop; delete only when safe |
| Repo-root master kill file (`kill_switch`) | Stops **all** symbols | Deliberate full stop |
| `notify_telegram.py --dry-run` | Preview alert text without sending | Verify wording before clearing kills |
| Restart symbol | Stop Task Scheduler task or kill process; clear kill file if appropriate; restart watchdog | After fixing MT5 disconnect or config |

Do **not** use Windows Services/NSSM for the agent — MT5 needs an interactive desktop session (see `08-live-trading-and-deployment.md` §08.4).

---

## Research-only (Mac / offline — not VM trading)

| Script | Purpose |
|--------|---------|
| `smoke_test.py` | Offline v2 pipeline wiring check |
| `download_data.py` | OHLCV cache (yfinance on Mac, MT5 on Windows) |
| `evaluate.py` / `evaluate_alphas.py` | Dev-span alpha scorecards |
| `run_walk_forward.py` / `analyze_walk_forward.py` | Walk-forward research |
| `run_zone_all_tfs.py` / `run_ablation.py` / `run_holdout_validation.py` | Zone grid / ablation / holdout |
| `run_cross_pair_frozen.py` | Frozen cross-pair zone test |
| `build_dashboard.py` | Static `reports/dashboard.html` |
| `run_squad_paper.py` / `notify_squad_telegram.py` | M001 squad paper loop + **separate** squad bot smoke test |

---

*See also:* [RUNBOOK_demo_launch.md](RUNBOOK_demo_launch.md), [08-live-trading-and-deployment.md](08-live-trading-and-deployment.md), [runbooks/vmware-windows.md](runbooks/vmware-windows.md).
