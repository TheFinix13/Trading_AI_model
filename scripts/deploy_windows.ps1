# Multi-Pair Trading Agent — Windows setup
# Run from an OPEN PowerShell window (do not double-click — the window will close on error).
#
#   cd C:\Users\Fiyin\Documents\GitHub\multi-pair-trading-agent
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\deploy_windows.ps1
#
param(
    [string]$RepoPath = ""
)

$ErrorActionPreference = "Continue"

function Write-Step([string]$Message, [string]$Color = "White") {
    Write-Host $Message -ForegroundColor $Color
}

function Pause-ForUser {
    Write-Host ""
    Read-Host "Press Enter to close this window"
}

function Resolve-RepoDir {
    param([string]$Requested)

    if ($Requested -and (Test-Path (Join-Path $Requested "pyproject.toml"))) {
        return (Resolve-Path $Requested).Path
    }

    $candidates = @(
        (Join-Path $PSScriptRoot ".."),
        "$HOME\Documents\GitHub\multi-pair-trading-agent",
        "$HOME\Documents\multi-pair-trading-agent",
        (Get-Location).Path
    )

    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        try {
            $resolved = Resolve-Path $candidate -ErrorAction SilentlyContinue
        } catch {
            continue
        }
        if (-not $resolved) { continue }
        $dir = $resolved.Path
        if (Test-Path (Join-Path $dir "pyproject.toml")) {
            return $dir
        }
    }

    return ""
}

function Install-Dependencies {
    param(
        [string]$VenvPython,
        [string]$VenvPip
    )

    Write-Step "~ Upgrading pip..." "Yellow"
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed (exit $LASTEXITCODE)"
    }

    Write-Step "~ Installing project + MT5 support (2-5 min, output shown)..." "Yellow"
    & $VenvPip install -e ".[mt5]"
    if ($LASTEXITCODE -ne 0) {
        Write-Step "  Retrying without editable install..." "Yellow"
        & $VenvPip install ".[mt5]"
        if ($LASTEXITCODE -ne 0) {
            throw "Package installation failed (exit $LASTEXITCODE). See errors above."
        }
    }
}

try {
    Write-Host ""
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host "  Multi-Pair Trading Agent - Windows Setup" -ForegroundColor Cyan
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host ""

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Step "! Python not found." "Yellow"
        Write-Step "  Install Python 3.11+ from https://www.python.org/downloads/" "White"
        Write-Step "  Check 'Add Python to PATH', restart PowerShell, run this script again." "White"
        Pause-ForUser
        exit 1
    }
    Write-Step "OK Python: $(python --version)" "Green"

    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        Write-Step "OK Git: $(git --version)" "Green"
    } else {
        Write-Step "! Git not in PATH (optional if repo is already cloned)" "Yellow"
    }

    $repoDir = Resolve-RepoDir -Requested $RepoPath
    if (-not $repoDir) {
        $defaultClone = "$HOME\Documents\GitHub\multi-pair-trading-agent"
        if (-not $git) {
            Write-Step "X Cannot find repo (no pyproject.toml) and Git is missing." "Red"
            Write-Step "  Clone manually or pass: .\scripts\deploy_windows.ps1 -RepoPath 'C:\path\to\multi-pair-trading-agent'" "White"
            Pause-ForUser
            exit 1
        }
        Write-Step "~ Cloning repo to $defaultClone ..." "Yellow"
        $parent = Split-Path $defaultClone -Parent
        if (-not (Test-Path $parent)) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        git clone https://github.com/TheFinix13/Trading_AI_model.git $defaultClone
        if ($LASTEXITCODE -ne 0) {
            throw "git clone failed (exit $LASTEXITCODE)"
        }
        $repoDir = $defaultClone
    } else {
        Write-Step "OK Using repo: $repoDir" "Green"
        if ($git) {
            Push-Location $repoDir
            git pull origin main 2>&1 | Out-Null
            Pop-Location
        }
    }

    Set-Location $repoDir
    Write-Step "  Working directory: $(Get-Location)" "Gray"

    if (-not (Test-Path ".venv")) {
        Write-Step "~ Creating virtual environment..." "Yellow"
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Virtual environment creation failed (exit $LASTEXITCODE)"
        }
    }

    $venvPython = Join-Path $repoDir ".venv\Scripts\python.exe"
    $venvPip = Join-Path $repoDir ".venv\Scripts\pip.exe"
    if (-not (Test-Path $venvPython)) {
        throw "Missing $venvPython after venv create"
    }

    Install-Dependencies -VenvPython $venvPython -VenvPip $venvPip
    Write-Step "OK Dependencies installed" "Green"

    if (-not (Test-Path ".env")) {
        Write-Host ""
        Write-Host "===========================================================" -ForegroundColor Red
        Write-Host "  Exness MT5 credentials (demo account)" -ForegroundColor Red
        Write-Host "===========================================================" -ForegroundColor Red
        Write-Host ""
        $login = Read-Host "  MT5 Login (numbers only)"
        $password = Read-Host "  MT5 Password"
        $server = Read-Host "  MT5 Server (e.g. Exness-MT5Trial9)"

        @"
# Multi-Pair Trading Agent
MT5_LOGIN=$login
MT5_PASSWORD=$password
MT5_SERVER=$server
"@ | Out-File -FilePath ".env" -Encoding utf8

        Write-Step "OK .env created" "Green"
    } else {
        Write-Step "OK .env already exists" "Green"
    }

    if (-not (Test-Path "models")) {
        New-Item -ItemType Directory -Path "models" | Out-Null
    }
    if (-not (Test-Path "data\parquet")) {
        New-Item -ItemType Directory -Path "data\parquet" -Force | Out-Null
    }
    Write-Step "OK data/models folders ready" "Green"

    Write-Host ""
    Write-Step "~ Testing MT5 connection (MT5 must be OPEN and logged in)..." "Yellow"
    $env:PYTHONPATH = "."

    $mt5Test = @'
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError as exc:
    print(f"! dotenv import failed: {exc}")
    sys.exit(1)

