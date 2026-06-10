# Runbook — Live Demo Trading on the Windows VM (VMware + MT5/Exness)

How to run the three deployed symbol processes (EURUSD, GBPUSD, USDCAD) on
the Windows VM, one PowerShell tab per symbol.

## Prerequisites

1. **MT5 terminal installed and logged in** to the Exness demo account
   (server e.g. `Exness-MT5Trial`). Log in once manually in the terminal so
   the account is cached; the agent then attaches via the MetaTrader5 Python
   API. The terminal must be running while the agent trades.
2. **`.env` in the repo root** with the demo credentials:

   ```
   MT5_LOGIN=12345678
   MT5_PASSWORD=your-demo-password
   MT5_SERVER=Exness-MT5Trial
   ```

   (`MT5_PATH` optional if the terminal is in the default install location.)
3. **Python dependencies installed** in the VM's environment
   (`pip install -r requirements.txt`, which includes the Windows-only
   `MetaTrader5` package).
4. **Demo balance: $500 or more recommended.** H4 stop distances are wide
   (often 40-100+ pips). At the broker minimum lot of 0.01, the dollar risk
   of such a stop can exceed the sizer's 0.5-2% risk band on a $100 account,
   and the position sizer will then *skip* those trades rather than
   over-risk. $500+ keeps the min-lot risk inside the band so valid signals
   actually execute.

## Start the three processes (one PowerShell tab each)

```powershell
python scripts/run_live.py --broker exness --symbol EURUSD --verbose
```

```powershell
python scripts/run_live.py --broker exness --symbol GBPUSD --verbose
```

```powershell
python scripts/run_live.py --broker exness --symbol USDCAD --verbose
```

## What healthy startup looks like

Each tab should print (among other lines):

```
Logging to: C:\Users\<name>\Documents\TradingAgentLogs\EURUSD\EURUSD_2026-06-10.log
Routed cell: EURUSD/H4/all mode=htf_against risk_scale=1.00 alpha=zone_h4_all
MT5 connected: login=... server=Exness-MT5Trial balance=...
Broker OK: exness balance=$...
Signal loop starting ...
```

Check the routed cell line carefully — it is the proof you are trading the
validated router cell:

| Tab    | Expected routed cell line                                  |
| ------ | ---------------------------------------------------------- |
| EURUSD | `EURUSD/H4/all mode=htf_against risk_scale=1.00`            |
| GBPUSD | `GBPUSD/H4/all mode=htf_against risk_scale=0.50`            |
| USDCAD | `USDCAD/H4/all mode=htf_against risk_scale=0.50`            |

If you start an undeployed symbol (e.g. USDJPY) the process refuses to start
with a clear error listing the deployed symbols — that is by design.

## Log files

