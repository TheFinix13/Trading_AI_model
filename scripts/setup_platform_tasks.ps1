<#
.SYNOPSIS
    One-shot, idempotent registration of every v2 scheduled task: squad
    loop, dashboard, ops watchdog, night auditor. The v2 twin of the
    trading clone's scripts\setup_self_healing.ps1.

.DESCRIPTION
    Until now v1 had a one-command task setup and v2 did not -- v2's four
    tasks were registered by hand from separate runbook sections, which is
    why the VM ended up with the dashboard task named "PlatformServer"
    while the runbook said "PlatformWebUI", and why a NightAuditor got
    registered against C:\TradingAgent-platform (a clone path that no
    longer holds the pulled code, so it failed silently every morning).

    Every task is registered against THIS clone, resolved from
    $PSScriptRoot. There is no path to type and no path to get wrong.
    Re-running is safe: -Force re-registers in place.

    Run as the normal interactive user. No elevation needed -- unlike the
    v1 script, nothing here writes HKLM (the Windows Update reboot policy
    is machine-wide and already set by the v1 setup; it is not repeated).

    After this, the only command you need is scripts\update_platform.ps1
    (or `v2up`), which stops and starts whatever is registered.

.PARAMETER Port
    Dashboard port. Default 8787.

.PARAMETER BindHost
    Dashboard bind address. Default 0.0.0.0 so Tailscale clients (your
    phone) can reach it; 127.0.0.1 restricts it to the VM itself.

.PARAMETER NoSae
    Register the squad loop WITHOUT --enable-sae. Default is Aoshi ON,
    matching watchdog_squad.ps1's own default (an observability decision
    -- Phase AE's FAIL verdict on his trades stands).

.PARAMETER SkipNightAuditor
    Don't register the 06:30 daily tape audit.

.EXAMPLE
    cd C:\Users\Fiyin\Documents\GitHub\TradingAgent2
    powershell -ExecutionPolicy Bypass -File scripts\setup_platform_tasks.ps1

.EXAMPLE
    # then confirm, and from then on only ever need this:
    powershell -ExecutionPolicy Bypass -File scripts\update_platform.ps1 -StatusOnly
#>
param(
    [int]$Port = 8787,
    [string]$BindHost = "0.0.0.0",
    [switch]$NoSae,
    [switch]$SkipNightAuditor,
    [string]$RepoDir = ""
)

$ErrorActionPreference = "Continue"
if (-not $RepoDir) { $RepoDir = Split-Path -Parent $PSScriptRoot }

$results = @()
function Add-Result([string]$Item, [string]$Status, [string]$Detail) {
    $script:results += [pscustomobject]@{ Item = $Item; Status = $Status; Detail = $Detail }
    $color = switch ($Status) { "OK" { "Green" } "WARN" { "Yellow" } default { "Red" } }
    Write-Host ("[{0,-4}] {1} - {2}" -f $Status, $Item, $Detail) -ForegroundColor $color
}

Write-Host "`n=== v2 platform task setup (repo: $RepoDir) ===`n"

# ---------------------------------------------------------------------------
# 0. Sanity: is this actually the platform clone, on the right branch, with
#    a venv? A task registered against the wrong clone fails silently.
# ---------------------------------------------------------------------------
if (-not (Test-Path (Join-Path $RepoDir "scripts\run_squad_live.py"))) {
    Add-Result "Clone check" "FAIL" ("$RepoDir does not contain scripts\run_squad_live.py " +
        "-- this is not the v2 platform clone. Run this script from inside it.")
    $results | Format-Table -AutoSize
    exit 1
}
Add-Result "Clone check" "OK" "run_squad_live.py present"

$branch = (& git -C $RepoDir branch --show-current 2>$null)
if ($branch -eq "product") {
    Add-Result "Branch" "OK" "product"
} else {
    Add-Result "Branch" "WARN" ("on '$branch', expected 'product' (the declared v2 lane). " +
        "Tasks will still register, but update_platform.ps1 will refuse to pull.")
}

$venvPython = Join-Path $RepoDir ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Add-Result "venv" "OK" $venvPython
} else {
    Add-Result "venv" "WARN" ("no .venv at $venvPython -- the watchdogs fall back to " +
        "system python, but run_watchdog/night_audit tasks below are registered " +
        "against the venv path and will fail until it exists.")
}

# ---------------------------------------------------------------------------
# Shared settings. ExecutionTimeLimit zero = never kill a long-running
# loop; StartWhenAvailable catches a missed trigger after a VM outage.
# ---------------------------------------------------------------------------
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

