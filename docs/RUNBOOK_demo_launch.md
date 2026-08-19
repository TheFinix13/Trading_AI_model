# Runbook — Demo-MT5 Launch & Verification

> ## Read this before copying any command below
>
> **This is a build-and-first-launch runbook, not the day-to-day command
> set.** For routine operation — pulling changes, restarting, reports,
> health checks — use **`docs/VM_QUICKSTART.md` in the v1 clone**. That
> page is the single reference and it wins over anything here.
>
> **Two paths and two branch names in this file are stale.** They date
> from the original build and are left in place because the surrounding
> setup narrative still reads correctly, but do not paste them:
>
> | Appears below as | Actually is |
> |---|---|
> | clone `C:\TradingAgent-platform` | `C:\Users\Fiyin\Documents\GitHub\TradingAgent2` |
> | branch `next-gen` | `product` (single serving branch since the D110 merge) |
>
> A scheduled task registered against the retired clone path fails
> silently every time it fires — that is a real incident that already
> happened to the Night Auditor, not a hypothetical. **Register v2 tasks
> with `scripts\setup_platform_tasks.ps1`**, which resolves the clone from
> its own location and then verifies every task points there.

> **Demo MT5 only — hard rule.** This runbook never involves live broker
> keys. The account is an Exness **demo** ($500+ recommended, see
> [08 — Live Trading & Deployment](08-live-trading-and-deployment.md)
> section 08.3). Nothing here changes strategy behaviour.

> **Branch note.** The VM's v1 trading agent runs **`main`**. The v2
> platform line — this runbook, the dashboard, the squad — runs
> **`product`**, which has been the single serving branch since the D110
> reconciliation merge. Where this file still says `next-gen`, read
> `product`.

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

> **⚠ VM venv rebuild required (2026-07-24, audit A009 / I009).**
> The dependency pin is now `pandas>=2.2,<3`, but the VM's existing
> venv already resolved **pandas 3.0.3** — a major version this code
> has never been tested against. The pin does NOT downgrade an
> existing install. Before the next VM session, rebuild the venv:
> `./.venv/Scripts/python -m pip install -r requirements.txt --force-reinstall`
> (or delete `.venv` and recreate), then confirm with
> `./.venv/Scripts/python -c "import pandas; print(pandas.__version__)"`
> — it must print 2.x.

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

### 7b.7 Ops Telegram bot (company/ops alerts on their own chat)

Company/ops alerts (`watchdog_alert`) route to a **separate** bot +
chat so ops noise never lands between trade fills. Safety events
(`kill_switch_trip`, `platform_down`) go to **both** chats — a trip
must reach you wherever you're looking. Everything else stays on the
primary alerts destination. If you skip this section entirely, ops
alerts simply fall back to the primary chat — nothing is dropped.

Two-minute setup:

1. In Telegram, message **@BotFather** → `/newbot`.
2. Name it (e.g. `Blue Lock Ops`) with a username ending in `bot`
   (e.g. `bluelock_ops_bot`). Copy the **token** BotFather replies
   with (`123456:DEF-...`) — never commit it.
3. Open a chat with the new bot and send it any message (bots can't
   message you first). For a group: add the bot to the group and post
   there.
4. Get the chat id (replace `<TOKEN>`):

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
```

   The `"chat":{"id":...}` field is the chat id (groups are negative).
   Empty `result`? Send the bot another message and re-run.

5. Add to `platform.toml` at the repo root:

```toml
[alerts.telegram.ops]
enabled = true
bot_token = "123456:DEF-..."
chat_id = "-1009876543210"
```

6. Restart the platform server (and the watchdog loop if running).
   Fail-closed: the ops destination only fires when `enabled`,
   `bot_token`, AND `chat_id` are all set.

### 7b.8 Redeploy the 2026-07-24 warm-up / legibility fix

The 2026-07-24 fix batch (originally on `next-gen`, now merged into
`product` — the single serving branch) fixes the P1 warm-up bug (a
fresh runtime used to wait 200 **live** H4 bars ≈ 33 days before any
agent could propose), wires Sae's hydration (calendar + M15 bars
provider — he stays **disabled** behind `--enable-sae` until the
Phase AE pre-registration passes), anchors the news-calendar cache to
the repo root, and makes /v2 silence legible.

**VM redeploy** (same clones as §7b.6):

```powershell
cd C:\TradingAgent-platform
git fetch && git checkout product && git reset --hard origin/product

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

### 7b.9 Keep the squad runtime + ops watchdog alive 24/5 (Task Scheduler)

> **Why (2026-07-28 weekly review).** The first v2 weekly window
> (Jul 15–28) had tape on only 2 of 10 weekdays — the runtime only ran
> when a human started it and died with the session. This section is
> the "start the shadow clock" step: after it, the squad runtime and
> the F017 ops watchdog survive reboots and logouts, and the new
> `squad_tape_freshness` check (I017) pages ops when bars stop flowing
> even while the process looks alive.

