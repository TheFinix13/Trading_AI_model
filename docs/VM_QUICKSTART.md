# VM commands — the single reference

This is the one page. If a command isn't here, it isn't part of the
routine. Anything you find in an older note, a chat scrollback, or a
runbook section that contradicts this page is stale — this page wins.

Two agents run on the Windows VM:

| | Repo on the VM | Branch | What it is |
|---|---|---|---|
| **v1** | `C:\Users\Fiyin\Documents\GitHub\Trading_AI_model` | `main` | The live demo-MT5 zones trading agent. Places orders. |
| **v2** | `C:\Users\Fiyin\Documents\GitHub\TradingAgent2` | `product` | The squad + dashboard. Shadow only, places no orders. |

> **Retired path.** `C:\TradingAgent-platform` was the original v2 clone
> and is dead. A scheduled task pointed there fails silently every time
> it fires — which is exactly what happened to the Night Auditor. As of
> 2026-08-19 the path is gone from every doc and script in both repos:
> `RUNBOOK_demo_launch.md` was corrected inline, and
> `install_vm_shortcuts.ps1` no longer auto-detects it and warns if you
> point it there on purpose. If you still see it in a chat scrollback,
> that scrollback is out of date.

---

## Part 1 — One-time setup (per VM, and again only if a clone moves)

Run these three, in order, once. **Not after every update.** This is the
part that has caused the most confusion, so to be explicit: registering
scheduled tasks is a *setup* action, and starting or restarting them is a
*daily* action. They are different commands and you almost never need the
setup ones again.

**1. v1 scheduled tasks** — elevated PowerShell (it sets a machine-wide
Windows Update reboot policy):

```powershell
cd $HOME\Documents\GitHub\Trading_AI_model
powershell -ExecutionPolicy Bypass -File scripts\setup_self_healing.ps1
powershell -ExecutionPolicy Bypass -File scripts\verify_self_healing.ps1
```

This registers `TradingAgent-EURUSD`, `-GBPUSD` and `-USDCAD`, puts MT5
in Startup, and checks autologon. **This is the command that starts all
three symbols.**

**2. v2 scheduled tasks** — normal PowerShell, from the v2 clone:

```powershell
cd $HOME\Documents\GitHub\TradingAgent2
powershell -ExecutionPolicy Bypass -File scripts\setup_platform_tasks.ps1
```

Registers `SquadLiveRuntime`, `PlatformWebUI`, `OpsWatchdog` and
`NightAuditor`, all against the clone it is run from, and confirms each
task's working directory actually points there. It retires any old
`PlatformServer` task, since two tasks fighting over port 8787 is worse
than one.

**3. The shortcuts** — normal PowerShell, from the v1 clone:

```powershell
cd $HOME\Documents\GitHub\Trading_AI_model
powershell -ExecutionPolicy Bypass -File scripts\install_vm_shortcuts.ps1
```

Then **open a new PowerShell window**. If it complains about the
execution policy, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
once.

Finally, reboot and touch nothing. Within a couple of minutes you should
get three "Agent ONLINE" Telegram messages and have a dashboard on 8787.
That hands-off reboot is the only proof that counts.

---

## Part 2 — Daily commands (this is all you need)

No `cd`. No paths. No python. Type `agenthelp` any time to print this
table in the terminal.

| Command | What it does |
|---|---|
| `agents` | Both health reports, back to back. Start here. |
| `v1status` / `v2status` | One agent's health report. Changes nothing. |
| `v1up` / `v2up` | Pull the branch, restart that agent's tasks, verify. |
| `v1report` / `v2report` | Weekly report zip. |
| `v2web` | Open the dashboard in a browser with its token filled in. |
| `v1log` / `v2log` | Live tail of the freshest log. Ctrl-C to stop. |
| `v1cd` / `v2cd` | Drop into the clone. |

**After I push changes, the entire procedure is:**

```powershell
v1up      # if I touched the v1 agent
v2up      # if I touched the v2 squad or dashboard
```

That's it. `v2up` restarts the squad loop and the dashboard for you —
you do not run `watchdog_squad.ps1` or `watchdog_platform.ps1` by hand,
and you do not re-run the setup scripts.

