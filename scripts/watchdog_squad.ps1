<#
.SYNOPSIS
    Runs the v2 squad live runtime (shadow paper) and restarts it forever
    if it ever exits -- crash, MT5 disconnect, VM hiccup, anything.

.DESCRIPTION
    The squad counterpart of watchdog_agent.ps1 (which loops run_live.py
    per symbol for the v1 agent). Motivated by the 2026-07-15..28 weekly
    v2 review: the runtime only ran when a human started it and died with
    the session -- 8 of 10 weekdays had no tape at all.

    Intended to be launched by a Task Scheduler task tied to a user's
    interactive LOGON session (trigger: "At log on", logon type
    Interactive) -- NOT registered as a Windows Service / via NSSM.
    MetaTrader5's Python API talks to the terminal over local IPC that
    only works inside the same interactive desktop session, so combine
    with Windows Autologon (already set up for v1, runbook section 2).

    Honouring kill.txt: run_squad_live.py exits when
    <log_root>\squad_live\kill.txt exists. This wrapper checks for the
    same file BEFORE each relaunch and holds (no restart) until it is
    deleted -- so "write kill.txt" remains a real stop, not a 15-second
    pause.

.PARAMETER RepoDir
    Repo root. Defaults to the parent of this script's folder.

.PARAMETER Poll
    Idle poll seconds passed to run_squad_live.py. Default 45.

.EXAMPLE
    powershell.exe -ExecutionPolicy Bypass -File scripts\watchdog_squad.ps1
#>
param(
    [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot),

    [int]$Poll = 45
)

Set-Location $RepoDir

$logDir = Join-Path $HOME "Documents\TradingAgentLogs\squad_live"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$watchdogLog = Join-Path $logDir "watchdog_squad.log"
$killFile = Join-Path $logDir "kill.txt"

function Write-Watchdog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [watchdog:squad] $Message"
    Write-Host $line
    Add-Content -Path $watchdogLog -Value $line
}

Write-Watchdog "Squad watchdog started (repo=$RepoDir, poll=${Poll}s)"

$restartDelaySeconds = 15
$killHoldSeconds = 60

while ($true) {
    if (Test-Path $killFile) {
        Write-Watchdog "kill.txt present -- holding (no restart). Delete it to resume."
        Start-Sleep -Seconds $killHoldSeconds
        continue
    }
    Write-Watchdog "Launching: python scripts\run_squad_live.py --feed mt5 --poll $Poll"
    python scripts\run_squad_live.py --feed mt5 --poll $Poll
    $code = $LASTEXITCODE
    Write-Watchdog "Squad process exited (code=$code). Restarting in ${restartDelaySeconds}s..."
    Start-Sleep -Seconds $restartDelaySeconds
}