Same architecture as the v1 agents (section 2): **`AtLogOn`
interactive-user tasks + Autologon**, never a Windows Service — the
squad's `--feed mt5` reads bars over MT5's desktop-session IPC.

> **Use `scripts\setup_platform_tasks.ps1` instead of the block below.**
> It registers all four v2 tasks (squad loop, dashboard, ops watchdog,
> night auditor) against the clone it is run from, and then verifies each
> task's working directory actually points there. The hand-rolled
> commands below are kept as reference for what it does, and because they
> show the trigger shape — but they hardcode
> `C:\TradingAgent-platform`, which is **no longer the clone that holds
> the pulled code** (the current one is
> `C:\Users\Fiyin\Documents\GitHub\TradingAgent2`). A task registered
> against the wrong clone fails silently every time it fires. If you do
> run these by hand, substitute your real path everywhere, and note that
> they omit the dashboard task entirely — which is why the dashboard had
> no restarter on 2026-08-10.
>
> Day-to-day restarts are `scripts\update_platform.ps1` (or `v2up`);
> see `docs/VM_QUICKSTART.md` in the v1 clone for the whole command set.

Reference form (substitute `$repo` for your clone):

```powershell
$repo = "C:\Users\Fiyin\Documents\GitHub\TradingAgent2"
cd $repo

# 1) Squad runtime, restart-forever wrapper (kill.txt still stops it).
#    watchdog_squad.ps1 passes --enable-sae by default; -NoSae opts out.
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-ExecutionPolicy Bypass -File scripts\watchdog_squad.ps1" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName "SquadLiveRuntime" -Action $action -Trigger $trigger `
  -RunLevel Limited -Force `
  -Description "v2 squad shadow-paper runtime (restart loop; MT5 read-only)"
Start-ScheduledTask -TaskName "SquadLiveRuntime"

# 2) Dashboard on 8787. Bind 0.0.0.0 so Tailscale clients reach it.
#    Missing from earlier revisions of this runbook -- that omission is
#    why nothing restarted the dashboard when it died on 2026-08-10.
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-ExecutionPolicy Bypass -File scripts\watchdog_platform.ps1 -BindHost 0.0.0.0 -Port 8787" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName "PlatformWebUI" -Action $action -Trigger $trigger `
  -RunLevel Limited -Force -Description "v2 dashboard on 0.0.0.0:8787 (watchdog-wrapped)"
Start-ScheduledTask -TaskName "PlatformWebUI"

# 3) Ops watchdog loop (5-min cadence; pages transitions via ops Telegram):
$action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\python.exe" `
  -Argument "scripts\run_watchdog.py --loop 300" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
Register-ScheduledTask -TaskName "OpsWatchdog" -Action $action -Trigger $trigger `
  -RunLevel Limited -Force `
  -Description "F017 ops watchdog loop (observe-only, 8-check registry)"
Start-ScheduledTask -TaskName "OpsWatchdog"
```

If an older `PlatformServer` task exists, remove it — two tasks binding
8787 will fight, and `update_platform.ps1` treats either name as the
dashboard so it will restart whichever it finds:

```powershell
Stop-ScheduledTask -TaskName PlatformServer -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName PlatformServer -Confirm:$false
```

**Verify (do all four before walking away):**

1. `Get-ScheduledTask SquadLiveRuntime, OpsWatchdog` — both `Running`.
2. `type "$HOME\Documents\TradingAgentLogs\squad_live\poll_heartbeat.txt"`
   — timestamp refreshes every ≤ 60 s.
3. Within one poll of the next H4 close (03/07/11/15/19/23 UTC on the
   current feed — see the tape, not the /v2 countdown, which as of
   2026-07-28 assumes the 00/04/…/20 grid; intake I018):
   `state.json` → `last_bar_times` advances to today. If it stays
   pinned days old while the heartbeat is fresh, the feed is starved —
   check the MT5 terminal A login (squad reads bars there, read-only).
4. `.venv\Scripts\python scripts\run_watchdog.py` (one-shot) —
   `squad_tape_freshness` reports `ok` once bars flow (it will read
   `warn`/`alarm` until the first post-restart bar lands; burn-in is
   noted in the detail string).

**Stop ceremony (unchanged):** `echo pause >
"$HOME\Documents\TradingAgentLogs\squad_live\kill.txt"` — the runtime
exits at the next poll and the wrapper HOLDS (no restart) until the
file is deleted. `Stop-ScheduledTask -TaskName SquadLiveRuntime` kills
the wrapper itself.

### 7b.10 Night Auditor — daily tape audit at 06:30 (Task Scheduler)

> **Why (2026-08-04, D144).** The 5-min OpsWatchdog answers "is it
> alive right now?"; nobody answered "did yesterday make sense?" until
> a human read the weekly report — which is how the silent week ran
> for days. The Night Auditor (`scripts/night_audit.py`, role doc at
> `company/roles/night_auditor.md`, Ego Jinpachi persona) reads ONE
> UTC day of tape every morning: per-symbol bar coverage vs the H4
> grid, timestamp_miss regressions, feed stale/refresh-error streaks,
> activity counts. Observe-and-draft only: it writes a digest + intake
> stubs under `<live_dir>\audits\` and sends ONE ops-Telegram line
> ("all nominal" or "N anomalies: …"). No LLM, no mutations, no git.

**`scripts\setup_platform_tasks.ps1` registers this for you** against
the correct clone, alongside the other three tasks. Prefer it.

If you register by hand, **use YOUR clone's real path** — on the current
VM that is `C:\Users\Fiyin\Documents\GitHub\TradingAgent2`, the same repo
the SquadLiveRuntime watchdog logs as `repo=`. A task registered against
a path that doesn't hold the pulled code fails silently every morning,
which is precisely what happened to a NightAuditor pointed at the retired
`C:\TradingAgent-platform`. `-Force` makes re-registration idempotent:

```powershell
$repo = "C:\Users\Fiyin\Documents\GitHub\TradingAgent2"   # <- your clone
cd $repo

