<#
.SYNOPSIS
    Runs the platform dashboard server (serve_platform.py) and restarts
    it forever if it ever exits -- crash, unhandled request error, VM
    hiccup, anything.

.DESCRIPTION
    The dashboard counterpart of watchdog_squad.ps1. Motivated by the
    2026-08-10 weekly review: localhost:8787 refused connections inside
    the VM because serve_platform.py had died at some point and nothing
    restarted it -- the server only ran when a human started it.

    Intended to be launched by a Task Scheduler task tied to the user's
    interactive LOGON session (trigger: "At log on"), same posture as
    watchdog_agent.ps1 / watchdog_squad.ps1. The server itself is
    read-only over the tape and holds no state, so a blind restart is
    always safe.

    Stopping: create stop_platform.txt in the log dir. The wrapper
    checks for it before each relaunch and holds until it is deleted.
    (serve_platform.py has no kill-file convention of its own; Ctrl+C /
    process kill is its normal stop, which is exactly what this wrapper
    would otherwise undo.)

.PARAMETER RepoDir
    Repo root. Defaults to the parent of this script's folder.

.PARAMETER BindHost
    Bind address. Default 0.0.0.0 so the Mac can browse via the VM IP.

.PARAMETER Port
    Port. Default 8787.

.EXAMPLE
    powershell.exe -ExecutionPolicy Bypass -File scripts\watchdog_platform.ps1
#>
param(
    [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot),

    [string]$BindHost = "0.0.0.0",

    [int]$Port = 8787
)

Set-Location $RepoDir

$logDir = Join-Path $HOME "Documents\TradingAgentLogs\platform"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$watchdogLog = Join-Path $logDir "watchdog_platform.log"
$stopFile = Join-Path $logDir "stop_platform.txt"

function Write-Watchdog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [watchdog:platform] $Message"
    Write-Host $line
    Add-Content -Path $watchdogLog -Value $line
}

Write-Watchdog "Platform watchdog started (repo=$RepoDir, bind=${BindHost}:${Port})"

$restartDelaySeconds = 15
$stopHoldSeconds = 60

while ($true) {
    if (Test-Path $stopFile) {
        Write-Watchdog "stop_platform.txt present -- holding (no restart). Delete it to resume."
        Start-Sleep -Seconds $stopHoldSeconds
        continue
    }
    Write-Watchdog "Launching: python scripts\serve_platform.py --host $BindHost --port $Port"
    python scripts\serve_platform.py --host $BindHost --port $Port
    $code = $LASTEXITCODE
    Write-Watchdog "Platform server exited (code=$code). Restarting in ${restartDelaySeconds}s..."
    Start-Sleep -Seconds $restartDelaySeconds
}
