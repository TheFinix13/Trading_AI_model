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
    powershell -ExecutionPolicy Bypass -File scripts\install_vm_shortcuts.ps1 -V2Dir C:\Users\Fiyin\Documents\GitHub\TradingAgent2
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
# C:\TradingAgent-platform is DELIBERATELY absent from this list. It is
# the retired clone that silently broke the Night Auditor: the task fired
# on schedule, found stale code, and failed with nobody watching. An old
# copy of it may still be on disk, so auto-detecting it would resurrect
# exactly that incident. If it is genuinely the clone you want, pass
# -V2Dir explicitly and take the warning below.
$staleV2 = "C:\TradingAgent-platform"
if (-not $V2Dir) {
    $parent = Split-Path -Parent $V1Dir
    $candidates = @(
        (Join-Path $parent "TradingAgent2"),
        (Join-Path $parent "multi-pair-trading-agent-product"),
        (Join-Path $HOME "Documents\GitHub\TradingAgent2"),
        (Join-Path $HOME "Documents\GitHub\multi-pair-trading-agent-product"),
        "C:\TradingAgent2"
    )
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c "scripts\run_squad_live.py")) { $V2Dir = $c; break }
    }
}
if ($V2Dir -and ($V2Dir.TrimEnd('\') -ieq $staleV2.TrimEnd('\'))) {
    Write-Warn2 "$staleV2 is the RETIRED v2 clone -- this is the path that"
    Write-Info  "silently broke the Night Auditor. Expected:"
    Write-Info  "  C:\Users\Fiyin\Documents\GitHub\TradingAgent2"
}

if ($V2Dir -and (Test-Path (Join-Path $V2Dir "scripts\run_squad_live.py"))) {
    Write-Ok "v2 clone: $V2Dir"
    if (-not (Test-Path (Join-Path $V2Dir "scripts\update_platform.ps1"))) {
        Write-Warn2 "that clone has no scripts\update_platform.ps1 yet -- pull the product branch there first"
    }
} else {
    Write-Warn2 "v2 clone not found; v2 commands will be installed but will report the missing path"
    Write-Info "Re-run with -V2Dir <path> once you know it."
    if (-not $V2Dir) { $V2Dir = "C:\Users\Fiyin\Documents\GitHub\TradingAgent2" }
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

# Reports. Both run from the right clone with the right python, so no cd
# and no venv path. Extra flags pass through:
#   v1report -Days 14
#   v1report -Start 2026-07-08 -End 2026-07-14
#   v1report -Days 7 -Symbols EURUSD,GBPUSD
#   v2report -Days 10
function __agentPython([string]$dir) {
    $venv = Join-Path $dir '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    return 'python'
}
function v1report {
    param([int]$Days = 7, [string]$Start = '', [string]$End = '',
          [string]$Symbols = '', [string]$Out = '')
    $py = __agentPython $global:V1Dir
    $a = @('scripts\weekly_report.py')
    if ($Start -and $End) { $a += @('--start', $Start, '--end', $End) }
    else                  { $a += @('--days', "$Days") }
    if ($Symbols) { $a += @('--symbols', $Symbols) }
    if ($Out)     { $a += @('--out', $Out) }
    Push-Location $global:V1Dir
    try { & $py @a } finally { Pop-Location }
}
function v2report {
    param([int]$Days = 7, [string]$Start = '', [string]$End = '', [string]$Out = '')
    $py = __agentPython $global:V2Dir
    $a = @('scripts\weekly_squad_report.py')
    if ($Start -and $End) { $a += @('--start', $Start, '--end', $End) }
    else                  { $a += @('--days', "$Days") }
    if ($Out) { $a += @('--out', $Out) }
    Push-Location $global:V2Dir
    try { & $py @a } finally { Pop-Location }
}

# Dashboard, token included. The install token lives in the Windows
# credential store (keyring namespace "bluelock"), NOT in platform.toml,
# so ask the platform's own loader for it rather than grepping config.
function v2web {
    param([int]$Port = 8787)
    $py = __agentPython $global:V2Dir
    $tok = ''
    Push-Location $global:V2Dir
    try {
        # No quotes inside the -c payload: PS 5.1 mangles embedded quotes
        # when passing args to native commands. Prints "0" for no token.
        $raw = (& $py -c "from agent.platform.auth import load_install_token as t; print(t() or 0)" 2>$null)
        $raw = "$raw".Trim()
        if ($raw -and $raw -ne '0' -and $raw -ne 'None') { $tok = $raw }
    } catch { $tok = '' }
    finally { Pop-Location }
    $url = if ($tok) { "http://localhost:${Port}/v2?token=$tok" }
           else       { "http://localhost:${Port}/v2" }
    if (-not $tok) {
        Write-Host "no install token found - opening untokenised (fine on localhost)" -ForegroundColor Yellow
    }
    Write-Host $url -ForegroundColor Cyan
    Start-Process $url
}

function agenthelp {
    Write-Host ""
    Write-Host "v1 (live trading agent, branch main)" -ForegroundColor White
    Write-Host "  v1status              health report, changes nothing"
    Write-Host "  v1up                  pull + restart watchdogs + verify"
    Write-Host "  v1report [-Days 14]   weekly report zip"
    Write-Host "  v1log / v1cd          tail freshest log / cd to clone"
    Write-Host ""
    Write-Host "v2 (squad + dashboard, branch product)" -ForegroundColor White
    Write-Host "  v2status              health report, changes nothing"
    Write-Host "  v2up                  pull + restart squad/dashboard + verify"
    Write-Host "  v2report [-Days 10]   weekly squad report zip"
    Write-Host "  v2web                 open the dashboard with its token"
    Write-Host "  v2log / v2cd          tail squad log / cd to clone"
    Write-Host ""
    Write-Host "both" -ForegroundColor White
    Write-Host "  agents                v1status then v2status"
    Write-Host ""
    Write-Host "one-time only (already done unless a clone moved):" -ForegroundColor Gray
    Write-Host "  v1: scripts\setup_self_healing.ps1     (registers 3 symbol tasks)"
    Write-Host "  v2: scripts\setup_platform_tasks.ps1   (registers the 4 v2 tasks)"
    Write-Host ""
}
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