- Default location: `C:\Users\<name>\Documents\TradingAgentLogs\`
  (easy to find in File Explorer — it is NOT inside the repo).
- **One subfolder per symbol**, so the three processes never mix:

  ```
  TradingAgentLogs/
    EURUSD/
      EURUSD_2026-06-10.log
      EURUSD_2026-06-11.log
    GBPUSD/
      GBPUSD_2026-06-10.log
    USDCAD/
      USDCAD_2026-06-10.log
  ```

- **One file per UTC day**, named `SYMBOL_YYYY-MM-DD.log` (sorts
  chronologically in Explorer, and the symbol stays visible when a single
  file is downloaded or shared — e.g. over WhatsApp — without its folder).
  A process left running for days rolls over at UTC midnight into a fresh
  dated file automatically; the last 30 days are kept.
- The exact path is printed at startup (`Logging to: ...`).
- Each day's file is plain text with the same lines as the console — you can
  open it and **copy-paste the whole file into chat for review**.
- Override the root folder with `--log-dir`, e.g.
  `python scripts/run_live.py --broker exness --symbol EURUSD --log-dir D:\logs`.

### Reading the logs

The agent only **decides** at H4 candle closes — 00, 04, 08, 12, 16 and 20
UTC. The loop polls every 30 seconds, but between closes there is nothing to
decide, so the log is intentionally quiet. Two kinds of lines tell you it is
alive and working:

- **Heartbeat** (every 15 minutes):

  ```
  heartbeat: balance=$512.34 equity=$510.10 open_positions=1 | next H4 close ~16:00 UTC
  ```

  Balance/equity come from the position monitor's last broker snapshot; right
  after startup (before the first monitor cycle) the heartbeat may briefly
  say `running (account snapshot pending)` instead.

- **Per-close evaluation** (one line at each H4 close, when no trade is taken):

  ```
  H4 close 16:00 UTC: evaluated, no setup (alphas checked: zone_h4_all)
  ```

  This is the proof the candle WAS evaluated and simply produced no setup.
  If a signal fires instead, you will see the routing/sizing/order lines.

**Silence between heartbeats is normal.** Only worry if heartbeats stop
appearing for well over 15 minutes while the process is supposedly running.

## No charts needed

You do **not** need to open any charts or manually add symbols to Market
Watch. The agent reads price data through the MT5 API and calls
`symbol_select` itself before fetching bars or placing orders, so EURUSD,
GBPUSD and USDCAD are selected into Market Watch automatically (including
broker-suffixed variants like `GBPUSDm`). The MT5 terminal just has to be
running and logged in.

## Stopping safely

- **Normal stop**: `Ctrl+C` in the tab. The loop catches it and shuts down
  cleanly. Open positions keep their broker-side SL/TP, so they remain
  protected even with the agent stopped.
- **Kill switch (all tabs at once, without touching them)**: create a file
  named `kill.txt` in the repo root. Every loop iteration checks it; the
  monitor closes open positions and the loops stand down. Delete the file
  before restarting.

## Near-miss and loss vaults

Each symbol process also keeps two **observation-only** evidence folders next
to its daily logs (pure logging — they never change what the agent trades):

```
TradingAgentLogs/
  EURUSD/
    EURUSD_2026-06-10.log
    near_misses/
      events.jsonl                      ← one JSON line per near-miss
      2026-06-10_0800_htf_gate.png      ← chart snapshot of the event
    losses/
      events.jsonl                      ← one JSON line per losing close
      2026-06-12_1600_loss.png          ← chart with the trade's lifetime
```

- **Near-misses** are trades the agent almost took: zone touches rejected
  only by the D1 HTF gate (`htf_gate`), plus signals dropped downstream by
  the post-loss guard (`post_loss_guard`), the risk manager / max-positions
  check (`risk_manager`), or a zero-lot sizing skip (`sizing_skip`).
- **Losses** are live positions that closed in the red, with entry/exit
  prices, pnl, R-multiple and the chart from entry to exit.
- Both the PNGs and the `events.jsonl` files are plain files — **copy them
  into chat for review** exactly like the daily logs.

**Weekly routine** (any machine with the parquet cache, e.g. the Mac):

```bash
python scripts/resolve_near_misses.py --symbol EURUSD
python scripts/resolve_near_misses.py --symbol GBPUSD
python scripts/resolve_near_misses.py --symbol USDCAD
```

The resolver scores each unresolved near-miss (would the hypothetical trade
have hit SL or TP first? both-in-one-bar counts as SL, conservative),
rewrites the JSONL with the outcomes, re-renders charts with ~40 aftermath
bars, and prints a per-reason summary (n / win rate / avg R). Review the
table; if a reason tag looks systematically profitable, that is a
**hypothesis** to pre-register through the validation pipeline — never a
reason to loosen a gate directly.

## Expected behaviour / trade frequency

- Signals are driven by **H4 candle closes**; the loop polls every **30
  seconds** but only acts when a new H4 bar has closed, so most log lines are
  quiet heartbeat/no-signal entries. That is normal.
- Expect roughly **3-5 trades per week across all three pairs combined**.
  Hours or days with no trades are expected — do not "fix" a quiet agent.
- Every order is placed with a structural stop loss and take profit; naked
  orders are refused by a hard guard in the broker layer.
