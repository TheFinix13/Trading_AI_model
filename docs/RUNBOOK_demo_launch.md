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
| Heartbeat | healthchecks.io dashboard | one success ping per symbol every 15 min; intentional halts annotate the ping (check stays UP); a genuine freeze pages you in ~35 min if grace=15 min |
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

## 7. Progress dashboard (static snapshot)

One command regenerates the static progress dashboard (live-agent status,
research-program headlines, validated-vs-sim-only separation):

```bash
./.venv/bin/python scripts/build_dashboard.py && open reports/dashboard.html
```

Add `--skip-tests` to skip the embedded pytest run. The script is stdlib-only
and reads the research repo's artifacts read-only (never imports lab code).

## 7b. Live platform web UI (v1 live view + v2 squad pitch)

`scripts/serve_platform.py` serves a real-time web UI — stdlib only, no
new dependencies, strictly READ-ONLY (it cannot affect trading):

* `/v1` — the running zones agent, per symbol: aliveness, open positions,
  day PnL, guards, kill switches, and a decision feed of every signal
  evaluated / blocked / traded. Auto-refreshes every 10 s.
* `/v2` — the M001 squad replayed as a football match (passes =
  proposals, tackles = aggregator rejections, Sentinel wall, goals =
  winning trades). Sim-only evidence; reads the research repo's replay
  artifact files, never its code.

**On the VM** (run from a SECOND clone on `next-gen` — never the trading
clone, which stays on `main`):

```powershell
# One-time: second clone next to the trading clone
git clone https://github.com/TheFinix13/Trading_AI_model.git C:\TradingAgent-platform
cd C:\TradingAgent-platform
git checkout next-gen

# Serve (reads the same log root the main agents write):
python scripts\serve_platform.py --log-root $HOME\Documents\TradingAgentLogs --host 0.0.0.0 --port 8787
```

Then browse `http://<VM-IP>:8787` from the Mac (find the VM IP with
`ipconfig`; VMware NAT/bridged both work). The v2 page needs the research
repo cloned next to the platform clone (`--research-reviews` overrides the
path); without it, v2 simply lists no matches — v1 is unaffected.

**On the Mac** the defaults work as-is:

```bash
./.venv/bin/python scripts/serve_platform.py --port 8787
```

`scripts/serve_live_dashboard.py` remains as the v1-only variant.

### 7b.1 Config file, health endpoint, auth

The server (and the paper loop below) reads an optional **`platform.toml`**
at the repo root — copy `platform.toml.example` and set `log_root`,
`research_reviews`, `live_dir`, `host`/`port`, `auth_token`. CLI flags
always override the file. The file is gitignored (machine-local).

**Health endpoint:** `GET /healthz` returns
`{"status":"ok","version":...,"uptime_seconds":...}` with no auth —
point a healthchecks.io HTTP check (or any uptime monitor) at
`http://<host>:8787/healthz` and alert on non-200.

**Auth:** binding non-localhost without a token prints a warning and
leaves the dashboards open to the network. Set `--auth-token <secret>`
(or `auth_token` in platform.toml); then every route except `/healthz`
requires the token. First visit uses `http://<host>:8787/v2?token=<secret>`
— that plants a session cookie so subsequent page fetches work without
the query string. Scripted access can send `Authorization: Bearer <secret>`.
On `127.0.0.1` binds the token is ignored (local browsing stays open).

### 7b.2 Squad paper loop (shadow-only STUB stream for /v2 LIVE mode)

`scripts/run_squad_paper.py` replays an existing M001 replay cache into
`<log_root>/squad_live/` in accelerated wall-clock time, in the same
three-JSONL schema — this feeds the `/v2` page's **LIVE** source option
via `/api/v2/live/*`. It is shadow-only: it never places broker orders
(it only copies JSON rows between files) and it exists to prove the live
plumbing before the validated squad graduates in.

```bash
# Mac (sibling research checkout auto-detected):
./.venv/bin/python scripts/run_squad_paper.py \
    --source-cache g7_replay_cache_phi5-arm4-post-kunigami --tick-seconds 2
```

Controls: `--max-steps N` stops after N rows; `--reset` wipes the output
and restarts the replay; Ctrl-C (or a `kill.txt` dropped in the output
dir) stops it, and a restart resumes from `state.json`:

```bash
echo "pause for review" > ~/Documents/TradingAgentLogs/squad_live/kill.txt
```

### 7b.3 Installing the platform server as a Windows service

Unlike the trading agents, the platform server does NOT need MT5's
desktop session, so both service approaches work. Run it from the
**platform clone** (`C:\TradingAgent-platform`, `next-gen`), never the
trading clone.

**Option A — Task Scheduler (no extra software):**

