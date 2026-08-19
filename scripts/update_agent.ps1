<#
.SYNOPSIS
    One command to pull the latest v1 trading-agent code on the VM and
    restart the per-symbol watchdogs, then prove it actually took.

.DESCRIPTION
    Replaces the hand-typed sequence (cd into the clone, git pull, stop
    tasks, start tasks, hunt for the log tail). The script locates its
    own repo via $PSScriptRoot, so there is no path to remember and no
    path to get wrong -- wherever this clone lives, the script works.

    Safety rules it enforces so a routine update can never surprise you:

      * Refuses to pull unless the checked-out branch is the expected
        one (default `main` -- the declared v1 lane). Wrong branch is a
        hard stop, not a warning.
      * Refuses to pull when the working tree has uncommitted changes,
        and shows you what they are. It never stashes or discards.
      * Uses --ff-only, so it can never create a merge commit or a
        conflict on the VM.
      * -StatusOnly does no git and no restart at all: read-only health
        report. Run this first if you just want to know what's up.

.PARAMETER StatusOnly
    Report health only. No fetch, no pull, no restart.

.PARAMETER NoPull
    Restart the watchdogs against the code already on disk.

.PARAMETER NoRestart
    Pull, but leave the running agents alone (they pick up new code at
    their next natural restart -- use when a trade is open and you would
    rather not interrupt the monitor).

.PARAMETER Branch
    Expected branch. Default `main`. Only change this if the session's
    declared v1 lane has changed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\update_agent.ps1

.EXAMPLE
    # health check, changes nothing
    powershell -ExecutionPolicy Bypass -File scripts\update_agent.ps1 -StatusOnly
#>
param(
    [switch]$StatusOnly,
    [switch]$NoPull,
    [switch]$NoRestart,
    [string]$Branch = "main",
    # Not defaulted to $PSScriptRoot in param(): Windows PowerShell 5.1
    # has not populated it at parameter-binding time.
    [string]$RepoDir = ""
)

$ErrorActionPreference = "Continue"
if (-not $RepoDir) { $RepoDir = Split-Path -Parent $PSScriptRoot }

function Write-Head([string]$Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}
function Write-Ok([string]$Text)   { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Write-Bad([string]$Text)  { Write-Host "  [FAIL] $Text" -ForegroundColor Red }
function Write-Info([string]$Text) { Write-Host "         $Text" -ForegroundColor Gray }

$logRoot = Join-Path $HOME "Documents\TradingAgentLogs"
$taskPrefix = "TradingAgent-"

Write-Host ""
Write-Host "v1 trading agent -- update + restart" -ForegroundColor White
Write-Info "repo: $RepoDir"

# ---------------------------------------------------------------------------
# 1. Git state
# ---------------------------------------------------------------------------
Write-Head "git"

if (-not (Test-Path (Join-Path $RepoDir ".git"))) {
    Write-Bad "not a git clone: $RepoDir"
    exit 1
}

$current = (& git -C $RepoDir rev-parse --abbrev-ref HEAD 2>$null)
if (-not $current) {
    Write-Bad "could not read the current branch (is git on PATH?)"
    exit 1
}
Write-Info "branch: $current"

$dirty = (& git -C $RepoDir status --porcelain 2>$null)
$pulled = $false

if ($StatusOnly -or $NoPull) {
    Write-Info "skipping fetch/pull (StatusOnly or NoPull)"
} elseif ($current -ne $Branch) {
    Write-Bad "expected branch '$Branch' but '$current' is checked out -- refusing to pull."
    Write-Info "This guard exists so a v1 update can never land on another lane's"
    Write-Info "branch. Either check out $Branch or pass -Branch $current deliberately."
} elseif ($dirty) {
    Write-Bad "working tree has uncommitted changes -- refusing to pull."
    $dirty | ForEach-Object { Write-Info $_ }
    Write-Info "Commit, or move them aside by hand. This script never stashes."
} else {
    & git -C $RepoDir fetch origin $Branch 2>&1 | Out-Null
    $incoming = (& git -C $RepoDir log --oneline "HEAD..origin/$Branch" 2>$null)
    if (-not $incoming) {
        Write-Ok "already up to date with origin/$Branch"
    } else {
        Write-Info "incoming commits:"
        $incoming | ForEach-Object { Write-Info "  $_" }
        & git -C $RepoDir pull --ff-only origin $Branch 2>&1 |
            ForEach-Object { Write-Info $_ }
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "pulled origin/$Branch"
            $pulled = $true
        } else {
            Write-Bad "pull failed (exit $LASTEXITCODE) -- code on disk unchanged"
        }
    }
}