function Register-LoopTask {
    param(
        [string]$TaskName,
        [string]$ScriptRelPath,
        [string]$ExtraArgs = "",
        [string]$DelaySeconds = "PT60S",
        [string]$Description
    )
    try {
        $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden " +
               "-File `"$RepoDir\$ScriptRelPath`""
        if ($ExtraArgs) { $arg += " $ExtraArgs" }
        $action = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument $arg -WorkingDirectory $RepoDir
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $trigger.Delay = $DelaySeconds
        Register-ScheduledTask -TaskName $TaskName -Action $action `
            -Trigger $trigger -Settings $settings -Principal $principal `
            -Description $Description -Force | Out-Null
        Add-Result "Task $TaskName" "OK" "AtLogOn +$DelaySeconds, self-restarting loop"
        return $true
    } catch {
        Add-Result "Task $TaskName" "FAIL" $_.Exception.Message
        return $false
    }
}

# ---------------------------------------------------------------------------
# 1. Squad runtime. 90s delay: MT5 must be logged in before the feed
#    connects, and v1's own agents start at +45s.
# ---------------------------------------------------------------------------
$saeArgs = if ($NoSae) { "-NoSae" } else { "" }
Register-LoopTask -TaskName "SquadLiveRuntime" `
    -ScriptRelPath "scripts\watchdog_squad.ps1" `
    -ExtraArgs $saeArgs -DelaySeconds "PT90S" `
    -Description "v2 squad shadow loop (watchdog-wrapped, restarts on crash)" | Out-Null
if ($NoSae) {
    Add-Result "Aoshi (event striker)" "WARN" "-NoSae passed: he is NOT in the lineup"
} else {
    Add-Result "Aoshi (event striker)" "OK" ("in the lineup (--enable-sae). Observability " +
        "decision -- Phase AE's FAIL on his event trades stands unrevised.")
}

# ---------------------------------------------------------------------------
# 2. Dashboard. The Aug 10 localhost:8787 refusal was this having no
#    restarter at all. Registered under the runbook's canonical name; any
#    pre-existing PlatformServer task is retired so they can't both bind.
# ---------------------------------------------------------------------------
$legacyDash = Get-ScheduledTask -TaskName "PlatformServer" -ErrorAction SilentlyContinue
if ($legacyDash) {
    try {
        Stop-ScheduledTask -TaskName "PlatformServer" -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName "PlatformServer" -Confirm:$false
        Add-Result "Legacy PlatformServer" "OK" ("stopped and removed -- superseded by " +
            "PlatformWebUI; two tasks on port $Port would fight")
    } catch {
        Add-Result "Legacy PlatformServer" "WARN" ("could not remove: $($_.Exception.Message). " +
            "Remove it by hand or the two will race for port $Port.")
    }
}
Register-LoopTask -TaskName "PlatformWebUI" `
    -ScriptRelPath "scripts\watchdog_platform.ps1" `
    -ExtraArgs "-BindHost $BindHost -Port $Port" -DelaySeconds "PT60S" `
    -Description "v2 dashboard on ${BindHost}:${Port} (watchdog-wrapped)" | Out-Null
if ($BindHost -eq "0.0.0.0") {
    Add-Result "Dashboard reach" "OK" ("bound 0.0.0.0:$Port -- reachable over Tailscale " +
        "from your phone, not just inside the VM")
} else {
    Add-Result "Dashboard reach" "WARN" ("bound ${BindHost}:$Port -- VM-only. Use " +
        "-BindHost 0.0.0.0 to reach it over Tailscale.")
}

# ---------------------------------------------------------------------------
# 3. Ops watchdog (7-check registry, --loop 300). Python directly, not a
#    .ps1 wrapper -- it has its own loop.
# ---------------------------------------------------------------------------
try {
    $action = New-ScheduledTaskAction -Execute $venvPython `
        -Argument "scripts\run_watchdog.py --loop 300" -WorkingDirectory $RepoDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $trigger.Delay = "PT120S"
    Register-ScheduledTask -TaskName "OpsWatchdog" -Action $action `
        -Trigger $trigger -Settings $settings -Principal $principal `
        -Description "v2 ops watchdog: 7-check health registry every 5 min" -Force | Out-Null
    Add-Result "Task OpsWatchdog" "OK" "AtLogOn +PT120S, --loop 300"
} catch {
    Add-Result "Task OpsWatchdog" "FAIL" $_.Exception.Message
}

# ---------------------------------------------------------------------------
# 4. Night auditor, 06:30 daily. Observe-and-draft only.
# ---------------------------------------------------------------------------
if ($SkipNightAuditor) {
    Add-Result "Task NightAuditor" "WARN" "skipped (-SkipNightAuditor)"
} else {
    try {
        $action = New-ScheduledTaskAction -Execute $venvPython `
            -Argument "scripts\night_audit.py" -WorkingDirectory $RepoDir
        $trigger = New-ScheduledTaskTrigger -Daily -At 6:30am
        Register-ScheduledTask -TaskName "NightAuditor" -Action $action `
            -Trigger $trigger -Settings $settings -Principal $principal `
            -Description "Daily squad tape audit (observe-and-draft; digest + ops Telegram line)" `
            -Force | Out-Null
        Add-Result "Task NightAuditor" "OK" "daily 06:30, working dir $RepoDir"
    } catch {
        Add-Result "Task NightAuditor" "FAIL" $_.Exception.Message
    }
}

# ---------------------------------------------------------------------------
# 5. Prove every registered action points at THIS clone. This is the check
#    that would have caught the C:\TradingAgent-platform night-auditor.
# ---------------------------------------------------------------------------
Write-Host ""
foreach ($n in @("SquadLiveRuntime", "PlatformWebUI", "OpsWatchdog", "NightAuditor")) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $t) { continue }
    $wd = ($t.Actions | Select-Object -First 1).WorkingDirectory
    $ex = ($t.Actions | Select-Object -First 1).Execute
    if ($wd -and ($wd.TrimEnd('\') -ieq $RepoDir.TrimEnd('\'))) {
        Add-Result "$n -> clone" "OK" "$wd"
    } else {
        Add-Result "$n -> clone" "FAIL" ("points at '$wd' (exec '$ex'), NOT $RepoDir " +
            "-- it will run stale code or fail silently. Re-run this script.")
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host "`n=== Summary ==="
$results | Format-Table -AutoSize
Write-Host @"
Start them now without a reboot:
  Start-ScheduledTask SquadLiveRuntime
  Start-ScheduledTask PlatformWebUI
  Start-ScheduledTask OpsWatchdog

Then verify (and from now on this is the ONLY v2 command you need):
  powershell -ExecutionPolicy Bypass -File scripts\update_platform.ps1 -StatusOnly

The real proof is a reboot with hands off: the squad loop, the dashboard
on :$Port and the ops watchdog should all come back by themselves.
"@
if ($results | Where-Object { $_.Status -eq "FAIL" }) { exit 1 } else { exit 0 }