try:
    import MetaTrader5 as mt5
except ImportError as exc:
    print(f"! MetaTrader5 import failed: {exc}")
    sys.exit(1)

login_str = os.getenv("MT5_LOGIN", "").strip()
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not login_str:
    print("! MT5_LOGIN not set in .env")
    sys.exit(0)

login = int(login_str)

if not mt5.initialize():
    print("! MT5 init failed - open Exness MT5 and log into demo, then retry")
    sys.exit(1)

info = mt5.account_info()
if info and info.login == login:
  print(f"OK Already logged in: {info.login} balance={info.balance:.2f} server={info.server}")
  mt5.shutdown()
  sys.exit(0)

if mt5.login(login, password=password, server=server):
    info = mt5.account_info()
    print(f"OK Connected: {info.login} balance={info.balance:.2f} server={info.server}")
else:
    print(f"! Login failed: {mt5.last_error()}")
    print("  Check MT5_SERVER spelling and that MT5 terminal is open")

mt5.shutdown()
'@

    & $venvPython -c $mt5Test

    Write-Host ""
    Write-Host "===========================================================" -ForegroundColor Green
    Write-Host "  SETUP COMPLETE" -ForegroundColor Green
    Write-Host "===========================================================" -ForegroundColor Green
    Write-Host ""
    Write-Step "  Repo: $repoDir" "Cyan"
    Write-Host ""
    Write-Step "  Next commands (copy/paste):" "Cyan"
    Write-Host "    cd `"$repoDir`"" -ForegroundColor Gray
    Write-Host "    .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
    Write-Host "    python scripts/run_live.py --broker paper --timeframe H1 --lot 0.01" -ForegroundColor Gray
    Write-Host "    python scripts/run_live.py --broker mt5 --timeframe H1 --lot 0.01" -ForegroundColor Gray
    Write-Host ""
}
catch {
    Write-Host ""
    Write-Step "X SETUP FAILED" "Red"
    Write-Step $_.Exception.Message "Red"
    if ($_.ScriptStackTrace) {
        Write-Step $_.ScriptStackTrace "DarkGray"
    }
    Write-Host ""
    Write-Step "Manual setup (same folder):" "Yellow"
    Write-Host "  cd C:\Users\Fiyin\Documents\GitHub\multi-pair-trading-agent" -ForegroundColor Gray
    Write-Host "  python -m venv .venv" -ForegroundColor Gray
    Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
    Write-Host "  pip install -e `".[mt5]`"" -ForegroundColor Gray
    Write-Host ""
    exit 1
}
finally {
    Pause-ForUser
}
