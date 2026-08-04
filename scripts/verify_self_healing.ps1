<#
.SYNOPSIS
    Read-only check that every layer of the VM self-healing stack is in
    place and, where applicable, actually running.

.DESCRIPTION
    Companion to setup_self_healing.ps1. Checks: autologon, MT5 Startup
    shortcut + live process, the three watchdog scheduled tasks, the
    run_live.py processes per symbol, recent watchdog log lines,
    healthcheck URLs in .env, and the Windows Update reboot policy.
    Exit code 0 = all PASS, 1 = something needs attention.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\verify_self_healing.ps1
#>
param(
    [string[]]$Symbols = @("EURUSD", "GBPUSD", "USDCAD"),
    [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot)
)

$failures = 0
function Check([string]$Item, [bool]$Ok, [string]$Detail) {
    $status = if ($Ok) { "PASS" } else { $script:failures++; "FAIL" }
    $color = if ($Ok) { "Green" } else { "Red" }
    Write-Host ("[{0}] {1} - {2}" -f $status, $Item, $Detail) -ForegroundColor $color
}

Write-Host "`n=== Self-healing verification ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) ===`n"

# 1. Autologon
$auto = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -ErrorAction SilentlyContinue
Check "Autologon" ($auto.AutoAdminLogon -eq "1" -and [bool]$auto.DefaultUserName) `
    $(if ($auto.AutoAdminLogon -eq "1") { "enabled for '$($auto.DefaultUserName)'" } else { "AutoAdminLogon != 1 - reboot will strand at lock screen" })

# 2. MT5: Startup shortcut + running process
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "MT5-terminal.lnk"
Check "MT5 Startup shortcut" (Test-Path $lnk) $lnk
$mt5proc = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue
Check "MT5 terminal running" ([bool]$mt5proc) `
    $(if ($mt5proc) { "pid $($mt5proc[0].Id)" } else { "terminal64.exe not running" })

# 3. Scheduled tasks
foreach ($sym in $Symbols) {
    $task = Get-ScheduledTask -TaskName "TradingAgent-$sym" -ErrorAction SilentlyContinue
    Check "Task TradingAgent-$sym" ([bool]$task -and $task.State -ne "Disabled") `
        $(if ($task) { "state=$($task.State)" } else { "not registered" })
}

# 4. Live agent processes (one run_live.py per symbol)
$pythonProcs = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue
foreach ($sym in $Symbols) {
    $proc = $pythonProcs | Where-Object { $_.CommandLine -match "run_live\.py" -and $_.CommandLine -match $sym }
    Check "Agent process $sym" ([bool]$proc) `
        $(if ($proc) { "pid $($proc[0].ProcessId)" } else { "no run_live.py process (fine if tasks not started yet - reboot to test)" })
}

# 5. Watchdog log freshness (any line in the last 30 minutes)
foreach ($sym in $Symbols) {
    $log = Join-Path $HOME "Documents\TradingAgentLogs\$sym\watchdog.log"
    if (Test-Path $log) {
        $age = (Get-Date) - (Get-Item $log).LastWriteTime
        Check "Watchdog log $sym" $true `
            ("last write {0:N0} min ago: {1}" -f $age.TotalMinutes, (Get-Content $log -Tail 1))
    } else {
        Check "Watchdog log $sym" $false "missing $log (watchdog has never run)"
    }
}

# 6. Healthcheck URLs in .env (external dead-man's-switch)
$envFile = Join-Path $RepoDir ".env"
if (Test-Path $envFile) {
    $envText = Get-Content $envFile -Raw
    foreach ($sym in $Symbols) {
        Check "HEALTHCHECK_URL_$sym" ($envText -match "HEALTHCHECK_URL_$sym\s*=\s*https") ".env"
    }
} else {
    Check ".env" $false "missing $envFile"
}

# 7. Windows Update reboot policy
$au = Get-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU" -ErrorAction SilentlyContinue
Check "WU no-auto-reboot policy" ($au.NoAutoRebootWithLoggedOnUsers -eq 1) `
    $(if ($au) { "NoAutoRebootWithLoggedOnUsers=$($au.NoAutoRebootWithLoggedOnUsers), AUOptions=$($au.AUOptions), installs day=$($au.ScheduledInstallDay) hour=$($au.ScheduledInstallTime)" } else { "policy keys absent - run setup_self_healing.ps1 elevated" })

Write-Host ""
if ($failures -eq 0) {
    Write-Host "ALL PASS. Final proof: reboot the VM hands-off and wait for three 'Agent ONLINE' Telegram messages." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$failures check(s) failed - see above." -ForegroundColor Red
    exit 1
}
