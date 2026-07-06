<#
.SYNOPSIS
    Runs one live-agent process for a single symbol and restarts it forever
    if it ever exits -- crash, kill switch halt, MT5 disconnect, anything.

.DESCRIPTION
    Intended to be launched by a Task Scheduler task tied to a user's
    interactive LOGON session (trigger: "At log on", logon type Interactive)
    -- NOT registered as a Windows Service / via NSSM.

    MetaTrader5's Python API talks to the MT5 terminal over local IPC that
    only works within the same interactive desktop session the terminal is
    running in. Windows Services (NSSM included) run in an isolated
    "Session 0" that cannot reach that desktop, so a real service would
    likely fail to connect to MT5 (or connect to nothing). Task Scheduler,
    run as this interactive user, keeps the script in the same session as
    the MT5 terminal -- combine with Windows Autologon so that session
    exists automatically after a reboot with nobody physically logging in.

    See docs/08-live-trading-and-deployment.md for the full setup steps
    (autologon, MT5 in the Startup folder, registering the scheduled tasks).

.PARAMETER Symbol
    Trading symbol to run (e.g. EURUSD, GBPUSD, USDCAD).

.PARAMETER Broker
    Broker connection type passed to run_live.py. Default: exness.

.PARAMETER RepoDir
    Repo root. Defaults to the parent of this script's folder, so it works
    regardless of where the repo is cloned.

.EXAMPLE
    powershell.exe -ExecutionPolicy Bypass -File scripts\watchdog_agent.ps1 -Symbol EURUSD
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Symbol,

    [string]$Broker = "exness",

    [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot)
)

Set-Location $RepoDir

$logDir = Join-Path $HOME "Documents\TradingAgentLogs\$Symbol"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$watchdogLog = Join-Path $logDir "watchdog.log"

function Write-Watchdog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [watchdog:$Symbol] $Message"
    Write-Host $line
    Add-Content -Path $watchdogLog -Value $line
}

Write-Watchdog "Watchdog started (repo=$RepoDir, broker=$Broker)"

$restartDelaySeconds = 15

while ($true) {
    Write-Watchdog "Launching: python scripts\run_live.py --broker $Broker --symbol $Symbol --verbose"
    python scripts\run_live.py --broker $Broker --symbol $Symbol --verbose
    $code = $LASTEXITCODE
    Write-Watchdog "Agent process exited (code=$code). Restarting in ${restartDelaySeconds}s..."
    Start-Sleep -Seconds $restartDelaySeconds
}
