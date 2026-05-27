# ═══════════════════════════════════════════════════════════════
# EURUSD AI Agent — Windows Deployment Script
# Run in PowerShell (as Administrator recommended)
# ═══════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  EURUSD AI Trading Agent — Windows Setup" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ── 1. Check Python ──────────────────────────────────────────
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "[!] Python not found. Installing Python 3.11..." -ForegroundColor Yellow
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Host "[X] Python install failed. Please install Python 3.11+ manually from python.org" -ForegroundColor Red
        exit 1
    }
}
Write-Host "[OK] Python: $(python --version)" -ForegroundColor Green

# ── 2. Check Git ─────────────────────────────────────────────
$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "[!] Git not found. Installing Git..." -ForegroundColor Yellow
    winget install Git.Git --accept-package-agreements --accept-source-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Host "[X] Git install failed. Please install Git manually from git-scm.com" -ForegroundColor Red
        exit 1
    }
}
Write-Host "[OK] Git: $(git --version)" -ForegroundColor Green

# ── 3. Clone or update repo ─────────────────────────────────
$repoDir = "$HOME\Documents\Trading_AI_model"
if (Test-Path $repoDir) {
    Write-Host "[~] Updating existing repo..." -ForegroundColor Yellow
    Set-Location $repoDir
    git pull origin main
    Write-Host "[OK] Repo updated" -ForegroundColor Green
} else {
    Write-Host "[~] Cloning repo..." -ForegroundColor Yellow
    git clone https://github.com/TheFinix13/Trading_AI_model.git $repoDir
    Set-Location $repoDir
    Write-Host "[OK] Repo cloned to $repoDir" -ForegroundColor Green
}

# ── 4. Create venv and install dependencies ──────────────────
if (-not (Test-Path ".venv")) {
    Write-Host "[~] Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

Write-Host "[~] Activating venv and installing dependencies..." -ForegroundColor Yellow
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip --quiet
pip install -e ".[mt5]" --quiet
pip install MetaTrader5 --quiet
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# ── 5. Create .env if not exists ─────────────────────────────
if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Red
    Write-Host "  CONFIGURATION REQUIRED — Exness MT5 Credentials" -ForegroundColor Red
    Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Red
    Write-Host ""
    Write-Host "  You can find these in your Exness Personal Area:" -ForegroundColor White
    Write-Host "    - Login number (e.g. 12345678)" -ForegroundColor Gray
    Write-Host "    - Password (your trading password)" -ForegroundColor Gray
    Write-Host "    - Server name (e.g. Exness-MT5Trial7)" -ForegroundColor Gray
    Write-Host ""

    $login = Read-Host "  Enter MT5 Login"
    $password = Read-Host "  Enter MT5 Password"
    $server = Read-Host "  Enter MT5 Server (e.g. Exness-MT5Trial7)"

    @"
# ── EURUSD AI Agent — Environment Variables ──

# ----- MT5 (live/paper trading) -----
MT5_LOGIN=$login
MT5_PASSWORD=$password
MT5_SERVER=$server
# MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

# ----- Vision API Keys (optional) -----
GEMINI_API_KEY=
ANTHROPIC_API_KEY=

# ----- Telegram Alerts (optional) -----
# TG_BOT_TOKEN=
# TG_CHAT_ID=
"@ | Out-File -FilePath .env -Encoding utf8

    Write-Host ""
    Write-Host "[OK] .env created" -ForegroundColor Green
} else {
    Write-Host "[OK] .env already exists" -ForegroundColor Green
}

# ── 6. Ensure models directory exists ────────────────────────
if (-not (Test-Path "models")) {
    New-Item -ItemType Directory -Path "models" | Out-Null
}
if (-not (Test-Path "data\parquet")) {
    New-Item -ItemType Directory -Path "data\parquet" -Force | Out-Null
}
Write-Host "[OK] Directory structure ready" -ForegroundColor Green

# ── 7. Test MT5 connection ───────────────────────────────────
Write-Host ""
Write-Host "[~] Testing MT5 connection..." -ForegroundColor Yellow

$env:PYTHONPATH = "."
$mt5Test = @"
import sys
try:
    import MetaTrader5 as mt5
except ImportError:
    print('[X] MetaTrader5 package not installed')
    sys.exit(1)

from dotenv import load_dotenv
import os

load_dotenv()
login = int(os.getenv('MT5_LOGIN', '0'))
password = os.getenv('MT5_PASSWORD', '')
server = os.getenv('MT5_SERVER', '')

if not mt5.initialize():
    err = mt5.last_error()
    print(f'[!] MT5 init failed: {err}')
    print('    Make sure MetaTrader 5 terminal is OPEN and logged in!')
    print('    The Python package requires the MT5 terminal to be running.')
    mt5.shutdown()
    sys.exit(0)

info = mt5.account_info()
if info:
    print(f'[OK] Connected! Account: {info.login}, Balance: ${info.balance:.2f}, Server: {info.server}')
    mt5.shutdown()
    sys.exit(0)

if mt5.login(login, password=password, server=server):
    info = mt5.account_info()
    print(f'[OK] Connected! Account: {info.login}, Balance: ${info.balance:.2f}, Server: {info.server}')
else:
    err = mt5.last_error()
    print(f'[!] Login failed: {err}')
    print('    Check your credentials in .env')
    print('    Make sure the MT5 terminal is open and logged in.')

mt5.shutdown()
"@

python -c $mt5Test

# ── 8. Show next steps ───────────────────────────────────────
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host "  SETUP COMPLETE" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "  Prerequisites:" -ForegroundColor Cyan
Write-Host "    - MetaTrader 5 terminal must be OPEN and logged into Exness demo" -ForegroundColor White
Write-Host ""
Write-Host "  1. Paper trading (safe — validates signals, no real trades):" -ForegroundColor Cyan
Write-Host "     python scripts/run_live.py --broker paper --timeframe H1 --lot 0.01" -ForegroundColor White
Write-Host ""
Write-Host "  2. Demo trading (real demo account execution):" -ForegroundColor Cyan
Write-Host "     python scripts/run_live.py --broker mt5 --timeframe H1 --lot 0.01" -ForegroundColor White
Write-Host ""
Write-Host "  3. To stop: press Ctrl+C or create 'kill.txt' in this folder" -ForegroundColor Cyan
Write-Host ""
Write-Host "  4. Monitor via dashboard (on your Mac or any browser):" -ForegroundColor Cyan
Write-Host "     python -m uvicorn agent.dashboard.app:app --host 0.0.0.0 --port 8000" -ForegroundColor White
Write-Host ""
Write-Host "  5. See docs/deployment_guide.md for the full guide" -ForegroundColor Cyan
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Green