$action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\python.exe" `
  -Argument "scripts\night_audit.py" `
  -WorkingDirectory "$repo"
$trigger = New-ScheduledTaskTrigger -Daily -At 6:30am
Register-ScheduledTask -TaskName "NightAuditor" -Action $action -Trigger $trigger `
  -RunLevel Limited -Force `
  -Description "Daily squad tape audit (observe-and-draft; digest + ops Telegram line)"

# Confirm the action points at the right clone:
(Get-ScheduledTask NightAuditor).Actions | Format-List Execute, Arguments, WorkingDirectory

# Smoke it immediately (audits yesterday UTC, prints the digest):
.venv\Scripts\python scripts\night_audit.py
```

**Verify:**

1. The smoke run prints a digest and
   `type "$HOME\Documents\TradingAgentLogs\squad_live\audits\night_audit_*.md"`
   shows it on disk.
2. If the ops Telegram block (§7b.7) is configured, one message lands
   on the ops chat per run.
3. Next morning after 06:30: a fresh digest file exists for yesterday.
   Warn/alarm days also leave `audits\stubs\*.md` drafts — triage them
   in the next Cursor session (promote to `company/rd/intake/I###` or
   dismiss with a note in the stub).

Weekend behaviour: Saturday/Sunday coverage floors are zero, so closed
markets read "all nominal" rather than paging you.

## 7c. Demo-order executor (F018) — wire the "V2 Platform" demo account

> **What this is.** Sprint 2b's demo-order executor: approved entries
> on `/approvals` can be sent as real market orders to a DEMO account
> only. Default-disabled; demo-server allowlist enforced in code;
> volume hard-capped at 0.01 lots; every approval is single-use.
> Real-broker connections remain a hard NO (escalation protocol,
> Section 5).

**Designated account** (the only account this should ever point at):

| Field    | Value                                    |
|----------|------------------------------------------|
| Nickname | V2 Platform                              |
| Login    | 436983644                                |
| Server   | `Exness-MT5Trial9` (DEMO trial server)   |
| Type     | Pro, USD, $500                           |

The password lives ONLY in the platform keyring (entered once via
`/settings/broker` on the VM). It must never appear in this repo, in
`platform.toml`, in `.env`, or in any log.

### 7c.1 One-time setup (on the Windows VM)

1. **Pin the platform's own MT5 terminal FIRST** — before storing any
   credentials, set `[broker] terminal_path` + `portable = true` in
   `platform.toml` and confirm a second portable terminal exists at
   that path (setup: `docs/runbooks/dual-mt5-terminals.md`):

```toml
[broker]
terminal_path = "C:/MT5-V2/terminal64.exe"
portable = true
```

   This step is not optional on a single-terminal VM and it is not
   last for a reason. Incident
   `company/rd/intake/I015-mt5-account-contention-v1-killed.md` (P0,
   2026-07-24, resolved under D124): with no pin, a platform-side
   `mt5.initialize(login=…)` switches the machine-default terminal's
   logged-in account out from under the v1 zones agent. v1 saw equity
   drop ~$969 → $500 in one poll, concluded catastrophic drawdown,
   wrote `kill.txt`, and attempted emergency closes against the wrong
   account. The very next step's connection probe is itself an
   `mt5.initialize(login=…)` call, so an unpinned run reproduces I015
   before the executor is even enabled.
2. **Store the credentials** — open `/settings/broker`, add an alias
   (suggested: `v2-demo`) with login `436983644`, server
   `Exness-MT5Trial9`, and the password. Probe it from the same page;
   the health pill must go green before anything else matters.
