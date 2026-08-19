<#
.SYNOPSIS
    Installs short PowerShell commands for both agents so you never type
    a repo path again. Run once per VM (and again only if a clone moves).

.DESCRIPTION
    Writes a marked block into your PowerShell profile defining:

      v1up        pull + restart the v1 trading agent, then verify
      v1status    v1 health report, changes nothing
      v1cd        cd into the v1 clone
      v1log       tail the freshest v1 symbol log

      v2up        pull + restart the v2 squad loop + dashboard, verify
      v2status    v2 health report, changes nothing
      v2cd        cd into the v2 clone
      v2log       tail the v2 squad live log

      agents      both status reports back to back

    Extra switches pass straight through, so `v1up -NoRestart` and
    `v2up -StatusOnly` work as you would expect.

    The block is delimited by markers, so re-running this script
    replaces it rather than stacking duplicates. Nothing else in your
    profile is touched.

.PARAMETER V2Dir
    Path to the v2 (squad/platform) clone. Auto-detected from the usual
    locations when omitted; pass it explicitly if detection fails.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_vm_shortcuts.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_vm_shortcuts.ps1 -V2Dir C:\TradingAgent-platform
#>
param(
    [string]$V1Dir = "",
    [string]$V2Dir = ""
)

$ErrorActionPreference = "Stop"
if (-not $V1Dir) { $V1Dir = Split-Path -Parent $PSScriptRoot }

function Write-Ok([string]$Text)    { Write-Host "  [OK]   $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "  [WARN] $Text" -ForegroundColor Yellow }
function Write-Info([string]$Text)  { Write-Host "         $Text" -ForegroundColor Gray }

Write-Host ""
Write-Host "Installing agent shortcuts into your PowerShell profile" -ForegroundColor White

# --- locate the v1 clone (this script's own repo) ---------------------------
if (-not (Test-Path (Join-Path $V1Dir "scripts\update_agent.ps1"))) {
    Write-Host "  [FAIL] $V1Dir does not look like the v1 clone (no scripts\update_agent.ps1)" -ForegroundColor Red
    exit 1
}
Write-Ok "v1 clone: $V1Dir"

# --- locate the v2 clone ---------------------------------------------------
if (-not $V2Dir) {
    $parent = Split-Path -Parent $V1Dir
    $candidates = @(
        (Join-Path $parent "multi-pair-trading-agent-product"),
        (Join-Path $parent "TradingAgent-platform"),
        (Join-Path $parent "TradingAgent2"),
        "C:\TradingAgent-platform",
        "C:\TradingAgent2",
        (Join-Path $HOME "Documents\GitHub\multi-pair-trading-agent-product"),
        (Join-Path $HOME "Documents\GitHub\TradingAgent2")
    )
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c "scripts\run_squad_live.py")) { $V2Dir = $c; break }
    }
}

if ($V2Dir -and (Test-Path (Join-Path $V2Dir "scripts\run_squad_live.py"))) {
    Write-Ok "v2 clone: $V2Dir"
    if (-not (Test-Path (Join-Path $V2Dir "scripts\update_platform.ps1"))) {
        Write-Warn2 "that clone has no scripts\update_platform.ps1 yet -- pull the product branch there first"
    }
} else {
    Write-Warn2 "v2 clone not found; v2 commands will be installed but will report the missing path"
    Write-Info "Re-run with -V2Dir <path> once you know it."
    if (-not $V2Dir) { $V2Dir = "C:\TradingAgent-platform" }
}

# --- build the profile block ----------------------------------------------
# Single-quoted here-string so nothing expands now; the two path tokens
# are substituted afterwards.
$body = @'
# === trading-agent shortcuts (managed by scripts/install_vm_shortcuts.ps1) ===
$global:V1Dir = '__V1DIR__'
$global:V2Dir = '__V2DIR__'

function v1up    { powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $global:V1Dir 'scripts\update_agent.ps1') @args }
function v1status { v1up -StatusOnly @args }
function v1cd    { Set-Location $global:V1Dir }
function v1log {
    $root = Join-Path $HOME 'Documents\TradingAgentLogs'
    $log = Get-ChildItem (Join-Path $root '*\*.log') -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($log) { Write-Host $log.FullName -ForegroundColor Cyan; Get-Content $log.FullName -Tail 40 -Wait }
    else { Write-Host "no v1 logs under $root" -ForegroundColor Yellow }
}

function v2up    { powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $global:V2Dir 'scripts\update_platform.ps1') @args }
function v2status { v2up -StatusOnly @args }
function v2cd    { Set-Location $global:V2Dir }
function v2log {
    $p = Join-Path $HOME 'Documents\TradingAgentLogs\squad_live'
    $log = Get-ChildItem (Join-Path $p '*.log') -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($log) { Write-Host $log.FullName -ForegroundColor Cyan; Get-Content $log.FullName -Tail 40 -Wait }
    else { Write-Host "no squad log under $p" -ForegroundColor Yellow }
}

function agents { v1status; v2status }
# === end trading-agent shortcuts ===
'@

$body = $body.Replace('__V1DIR__', $V1Dir).Replace('__V2DIR__', $V2Dir)

$startMark = "# === trading-agent shortcuts (managed by scripts/install_vm_shortcuts.ps1) ==="
$endMark   = "# === end trading-agent shortcuts ==="

$profilePath = $PROFILE
$profileDir = Split-Path -Parent $profilePath
if (-not (Test-Path $profileDir)) {
    New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
}

$existing = ""
if (Test-Path $profilePath) {
    $existing = Get-Content $profilePath -Raw -ErrorAction SilentlyContinue
    if ($null -eq $existing) { $existing = "" }
}

if ($existing -like "*$startMark*") {
    # Replace the managed block in place, leave everything else alone.
    $lines = $existing -split "`r?`n"
    $out = New-Object System.Collections.Generic.List[string]
    $inBlock = $false
    $replaced = $false
    foreach ($line in $lines) {
        if ($line -eq $startMark) { $inBlock = $true; continue }
        if ($inBlock) {
            if ($line -eq $endMark) {
                $inBlock = $false
                if (-not $replaced) { $out.Add($body); $replaced = $true }
            }
            continue
        }
        $out.Add($line)
    }
    if (-not $replaced) { $out.Add($body) }
    Set-Content -Path $profilePath -Value ($out -join "`r`n") -Encoding UTF8
    Write-Ok "replaced the existing shortcut block in $profilePath"
} else {
    $sep = if ($existing.Trim()) { "`r`n`r`n" } else { "" }
    Set-Content -Path $profilePath -Value ($existing.TrimEnd() + $sep + $body + "`r`n") -Encoding UTF8
    Write-Ok "appended shortcuts to $profilePath"
}

# A profile only runs in sessions that allow local scripts.
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq "Restricted" -or $policy -eq "Undefined") {
    Write-Warn2 "CurrentUser execution policy is '$policy' -- your profile will not load."
    Write-Info "Fix once with:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"
}

Write-Host ""
Write-Host "Open a NEW PowerShell window (or run: . `$PROFILE) and then just type:" -ForegroundColor White
Write-Host "  v1up        v1status     v1cd    v1log" -ForegroundColor Cyan
Write-Host "  v2up        v2status     v2cd    v2log" -ForegroundColor Cyan
Write-Host "  agents      (both status reports)" -ForegroundColor Cyan
Write-Host ""
