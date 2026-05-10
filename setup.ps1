# CMS Data Pipeline - Windows Setup
# Run in PowerShell: powershell -ExecutionPolicy Bypass -File setup.ps1

$ErrorActionPreference = "Stop"

function Write-Ok($msg)  { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg){ Write-Host "[!!] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERR] $msg" -ForegroundColor Red }
function Write-Step($msg){ Write-Host "`n--- $msg ---" -ForegroundColor Cyan }

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   CMS Data Pipeline - Windows Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# ── 1. Check Python ───────────────────────────────────────────────────────────
Write-Step "Checking Python"

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $pythonCmd = $cmd
                Write-Ok "$cmd $($Matches[0]) found"
                break
            } else {
                Write-Warn "$cmd version $($Matches[0]) is too old (need 3.10+)"
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Err "Python 3.10+ not found."
    Write-Host "Download from: https://www.python.org/downloads/" -ForegroundColor Yellow
    exit 1
}

# ── 2. Create virtual environment ────────────────────────────────────────────
Write-Step "Virtual environment"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv..."
    & $pythonCmd -m venv .venv
    Write-Ok ".venv created"
} else {
    Write-Ok ".venv already exists"
}

$pip    = ".venv\Scripts\pip.exe"
$python = ".venv\Scripts\python.exe"

# ── 3. Install requirements ───────────────────────────────────────────────────
Write-Step "Installing requirements"
& $pip install -r requirements.txt -q
Write-Ok "requirements.txt installed"

# ── 4. Create logs directory ──────────────────────────────────────────────────
Write-Step "Directories"
New-Item -ItemType Directory -Force -Path "logs" | Out-Null
Write-Ok "logs\ ready"

# ── 5. Create .env ────────────────────────────────────────────────────────────
Write-Step ".env configuration"

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Warn ".env created from .env.example — edit it before running!"
        Write-Host ""
        Write-Host "  Required settings:" -ForegroundColor White
        Write-Host "    CANCEL_DIR       = full path to cancellation bills folder"
        Write-Host "    CUSTOMER_DATA_DIR= full path to customer data folder"
        Write-Host "    REVENUE_DIR      = full path to revenue folder"
        Write-Host "    DB_HOST          = PostgreSQL host (e.g. localhost)"
        Write-Host "    DB_PORT          = PostgreSQL port (default: 5432)"
        Write-Host "    DB_NAME          = database name"
        Write-Host "    DB_USER          = database user"
        Write-Host "    DB_PASSWORD      = database password"
        Write-Host ""
        Write-Host "  Open with: notepad .env" -ForegroundColor Yellow
    } else {
        Write-Err ".env.example not found — cannot create .env"
        exit 1
    }
} else {
    Write-Ok ".env already exists"
}

# ── 6. Test DB connection ─────────────────────────────────────────────────────
Write-Step "Testing database connection"
$testScript = @"
import os
from dotenv import load_dotenv
load_dotenv(dotenv_path='.env')
from loader.config import Config
from loader.db import get_engine
try:
    cfg = Config()
    engine = get_engine(cfg.db_url)
    with engine.connect() as conn:
        conn.execute(__import__('sqlalchemy').text('SELECT 1'))
    print('OK')
except Exception as e:
    print('FAIL: ' + str(e))
"@

$result = & $python -c $testScript 2>&1
if ($result -match "^OK") {
    Write-Ok "Database connection successful"
} else {
    Write-Warn "Database connection failed: $result"
    Write-Host "  Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD in .env" -ForegroundColor Yellow
    Write-Host "  (You can still edit .env and retry manually)" -ForegroundColor Yellow
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   Setup complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Run the pipeline:"
Write-Host "  Init (full load):    .venv\Scripts\python -m loader.main --mode init"
Write-Host "  Daily (incremental): .venv\Scripts\python -m loader.main --mode daily"
Write-Host ""