```powershell
$action = New-ScheduledTaskAction -Execute "C:\TradingAgent-platform\.venv\Scripts\python.exe" `
  -Argument "scripts\serve_platform.py --host 0.0.0.0 --port 8787 --auth-token <secret>" `
  -WorkingDirectory "C:\TradingAgent-platform"
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "PlatformWebUI" -Action $action -Trigger $trigger `
  -RunLevel Limited -Description "Read-only trading platform web UI (next-gen)"
Start-ScheduledTask -TaskName "PlatformWebUI"
```

(`-AtStartup` works here because the server needs no desktop session;
the trading agents keep their `AtLogOn` + watchdog setup from section 2.)

**Option B — NSSM (auto-restart on crash):**

```powershell
nssm install PlatformWebUI "C:\TradingAgent-platform\.venv\Scripts\python.exe" `
  "scripts\serve_platform.py --host 0.0.0.0 --port 8787 --auth-token <secret>"
nssm set PlatformWebUI AppDirectory "C:\TradingAgent-platform"
nssm set PlatformWebUI AppStdout "C:\TradingAgent-platform\platform_service.log"
nssm set PlatformWebUI AppStderr "C:\TradingAgent-platform\platform_service.log"
nssm start PlatformWebUI
```

Verify either way: `curl http://localhost:8787/healthz` on the VM, then
`http://<VM-IP>:8787/v1?token=<secret>` from the Mac. Prefer
`platform.toml` on the VM for the paths/token so the service command
line stays short.

**Telegram note:** squad/paper-loop events page through a DEDICATED
squad bot (decided 2026-07-14 — separate token + chat so match
commentary never mixes with the v1 trading bot). Setup walkthrough in
section 7b.4 below; routing lives in `agent/platform/squad_notify.py`
and is a silent no-op until the bot is configured.

### 7b.4 Squad Telegram bot (dedicated v2 bot — create + wire + test)

The squad gets its **own** bot and chat. The v1 keys (`TG_BOT_TOKEN` /
`TG_CHAT_ID`) are deliberately ignored by the squad notifier — never
reuse them here.

**1. Create the bot (BotFather):**

1. In Telegram, message **@BotFather** → `/newbot`.
2. Pick a display name (e.g. `Blue Lock Squad`) and a unique username
   ending in `bot` (e.g. `bluelock_squad_bot`).
3. BotFather replies with the **bot token** (`123456:ABC-...`) — copy it,
   never commit it.

**2. Get the chat id:**

1. Open a chat with the new bot and send it any message (this is
   required — bots cannot message you first). For a group, add the bot
   to the group and post a message there.
2. Fetch the id (replace `<TOKEN>`):

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
```

   The `"chat":{"id":...}` field is your chat id (group ids are
   negative, e.g. `-1001234567890`). Empty `result`? Send the bot
   another message and re-run.

**3. Configure (VM or Mac).** Either fill `platform.toml` at the repo
root (wins over env, per key):

```toml
[telegram]
bot_token = "123456:ABC-..."
chat_id = "-1001234567890"   # comma-separated for multi-chat fan-out
summary_every = 10           # closed trades between league-table posts
```

or set the env vars in `.env` (see `.env.example`):
`SQUAD_TELEGRAM_BOT_TOKEN` and `SQUAD_TELEGRAM_CHAT_ID`.

**4. One-shot test** (exit code 0 = confirmed send, 1 = unconfigured or
rejected — scriptable like `scripts/notify_telegram.py` for v1):

```bash
./.venv/bin/python scripts/notify_squad_telegram.py
```

A sample `GOAL — Isagi #11` message lands in the squad chat. From then
on `scripts/run_squad_paper.py` pages automatically: kickoff at start,
GOAL/miss per closed trade (player, symbol, pips, TQS, R), a league
table every `summary_every` closes, and full-time/halt + final table at
stop. Proposals and rejections never page. Unconfigured or broken
Telegram can never crash the loop (fail-open, same as v1); pass
`--no-telegram` to silence a configured bot for one run.

### 7b.5 Watch all 7 v1 squad players on the pitch (paper observation)

Paper mode replays a G7 second-attempt (`g7retry1`) cache with all 7 v1
players active — Phase Y Barou v1.3 weapon, dispersion-primitives
round 2, Nagi provenance borrow — into the `/v2` LIVE stream. It is
**shadow-only paper observation**: the loop only copies JSON rows
between files, never talks to a broker, never places orders. The v1
zones agent on `main` is completely unaffected — it does not share code,
processes, log root, or branch with the platform clone.

By default (no flags), the loop picks the newest
`g7_replay_cache_g7retry1-*` under the research reviews dir. Pin a
specific aggregator arm with `--aggregator {phi41,arm4}` — phi41 is
verdict-bearing, arm4 the companion; either is fine for observation.
An explicit `--cache <id>` overrides both.

