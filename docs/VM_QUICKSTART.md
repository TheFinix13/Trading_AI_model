# VM quickstart — the only commands you need

Both agents run on the Windows VM. Neither needs you to remember a
directory again: each clone ships a self-locating update script, and a
one-time installer turns those into two-word commands.

## One-time setup (per VM)

```powershell
cd C:\Users\Fiyin\Documents\GitHub\Trading_AI_model
powershell -ExecutionPolicy Bypass -File scripts\install_vm_shortcuts.ps1
```

It auto-detects the v2 clone; if it can't find it, pass the path:
`-V2Dir C:\TradingAgent-platform`. Then open a **new** PowerShell window.

If it warns about the execution policy, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Daily commands

| Command | What it does |
|---|---|
| `v1status` | v1 health report. Changes nothing. |
| `v1up` | v1: pull `main`, restart the per-symbol watchdogs, verify. |
| `v2status` | v2 health report. Changes nothing. |
| `v2up` | v2: pull `product`, restart squad loop + dashboard, verify. |
| `agents` | Both status reports, back to back. |
| `v1log` / `v2log` | Live tail of the freshest log (Ctrl-C to stop). |
| `v1cd` / `v2cd` | Drop into the clone. |

Switches pass through: `v1up -NoRestart` (pull but don't interrupt an
open trade), `v2up -StatusOnly`, `v1up -Branch <other>`.

## What the scripts refuse to do

Both update scripts stop rather than guess:

- **Wrong branch** — v1 expects `main`, v2 expects `product`. A mismatch
  is a hard stop, so a v1 update can never land on another lane.
- **Uncommitted changes** — reported, never stashed or discarded.
- **Non-fast-forward** — `--ff-only`, so the VM can never end up holding
  a merge commit or a conflict.

## What the verify step tells you

v1: branch and HEAD, each watchdog task's state, whether MT5's
`terminal64.exe` is running, whether a `kill_switch` / `kill.txt` halt
file is sitting there (the usual cause of a silent no-trade week), and
the tail of each symbol log with its age.

v2: task states, whether anything is listening on 8787 (the cause of the
2026-08-10 localhost refusal), `sae_enabled` in `state.json`, the equity
Sentinel R1 is sizing against, per-player books, and the tape's age.

## Running without scheduled tasks

If the tasks aren't registered, the update scripts say so and print the
direct watchdog commands. Register them with
`scripts\setup_self_healing.ps1` (v1) or per
`docs/RUNBOOK_demo_launch.md` §4 and §7 in the v2 clone.
