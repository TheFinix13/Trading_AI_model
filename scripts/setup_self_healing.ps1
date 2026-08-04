<#
.SYNOPSIS
    One-shot, idempotent VM self-healing setup: autologon check, MT5 in
    Startup, one watchdog Task Scheduler task per symbol, and a
    trading-aware Windows Update reboot policy.

.DESCRIPTION
    Automates every step of docs/08-live-trading-and-deployment.md
    "Running 24/5" in a single run. Safe to re-run: existing tasks are
    re-registered (-Force), existing shortcuts/registry values are left
    or overwritten with the same values.

    Run from an elevated PowerShell for the Windows Update policy step
    (HKLM writes); everything else works as the normal interactive user.

.EXAMPLE
    cd $HOME\Documents\GitHub\multi-pair-trading-agent
    powershell -ExecutionPolicy Bypass -File scripts\setup_self_healing.ps1

    # then verify:
    powershell -ExecutionPolicy Bypass -File scripts\verify_self_healing.ps1
    # then reboot and confirm 3x "Agent ONLINE" on Telegram, hands-off.
#>
param(
    [string[]]$Symbols = @("EURUSD", "GBPUSD", "USDCAD"),
    [string]$RepoDir = $(Split-Path -Parent $PSScriptRoot)
)

$results = @()
function Add-Result([string]$Item, [string]$Status, [string]$Detail) {
    $script:results += [pscustomobject]@{ Item = $Item; Status = $Status; Detail = $Detail }
    $color = switch ($Status) { "OK" { "Green" } "WARN" { "Yellow" } default { "Red" } }
    Write-Host ("[{0,-4}] {1} - {2}" -f $Status, $Item, $Detail) -ForegroundColor $color
}

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Host "`n=== VM self-healing setup (repo: $RepoDir) ===`n"

# ---------------------------------------------------------------------------
# 1. Autologon (detect only -- passwords belong in Sysinternals Autologon,
#    which stores them as an LSA secret, not plaintext registry)
# ---------------------------------------------------------------------------
$winlogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
$auto = (Get-ItemProperty -Path $winlogon -ErrorAction SilentlyContinue)
if ($auto.AutoAdminLogon -eq "1" -and $auto.DefaultUserName) {
    Add-Result "Autologon" "OK" "enabled for '$($auto.DefaultUserName)'"
} else {
    Add-Result "Autologon" "WARN" ("NOT enabled - run Sysinternals Autologon " +
        "(https://learn.microsoft.com/sysinternals/downloads/autologon) once, " +
        "enter this account's password, click Enable. Without it a reboot " +
        "parks the VM at the lock screen and nothing below can start.")
}

# ---------------------------------------------------------------------------
# 2. MT5 terminal in the Startup folder
# ---------------------------------------------------------------------------
$mt5 = $null
$running = Get-Process -Name "terminal64" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($running) { $mt5 = $running.Path }
if (-not $mt5) {
    $candidates = @(
        "C:\Program Files\MetaTrader 5\terminal64.exe"
    ) + (Get-ChildItem "C:\Program Files" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "MetaTrader|Exness|MT5" } |
        ForEach-Object { Join-Path $_.FullName "terminal64.exe" })
    $mt5 = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ($mt5) {
    $startup = [Environment]::GetFolderPath("Startup")
    $lnk = Join-Path $startup "MT5-terminal.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = $mt5
    $sc.WorkingDirectory = Split-Path -Parent $mt5
    $sc.Save()
    Add-Result "MT5 in Startup" "OK" "$lnk -> $mt5"
} else {
    Add-Result "MT5 in Startup" "FAIL" ("terminal64.exe not found (searched Program Files + running processes). " +
        "Create the Startup shortcut manually: Win+R -> shell:startup")
}

# ---------------------------------------------------------------------------
# 3. Watchdog scheduled tasks (one per symbol, exactly per docs/08)
# ---------------------------------------------------------------------------
foreach ($sym in $Symbols) {
    try {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RepoDir\scripts\watchdog_agent.ps1`" -Symbol $sym" `
            -WorkingDirectory $RepoDir
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $trigger.Delay = "PT45S"   # give MT5 time to log in first
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -ExecutionTimeLimit ([TimeSpan]::Zero)
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
            -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName "TradingAgent-$sym" -Action $action `
            -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        Add-Result "Task TradingAgent-$sym" "OK" "AtLogOn + 45s delay, infinite watchdog loop"
    } catch {
        Add-Result "Task TradingAgent-$sym" "FAIL" $_.Exception.Message
    }
}

# ---------------------------------------------------------------------------
# 4. Windows Update reboot policy (likely root cause of the recurring VM
#    deaths). Weekend-only installs + never auto-reboot while logged on
#    (autologon means someone is ALWAYS logged on).
# ---------------------------------------------------------------------------
if ($isAdmin) {
    try {
        $au = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
        New-Item -Path $au -Force | Out-Null
        Set-ItemProperty -Path $au -Name "NoAutoRebootWithLoggedOnUsers" -Value 1 -Type DWord
        Set-ItemProperty -Path $au -Name "NoAutoUpdate" -Value 0 -Type DWord
        Set-ItemProperty -Path $au -Name "AUOptions" -Value 4 -Type DWord            # auto download + scheduled install
        Set-ItemProperty -Path $au -Name "ScheduledInstallDay" -Value 7 -Type DWord  # Saturday
        Set-ItemProperty -Path $au -Name "ScheduledInstallTime" -Value 22 -Type DWord # 22:00 local (market closed)
        Add-Result "Windows Update policy" "OK" "install Sat 22:00 only; no auto-reboot while logged on"
    } catch {
        Add-Result "Windows Update policy" "FAIL" $_.Exception.Message
    }
} else {
    Add-Result "Windows Update policy" "WARN" "skipped - re-run this script in an ELEVATED PowerShell to set it (HKLM write)"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host "`n=== Summary ==="
$results | Format-Table -AutoSize
Write-Host @"
Next steps:
  1. Fix any WARN/FAIL above (autologon is the critical one).
  2. Run: powershell -ExecutionPolicy Bypass -File scripts\verify_self_healing.ps1
  3. Reboot the VM and touch NOTHING. Within ~2 minutes you should get
     three 'Agent ONLINE' Telegram messages. That reboot test is the
     only proof that counts.
"@
if ($results | Where-Object { $_.Status -eq "FAIL" }) { exit 1 } else { exit 0 }