**On the VM** (both clones already exist per §7b — the trading clone at
`C:\TradingAgent` on `main` is untouched; the platform clone at
`C:\TradingAgent-platform` on `next-gen` gets the paper loop):

```powershell
cd C:\TradingAgent-platform
git fetch && git checkout next-gen && git reset --hard origin/next-gen

# Terminal 1 — paper loop (fresh g7retry1 cache, phi41 verdict arm).
# Startup logs the resolved cache clearly, e.g.:
#   [paper-loop] source cache: g7_replay_cache_g7retry1-phi41 (aggregator=phi41)
.venv\Scripts\python scripts\run_squad_paper.py --aggregator phi41
# or --cache g7_replay_cache_g7retry1-arm4  to pick the companion arm
# or --cache g7_replay_cache_g7retry1-arm4 --reset  to restart from row 0

# Terminal 2 — platform server (skip if already installed as a service).
.venv\Scripts\python scripts\serve_platform.py --host 0.0.0.0 --port 8787 --auth-token <secret>
```

Browse `http://<VM-IP>:8787/?token=<secret>` from the Mac, hit `/v2`,
switch the source dropdown to **LIVE**. All 8 pitch positions render
(the 7 v1 players + Kunigami retained as the Sentinel R5 defender);
proposal / block / open / close events tick through as the loop
appends rows. The LIVE badge, ticker, league table, and player-profile
cards all populate from the same `/api/v2/live/*` endpoints — nothing
special about "live" vs "replay" on the client side.

**Kill switch (paper mode is a `kill.txt` in the live dir, NOT the v1
`kill_switch` at the repo root):**

```powershell
# stops the paper loop at the next tick, state.json is preserved so a
# restart resumes from where you paused
"pause for review" | Out-File -Encoding ascii $HOME\Documents\TradingAgentLogs\squad_live\kill.txt
```

Delete that file (and restart `run_squad_paper.py`) to resume, or pass
`--reset` on the next start to wipe `state.json` + JSONLs and replay
from the top. The v1 trading agent's kill switches
(`{log_root}/{SYMBOL}/kill.txt`, global `kill_switch`) are completely
independent — nothing here touches them.

Config knobs (all optional, CLI always wins) in `platform.toml`:

```toml
[paper_loop]
aggregator = "phi41"                             # or "arm4"
# cache = "g7_replay_cache_g7retry1-arm4"        # explicit id / path
```

### 7b.6 Run the squad on the live market (paper)

This is the milestone that makes the v2 Blue Lock squad react to
**today's** H4 bars instead of replaying a banked cache. Agent logic
is a **ported v1 (unvalidated port)** under `agent/squad/` —
reimplemented from the research sim at commit `e084c5b`, never
imported. G7 gate was FAIL 3/7; this runtime is for paper observation,
not live trading. **Shadow-only: never places broker orders.** The v1
zones agent on `main` is completely unaffected.

Hard guarantees (same family as §7b.5):

* MT5 is used **read-only** for bars when `--feed mt5` (VM). Dev Macs
  use `--feed cache` (parquet replay, accelerated).
* Events append to the same three-JSONL schema under
  `<log_root>/squad_live/` so `/v2` LIVE + the squad Telegram bot work
  unchanged. `/api/v2/live/status` exposes a `source` field
  (`live_market:mt5` / `cache_replay` / `replay_paper`) so the badge
  can distinguish this runtime from the §7b.5 history-replay loop.
* `kill.txt` in the live dir stops at the next poll; `state.json`
  resumes open shadow positions + per-symbol cursor; daily
  `heartbeat_YYYYMMDD.log` lines land in the same dir.
* Default aggregator arm is sealed phi41; `--aggregator arm4` enables
  multi-position. `--parity-mode` disables Barou v1.3 so cache-parity
  work matches sealed v1.

**Parity honesty (as of the first port):** against the banked
`g7retry1-phi41` early-slice proposals (2015-02-17→2015-03-17), the
ported engine matched **97%** of reference `(timestamp, symbol,
agent_id, direction)` keys and **97%** of those also hit conviction
within ±0.05. Not byte-identical (float paths, Phase Y Barou default,
shadow-ledger / Wild-Card Kunigami gate not ported). Do not claim
G7-validated behaviour.

**On the VM** (platform clone on `next-gen`):