3. **Set the risk budget** — `/risk`: per-day / per-symbol /
   per-strategy caps. Defaults ($100 / $50 / $50 max loss) are sane
   for a $500 demo.
4. **Enable the executor** in `platform.toml` (all six keys matter;
   `demo_only = true` is a required acknowledgement, not decoration):

```toml
[live_executor]
enabled = true
demo_only = true                 # required ack; absent/false refuses
allowed_server_patterns = ["*Trial*", "*Demo*", "*demo*"]
max_volume_lots = 0.01
broker_alias = "v2-demo"
magic = 314159                   # optional; this IS the default
```

   `magic` (F025 B5) is the MT5 magic number stamped on every order
   and every close this executor sends. It is what makes a position on
   a shared account attributable to v2 — reconciliation, "close only
   my positions", and any post-hoc attribution all need it. The
   default `314159` is deliberately distinct from the v1 zones agent's
   `271828` (`agent/live/broker.py`), so the two never claim each
   other's positions even if the step-1 pin were lost. A zero,
   negative or non-integer value is ignored in favour of the default:
   magic `0` means "unattributed" to MT5, which is the state this key
   exists to end. `/api/executor/status` echoes the value in use, and
   every `executions.jsonl` row carries it.
5. **Restart the platform server** (or the Windows service) so the
   config is re-read.

### 7c.2 The ceremony order (every session)

The executor refuses unless ALL of these are true at the moment you
click Execute — do them in order:

1. Broker creds stored + probe green (`/settings/broker`).
2. Risk budget has headroom (`/risk`).
3. Live-mode ceremony done (`/settings/live-mode` — acknowledge +
   type `ENABLE LIVE MODE`). One click turns it back off.
4. Submit a test proposal through the internal endpoint (requires
   `[internal] token` set in `platform.toml`):

```powershell
curl -X POST http://127.0.0.1:8787/api/approvals/submit `
  -H "X-Bluelock-Internal-Token: <your internal token>" `
  -H "Content-Type: application/json" `
  -d '{"symbol":"EURUSD","side":"buy","size":0.01,"entry":1.09,
       "stop":1.085,"take_profit":1.10,
       "rationale":"executor ceremony test",
       "source_agent":"runbook_test",
       "risk_snapshot":{"worst_case_loss":5.0}}'
```

5. Approve it on `/approvals` within the 5-minute timeout.
6. Click **Execute (DEMO account)** on the approved card. Expected:
   `filled: ticket <n>` and the position visible in the MT5 terminal
   on the VM. The fill lands in `executions.jsonl`, the risk ledger,
   and the alerts stream (Telegram if the bridge is on).

### 7c.2a Closing a position from the platform (F025 B4)

Orders go out with SL/TP attached and are otherwise broker-managed.
`POST /api/executor/close/<ticket>` is the operator's unwind path.
There is no UI for it — use the internal endpoint:

```powershell
curl -X POST http://127.0.0.1:8787/api/executor/close/12345678 `
  -H "X-Bluelock-Token: <your install token>"
```

What it will and will not do:

- Same refusal stack as Execute: executor `enabled`, a configured
  `broker_alias` with stored credentials, and the DEMO-ONLY guard
  against the server the adapter actually reports. Install-token
  gated and rate-limited like every other `/api/*` write.
- **Only tickets this executor filled itself** may be closed — the
  ticket must appear in `executions.jsonl` with `status: "filled"`.
  Anything else (an unknown ticket, or the v1 agent's ticket) refuses
  with `close_refused`. The `magic` number is the broker-side half of
  the same claim; the audit log is the authoritative list here.
- **The kill switch does NOT block a close.** This is deliberate: a
  close reduces risk, so it stays available exactly when the kill
  switch is on. A halt that also trapped you in your positions would
  be a worse failure than the one it prevents.
- Idempotent: closing an already-closed ticket refuses cleanly.
- Every attempt appends a row (`closed` / `close_refused` /
  `close_error`) to `executions.jsonl` and publishes a `trade_fill`
  alert carrying the matching `status`.

Expected on success: `{"ok": true, "status": "closed", ...}` and the
position gone from the MT5 terminal on the VM. Note that the squad's
own paper `_check_exit` does NOT reach the broker — a real position
closes only via SL/TP, this route, or the terminal itself.

### 7c.3 Kill-switch drill (do this once after wiring)

1. Trip the global switch on `/settings/kill-switches` (or
   `echo halt > kill_switch` at the repo root).
2. Submit + approve another test proposal, click Execute — it MUST
   refuse with a kill-switch reason and consume nothing.
3. Clear the switch; verify `/api/executor/status` still says ready.

If any step of the drill does not behave exactly as above, stop and
treat it as a P0 intake item — do not keep executing.

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
