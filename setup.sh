#!/bin/bash
# CMS Data Pipeline - Ubuntu/Linux Setup
# Run: bash setup.sh

set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $1"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; }
step() { echo -e "\n${CYAN}--- $1 ---${NC}"; }

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   CMS Data Pipeline - Ubuntu/Linux Setup${NC}"
echo -e "${CYAN}============================================${NC}"

# ── 1. Check Python ───────────────────────────────────────────────────────────
step "Checking Python"

PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VERSION=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [ "$MAJOR" -gt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]); then
            PYTHON_CMD="$cmd"
            ok "$cmd $VERSION found"
            break
        else
            warn "$cmd $VERSION is too old (need 3.10+)"
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    err "Python 3.10+ not found."
    echo "  Install with: sudo apt install python3.10 python3.10-venv"
    exit 1
fi

# ── 2. Create virtual environment ─────────────────────────────────────────────
step "Virtual environment"

if [ ! -d ".venv" ]; then
    echo "Creating .venv..."
    "$PYTHON_CMD" -m venv .venv
    ok ".venv created"
else
    ok ".venv already exists"
fi

PIP=".venv/bin/pip"
PYTHON=".venv/bin/python"

# ── 3. Install requirements ───────────────────────────────────────────────────
step "Installing requirements"
"$PIP" install -r requirements.txt -q
ok "requirements.txt installed"

# ── 4. Create logs directory ──────────────────────────────────────────────────
step "Directories"
mkdir -p logs
ok "logs/ ready"

# ── 5. Create .env ────────────────────────────────────────────────────────────
step ".env configuration"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn ".env created from .env.example — edit it before running!"
        echo ""
        echo "  Required settings:"
        echo "    CANCEL_DIR        = full path to cancellation bills folder"
        echo "    CUSTOMER_DATA_DIR = full path to customer data folder"
        echo "    REVENUE_DIR       = full path to revenue folder"
        echo "    DB_HOST           = PostgreSQL host (e.g. localhost)"
        echo "    DB_PORT           = PostgreSQL port (default: 5432)"
        echo "    DB_NAME           = database name"
        echo "    DB_USER           = database user"
        echo "    DB_PASSWORD       = database password"
        echo ""
        echo -e "  Open with: ${YELLOW}nano .env${NC}"
    else
        err ".env.example not found — cannot create .env"
        exit 1
    fi
else
    ok ".env already exists"
fi

# ── 6. Docker (optional) ──────────────────────────────────────────────────────
step "Docker (optional — local PostgreSQL)"

if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    read -r -p "  Start PostgreSQL via Docker? [y/N] " reply
    if [[ "$reply" =~ ^[Yy]$ ]]; then
        docker compose up -d
        ok "PostgreSQL container started (port mapped in docker-compose.yml)"
    else
        ok "Skipped Docker"
    fi
else
    warn "Docker not found — skipping. Use an external PostgreSQL and set DB_* in .env"
fi

# ── 7. Test DB connection ─────────────────────────────────────────────────────
step "Testing database connection"

RESULT=$("$PYTHON" -c "
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
" 2>&1 || true)

if [[ "$RESULT" == OK* ]]; then
    ok "Database connection successful"
else
    warn "Database connection failed: $RESULT"
    echo "  Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD in .env"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}   Setup complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Run the pipeline:"
echo "  Init (full load):    .venv/bin/python -m loader.main --mode init"
echo "  Daily (incremental): .venv/bin/python -m loader.main --mode daily"
echo ""