```powershell
cd C:\TradingAgent-platform
git fetch && git checkout next-gen && git reset --hard origin/next-gen

# Terminal 1 — live-market paper runtime (MT5 read-only for H4 bars).
# NEVER places broker orders. Startup logs feed + arm + out dir.
.venv\Scripts\python scripts\run_squad_live.py --feed mt5 --aggregator phi41 --poll 45

# Optional: pin symbols / out-dir / wipe state
# .venv\Scripts\python scripts\run_squad_live.py --feed mt5 --symbols EURUSD GBPUSD USDCAD --reset

# Terminal 2 — platform server (skip if already a service).
.venv\Scripts\python scripts\serve_platform.py --host 0.0.0.0 --port 8787 --auth-token <secret>
```

**On Mac (no MT5)** — accelerated cache replay through the same
runtime (useful for smoke-testing before the VM):

```bash
.venv/bin/python scripts/run_squad_live.py --feed cache --poll 1 --max-steps 50
```

Browse `/v2` → LIVE. The badge should read **LIVE — market paper
(shadow-only)** when `source` starts with `live_market`. Kill:

```powershell
"pause for review" | Out-File -Encoding ascii $HOME\Documents\TradingAgentLogs\squad_live\kill.txt
```

Config knobs (CLI always wins) in `platform.toml`:

```toml
[squad_live]
feed = "mt5"                 # or "cache"; empty = platform default
aggregator = "phi41"         # or "arm4"
poll_seconds = 45
symbols = ["EURUSD", "GBPUSD", "USDCAD"]
```

### 7b.7 Redeploy the 2026-07-24 warm-up / legibility fix

The 2026-07-24 `next-gen` push fixes the P1 warm-up bug (a fresh
runtime used to wait 200 **live** H4 bars ≈ 33 days before any agent
could propose), wires Sae's hydration (calendar + M15 bars provider —
he stays **disabled** behind `--enable-sae` until the Phase AE
pre-registration passes), anchors the news-calendar cache to the repo
root, and makes /v2 silence legible.

**VM redeploy** (same clones as §7b.6):

```powershell
cd C:\TradingAgent-platform
git fetch && git checkout next-gen && git reset --hard origin/next-gen

# Restart the runtime (Ctrl-C the old one, or write kill.txt and wait
# a poll). --reset is NOT needed: seeding applies on top of existing
# state and is idempotent across restarts.
.venv\Scripts\python scripts\run_squad_live.py --feed mt5 --aggregator phi41 --poll 45

# Restart the platform server (or the Windows service from §7b.3).
.venv\Scripts\python scripts\serve_platform.py --host 0.0.0.0 --port 8787 --auth-token <secret>
```

**What to expect after the restart:**

* Startup logs a `warm-up seeded: <symbol> bars_seen=200/200
  burn_in=2 (from N history bars)` line per symbol. `state.json` gains
  a `warmup` block
  (`bars_seen / warmup_bars / burn_in_remaining / seeded_bars`).
* Strikers become proposable after a **2-live-bar burn-in** (~8 h on
  H4), not 33 days. Tune with `--burn-in-bars N` if needed.
* `--parity-mode` never seeds — cache-parity runs keep the old
  count-from-zero semantics byte-identical.
* The news cache now lives at `<repo>/data/news_calendar.json`
  regardless of the launch directory; a legacy CWD-relative cache is
  still read (with a migration log line) until the first fresh fetch.
* Calendar fetch failures / staleness now emit `system_status` rows
  into `events.jsonl` and a rate-limited squad-Telegram warning (once
  per failure streak, not per poll).

**New /v2 dashboard signals:**

* A **"why quiet"** line under the LIVE badge —
  `live_status().quiet_reason`, priority: dead/stalled > kill file >
  warming up X/200 > burn-in > "evaluating quietly". Warm-up progress
  per symbol rides along.
* An **Upcoming USD events** panel (high-impact, this-week-only FF
  feed) with countdowns, the calendar's fetched-at age (a dead feed is
  visible), and a `sae window` tag when an event's [T−30 m, T+60 m]
  window covers now — `GET /api/v2/live/upcoming_events`.
* **Sae and Karasu join the pitch.** Sae renders dimmed with an
  "(off)" label while `state.json` says `sae_enabled=false` (the
  default; the Phase AE gate). Karasu sits in the back line as the
  news-window defender.

## 8. Emergency stop

```powershell
# Halt ONE symbol (its watchdog loop will hold at the kill check):
echo "manual halt: <reason>" > $HOME\Documents\TradingAgentLogs\EURUSD\kill.txt

# Halt EVERYTHING (global master switch, repo root):
echo "manual halt: <reason>" > kill_switch
```

Delete the file(s) to resume; startup logs the recorded reason either way.
An emergency close (daily-DD breach) also closes open positions and pages
Daily-DD halt / kill switch pages you on Telegram (`TRADING HALTED`);
the healthcheck sends an annotated success ping (check stays UP). A
genuine process crash still fires `/fail` on consecutive fatal errors.
