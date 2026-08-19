<#
.SYNOPSIS
    One command to pull the latest v2 squad/platform code on the VM,
    restart the squad loop and the dashboard, then prove it took --
    including whether SAE is actually on the pitch and what equity the
    book is running.

.DESCRIPTION
    Replaces the hand-typed sequence (cd into the second clone, git
    pull, stop tasks, start tasks, hunt the log, guess whether the
    dashboard is listening). The script locates its own repo via
    $PSScriptRoot, so there is no path to remember.

    Same safety rules as the v1 twin (scripts\update_agent.ps1 in the
    trading clone): expected-branch guard (default `product`), refuses
    to pull over uncommitted changes, --ff-only, and -StatusOnly does
    nothing but report.

    The verify step answers the questions that actually matter for v2:
    is the squad loop alive, is the dashboard listening on 8787, is
    sae_enabled true in state.json, what equity is Sentinel R1 sizing
    against, and how stale is the tape.

.PARAMETER StatusOnly
    Report health only. No fetch, no pull, no restart.

.PARAMETER NoPull
    Restart against the code already on disk.

.PARAMETER NoRestart
    Pull only; leave the running loop alone.

.PARAMETER Branch
    Expected branch. Default `product` (the declared v2 lane).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\update_platform.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\update_platform.ps1 -StatusOnly
#>
param(
    [switch]$StatusOnly,
    [switch]$NoPull,
    [switch]$NoRestart,
    [string]$Branch = "product",
    [int]$Port = 8787,
    [string]$RepoDir = ""
)

$ErrorActionPreference = "Continue"
if (-not $RepoDir) { $RepoDir = Split-Path -Parent $PSScriptRoot }

function Write-Head([string]$Text) {
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}
function Write-Ok([string]$Text)    { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Write-Bad([string]$Text)   { Write-Host "  [FAIL] $Text" -ForegroundColor Red }
function Write-Info([string]$Text)  { Write-Host "         $Text" -ForegroundColor Gray }

$liveDir = Join-Path $HOME "Documents\TradingAgentLogs\squad_live"
# Task names as registered by docs\RUNBOOK_demo_launch.md sections 4 + 7,
# plus the aliases actually present on VMs registered before those names
# settled. The dashboard task in particular exists as "PlatformServer" on
# the current VM while the runbook says "PlatformWebUI" -- looking for
# only one of them reported a running dashboard as missing.
# One entry per logical job; the array is the accepted names for it, so
# only a job with NO name present counts as unregistered.
$taskRoles = @(
    @{ Role = "squad loop"; Names = @("SquadLiveRuntime") },
    @{ Role = "dashboard";  Names = @("PlatformWebUI", "PlatformServer") },
    @{ Role = "ops watchdog"; Names = @("OpsWatchdog") },
    @{ Role = "night auditor"; Names = @("NightAuditor") }
)
$taskNames = $taskRoles | ForEach-Object { $_.Names } 

Write-Host ""
Write-Host "v2 squad + platform -- update + restart" -ForegroundColor White
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
    Write-Info "The v2 lane is $Branch. Check it out, or pass -Branch $current deliberately."
} elseif ($dirty) {
    Write-Bad "working tree has uncommitted changes -- refusing to pull."
    $dirty | ForEach-Object { Write-Info $_ }
    Write-Info "Note: platform.toml is expected to be local-only and gitignored."
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
# 2. Restart
# ---------------------------------------------------------------------------
$present = @()
foreach ($n in $taskNames) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($t) { $present += $t }
}