$head = (& git -C $RepoDir log -1 --format="%h %ad %s" --date=short 2>$null)
Write-Info "HEAD: $head"

# ---------------------------------------------------------------------------
# 2. Restart the watchdog tasks
# ---------------------------------------------------------------------------
$tasks = @(Get-ScheduledTask -TaskName "$taskPrefix*" -ErrorAction SilentlyContinue)

if ($StatusOnly -or $NoRestart) {
    Write-Head "restart (skipped)"
    Write-Info "StatusOnly or NoRestart set -- running processes left alone."
    if ($pulled) {
        Write-Warn2 "new code is on disk but the RUNNING agents are still on the old code."
        Write-Info "They will pick it up at their next restart, or run this again without -NoRestart."
    }
} elseif ($tasks.Count -eq 0) {
    Write-Head "restart"
    Write-Bad "no '$taskPrefix*' scheduled tasks are registered on this machine."
    Write-Info "Register them once with:"
    Write-Info "  powershell -ExecutionPolicy Bypass -File `"$RepoDir\scripts\setup_self_healing.ps1`""
} else {
    Write-Head "restart ($($tasks.Count) watchdog task(s))"
    foreach ($t in $tasks) {
        Stop-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
    }
    # The watchdog loop wraps run_live.py; Stop-ScheduledTask kills the
    # loop but a just-spawned python child can linger a moment.
    Start-Sleep -Seconds 4
    foreach ($t in $tasks) {
        Start-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
        if ($?) { Write-Ok "restarted $($t.TaskName)" }
        else    { Write-Bad "could not restart $($t.TaskName)" }
    }
    Start-Sleep -Seconds 6
}

# ---------------------------------------------------------------------------
# 3. Verify
# ---------------------------------------------------------------------------
Write-Head "verify"

if ($tasks.Count -eq 0) {
    Write-Warn2 "no watchdog tasks to report on"
} else {
    foreach ($t in @(Get-ScheduledTask -TaskName "$taskPrefix*" -ErrorAction SilentlyContinue)) {
        $info = Get-ScheduledTaskInfo -TaskName $t.TaskName -ErrorAction SilentlyContinue
        $last = if ($info) { $info.LastRunTime } else { "?" }
        if ($t.State -eq "Running") { Write-Ok "$($t.TaskName): Running (last start $last)" }
        else { Write-Warn2 "$($t.TaskName): $($t.State) (last start $last)" }
    }
}

$mt5 = @(Get-Process -Name "terminal64" -ErrorAction SilentlyContinue)
if ($mt5.Count -gt 0) { Write-Ok "MT5 terminal running ($($mt5.Count) process(es))" }
else { Write-Bad "MT5 terminal (terminal64.exe) is NOT running -- the agent cannot trade" }

# Kill switch / halt files: the agent writes these, and a stale one is
# the single most common reason for a silent no-trade week.
foreach ($name in @("kill_switch", "kill.txt")) {
    $p = Join-Path $RepoDir $name
    if (Test-Path $p) {
        Write-Bad "$name PRESENT at $p -- trading is halted until it is removed"
    }
}

Write-Head "latest log lines"
if (-not (Test-Path $logRoot)) {
    Write-Warn2 "no log root at $logRoot"
} else {
    foreach ($d in @(Get-ChildItem $logRoot -Directory -ErrorAction SilentlyContinue)) {
        $log = Get-ChildItem (Join-Path $d.FullName "*.log") -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $log) { continue }
        $ageMin = [math]::Round(((Get-Date) - $log.LastWriteTime).TotalMinutes, 1)
        Write-Host ""
        Write-Host "  --- $($d.Name) ($($log.Name), last write ${ageMin}m ago)" -ForegroundColor White
        Get-Content $log.FullName -Tail 4 -ErrorAction SilentlyContinue |
            ForEach-Object { Write-Info $_ }
    }
}

Write-Host ""
Write-Host "Done. Expect an 'Agent ONLINE' Telegram page per symbol within ~1 min of a restart." -ForegroundColor White
Write-Host ""