### Reports

Flags pass through, so all your old variants still work:

```powershell
v1report                                      # last 7 days
v1report -Days 14
v1report -Start 2026-07-08 -End 2026-07-14    # a specific incident window
v1report -Days 7 -Symbols EURUSD,GBPUSD
v1report -Days 7 -Out D:\reviews\last_week.zip

v2report -Days 10
```

### Switches worth knowing

```powershell
v1up -NoRestart      # pull, but don't interrupt an open trade
v2up -StatusOnly     # identical to v2status
v1up -Branch <name>  # only if I've asked you to test a branch
```

---

## Part 3 — When something is wrong

**Ask first, don't act.** `agents` answers most questions on its own: it
reports each task's state, whether MT5 is running, whether a halt file is
sitting there (the usual cause of a silent no-trade week), whether
anything is listening on 8787, whether Aoshi is in the lineup, what
equity Sentinel is sizing against, and how stale the tape is.

**"No watchdog tasks are registered."** You're in the Part 1 case — run
the matching setup script above. This is the only situation in which the
raw watchdog commands below are relevant.

**Running a watchdog by hand.** Only for debugging, when you want to
watch it in the foreground and read the output live. Each occupies its
window until you Ctrl-C it, and nothing restarts it afterwards:

```powershell
# v1 — one window per symbol
powershell -ExecutionPolicy Bypass -File scripts\watchdog_agent.ps1 -Symbol EURUSD

# v2 — one window each
powershell -ExecutionPolicy Bypass -File scripts\watchdog_squad.ps1
powershell -ExecutionPolicy Bypass -File scripts\watchdog_platform.ps1
```

**Dashboard won't load.** `v2status` tells you whether anything holds
8787. If nothing does, `v2up` restarts it. If it comes back and dies
again, `v2log` will show why.

**Nuclear option.** `Restart-Computer`, then touch nothing. Everything is
registered to come back on its own; if it doesn't, that is the bug worth
reporting.

---

## Appendix — the raw commands, per agent

The shortcuts above are a convenience layer, not a replacement. This is
the canonical hand-typed form for each agent, kept here so it is written
down rather than reconstructed from memory each time. **The two agents
are fully independent: nothing below touches both, and there is no
combined update command.**

### v1 — live trading agent (branch `main`, tasks `TradingAgent-*`)

```powershell
cd C:\Users\Fiyin\Documents\GitHub\Trading_AI_model
git fetch origin main
git pull --ff-only origin main

# restart the three symbol watchdogs
Get-ScheduledTask -TaskName "TradingAgent-*" | ForEach-Object {
    Stop-ScheduledTask  -TaskName $_.TaskName -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $_.TaskName
}

# weekly report
python scripts\weekly_report.py --days 14
```

### v2 — squad + dashboard (branch `product`)

```powershell
cd C:\Users\Fiyin\Documents\GitHub\TradingAgent2
git fetch origin product
git pull --ff-only origin product

# clear a stale kill file, then restart the four v2 tasks
Remove-Item "$HOME\Documents\TradingAgentLogs\squad_live\kill.txt" -ErrorAction SilentlyContinue
foreach ($t in @("SquadLiveRuntime","PlatformServer","OpsWatchdog","NightAuditor")) {
    Stop-ScheduledTask  -TaskName $t -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
}

# weekly report
python scripts\weekly_squad_report.py --days 10
```

The dashboard task is `PlatformServer` on the current VM; the runbook
calls it `PlatformWebUI`. `update_platform.ps1` accepts either, but a
hand-typed command has to use the name actually registered.

---

## What the update scripts refuse to do

Both stop rather than guess, which is why they are safe to run whenever:

- **Wrong branch.** v1 expects `main`, v2 expects `product`. A mismatch is
  a hard stop, so a v1 update can never land on another lane.
- **Uncommitted changes.** Reported, never stashed and never discarded.
- **Non-fast-forward.** `--ff-only`, so the VM can never end up holding a
  merge commit or a conflict to resolve by hand.