if ($StatusOnly -or $NoRestart) {
    Write-Head "restart (skipped)"
    Write-Info "StatusOnly or NoRestart set -- running processes left alone."
    if ($pulled) {
        Write-Warn2 "new code is on disk but the RUNNING loop is still on the old code."
    }
} elseif ($present.Count -eq 0) {
    Write-Head "restart"
    Write-Bad "none of [$($taskNames -join ', ')] are registered as scheduled tasks."
    Write-Info "Either register them per docs\RUNBOOK_demo_launch.md sections 4 + 7,"
    Write-Info "or run the watchdogs directly in two PowerShell windows:"
    Write-Info "  powershell -ExecutionPolicy Bypass -File `"$RepoDir\scripts\watchdog_squad.ps1`""
    Write-Info "  powershell -ExecutionPolicy Bypass -File `"$RepoDir\scripts\watchdog_platform.ps1`""
} else {
    Write-Head "restart ($($present.Count) task(s))"
    foreach ($t in $present) {
        Stop-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 4
    foreach ($t in $present) {
        Start-ScheduledTask -TaskName $t.TaskName -ErrorAction SilentlyContinue
        if ($?) { Write-Ok "restarted $($t.TaskName)" }
        else    { Write-Bad "could not restart $($t.TaskName)" }
    }
    # The squad loop seeds warm-up bars before it writes state.json.
    Start-Sleep -Seconds 12
}

# ---------------------------------------------------------------------------
# 3. Verify -- the questions that actually matter for v2
# ---------------------------------------------------------------------------
Write-Head "verify"

foreach ($role in $taskRoles) {
    $found = $null
    foreach ($n in $role.Names) {
        $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if ($t) { $found = $t; break }
    }
    if (-not $found) {
        Write-Warn2 "$($role.Role): not registered (looked for $($role.Names -join ' / '))"
        continue
    }
    if ($found.State -eq "Running") { Write-Ok "$($role.Role) [$($found.TaskName)]: Running" }
    else { Write-Warn2 "$($role.Role) [$($found.TaskName)]: $($found.State)" }
}

# Dashboard reachable? This is the localhost:8787 refusal from Aug 10.
$listening = $null
$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Ok "dashboard listening on port $Port"
    Write-Info "http://localhost:$Port/highlights  (and via Tailscale from your phone)"
} else {
    Write-Bad "nothing is listening on port $Port -- the dashboard will refuse connections"
    Write-Info "Start it: powershell -ExecutionPolicy Bypass -File `"$RepoDir\scripts\watchdog_platform.ps1`""
}

# Kill file: watchdog_squad.ps1 stops the loop while this exists.
$killFile = Join-Path $RepoDir "kill.txt"
if (Test-Path $killFile) {
    Write-Bad "kill.txt PRESENT -- the squad loop will stay down until it is deleted"
}

# state.json: is SAE on the pitch, and what equity is R1 sizing against?
$statePath = Join-Path $liveDir "state.json"
if (-not (Test-Path $statePath)) {
    Write-Warn2 "no state.json at $statePath (loop may not have written a tick yet)"
} else {
    $ageMin = [math]::Round(((Get-Date) - (Get-Item $statePath).LastWriteTime).TotalMinutes, 1)
    Write-Info "state.json last write: ${ageMin}m ago"
    try {
        $state = Get-Content $statePath -Raw | ConvertFrom-Json
        if ($state.sae_enabled -eq $true) {
            Write-Ok "sae_enabled = true (SAE is in the lineup)"
        } else {
            Write-Bad "sae_enabled = $($state.sae_enabled) -- SAE is NOT in the lineup"
            Write-Info "watchdog_squad.ps1 passes --enable-sae by default; -NoSae turns it off."
        }
        if ($null -ne $state.equity) {
            Write-Info "equity (Sentinel R1 book): `$$($state.equity)"
        }
        if ($state.per_agent_equity) {
            $books = $state.per_agent_equity.PSObject.Properties |
                ForEach-Object { "$($_.Name)=$([math]::Round([double]$_.Value, 2))" }
            Write-Info "player books: $($books -join '  ')"
        }
    } catch {
        Write-Warn2 "state.json present but could not be parsed: $($_.Exception.Message)"
    }
}

Write-Head "latest tape"
$eventsPath = Join-Path $liveDir "events.jsonl"
if (-not (Test-Path $eventsPath)) {
    Write-Warn2 "no events.jsonl at $eventsPath"
} else {
    $ageMin = [math]::Round(((Get-Date) - (Get-Item $eventsPath).LastWriteTime).TotalMinutes, 1)
    Write-Info "events.jsonl last write: ${ageMin}m ago"
    Get-Content $eventsPath -Tail 5 -ErrorAction SilentlyContinue |
        ForEach-Object {
            $line = $_
            if ($line.Length -gt 220) { $line = $line.Substring(0, 220) + "..." }
            Write-Info $line
        }
}

$squadLog = Get-ChildItem (Join-Path $liveDir "*.log") -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($squadLog) {
    Write-Host ""
    Write-Host "  --- $($squadLog.Name)" -ForegroundColor White
    Get-Content $squadLog.FullName -Tail 6 -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Info $_ }
}

Write-Host ""
Write-Host "Done. The squad is SHADOW-only: it never places broker orders." -ForegroundColor White
Write-Host ""
