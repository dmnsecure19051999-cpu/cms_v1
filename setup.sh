#!/bin/bash
# CMS Data Pipeline - Ubuntu/Linux Setup
# Run: bash setup.sh

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $1"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; }
step() { echo -e "\n${CYAN}--- $1 ---${NC}"; }

run_sudo() {
    if [ "${EUID}" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

set_env_var() {
    local key="$1"
    local value="$2"
    if grep -qE "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        echo "${key}=${value}" >> .env
    fi
}

get_first_ipv4() {
    local iface="$1"
    ip -4 addr show "$iface" 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n 1 || true
}

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}   CMS Data Pipeline - Ubuntu/Linux Setup${NC}"
echo -e "${CYAN}============================================${NC}"

# 1. Install Python packages early (Ubuntu/Debian)
step "Preparing system packages"
if command -v apt-get >/dev/null 2>&1; then
    run_sudo apt-get update
    if run_sudo apt-get install -y python3.12 python3.12-venv; then
        ok "python3.12 and python3.12-venv installed/updated"
    else
        warn "python3.12 packages not available, falling back to distro defaults"
        run_sudo apt-get install -y python3 python3-venv
        ok "python3 and python3-venv installed/updated"
    fi
else
    warn "apt-get not found, skipping package auto-install"
fi

# 2. Check Python
step "Checking Python"

PYTHON_CMD=""
PY_MAJOR_MINOR=""
for cmd in python3.12 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VERSION=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        MAJOR=$(echo "$VERSION" | cut -d. -f1)
        MINOR=$(echo "$VERSION" | cut -d. -f2)
        if [ "$MAJOR" -gt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; }; then
            PYTHON_CMD="$cmd"
            PY_MAJOR_MINOR="$VERSION"
            ok "$cmd $VERSION found"
            break
        else
            warn "$cmd $VERSION is too old (need 3.10+)"
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    err "Python 3.10+ not found."
    echo "Install with: sudo apt install python3.12 python3.12-venv"
    exit 1
fi

# 2. Ensure venv support is present for detected Python
step "Checking python venv support"
if ! "$PYTHON_CMD" -m venv --help >/dev/null 2>&1; then
    warn "venv module is missing, installing python${PY_MAJOR_MINOR}-venv"
    run_sudo apt update
    run_sudo apt install -y "python${PY_MAJOR_MINOR}-venv"
fi
ok "venv module ready"

# 3. Create virtual environment
step "Virtual environment"
if [ ! -d ".venv" ]; then
    "$PYTHON_CMD" -m venv .venv
    ok ".venv created"
else
    ok ".venv already exists"
fi

PYTHON=".venv/bin/python"

if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
    warn "pip is missing in .venv, bootstrapping with ensurepip"
    "$PYTHON" -m ensurepip --upgrade
fi

# 4. Install requirements
step "Installing requirements"
"$PYTHON" -m pip install -r requirements.txt -q
ok "requirements.txt installed"

# 5. Create required directories
step "Directories"
mkdir -p logs
ok "logs/ ready"

# 6. Prepare .env
step ".env configuration"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        ok ".env created from .env.example"
    else
        cat > .env <<'EOF'
CANCEL_DIR=
CUSTOMER_DATA_DIR=
REVENUE_DIR=
DB_HOST=localhost
DB_PORT=5433
DB_NAME=cms_db
DB_USER=postgres
DB_PASSWORD=postgres
EOF
        ok ".env created with defaults"
    fi
else
    ok ".env already exists"
fi

PROJECT_DIR="$(pwd)"
DEFAULT_CANCEL_DIR="${PROJECT_DIR}/sample_input/cancel"
DEFAULT_CUSTOMER_DIR="${PROJECT_DIR}/sample_input/customer_data"
DEFAULT_REVENUE_DIR="${PROJECT_DIR}/sample_input/revenue"

set_env_var "CANCEL_DIR" "${DEFAULT_CANCEL_DIR}"
set_env_var "CUSTOMER_DATA_DIR" "${DEFAULT_CUSTOMER_DIR}"
set_env_var "REVENUE_DIR" "${DEFAULT_REVENUE_DIR}"
set_env_var "DB_HOST" "localhost"
set_env_var "DB_PORT" "5433"

if ! grep -qE '^DB_NAME=' .env || grep -qE '^DB_NAME=\s*$' .env; then
    set_env_var "DB_NAME" "cms_db"
fi
if ! grep -qE '^DB_USER=' .env || grep -qE '^DB_USER=\s*$' .env; then
    set_env_var "DB_USER" "postgres"
fi
if grep -qE '^DB_PASSWORD=(your_password_here|\s*)$' .env; then
    DB_PASS=$("$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(18))')
    set_env_var "DB_PASSWORD" "${DB_PASS}"
    warn "DB_PASSWORD placeholder detected, generated a secure password in .env"
fi

ok ".env updated for Docker PostgreSQL on localhost:5433"

# 7. Install and start Docker
step "Docker installation"

if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not found, installing docker.io and compose plugin"
    run_sudo apt update
    if ! run_sudo apt install -y docker.io docker-compose-v2; then
        run_sudo apt install -y docker.io docker-compose-plugin
    fi
else
    ok "Docker command found"
fi

if command -v systemctl >/dev/null 2>&1; then
    run_sudo systemctl enable docker >/dev/null 2>&1 || true
    run_sudo systemctl start docker >/dev/null 2>&1 || true
fi

DOCKER_CMD="docker"
if ! docker ps >/dev/null 2>&1; then
    if sudo docker ps >/dev/null 2>&1; then
        DOCKER_CMD="sudo docker"
        warn "Using sudo docker (user is not in docker group yet)"
    else
        err "Docker is installed but cannot be accessed."
        echo "Try: sudo usermod -aG docker ${USER} && newgrp docker"
        exit 1
    fi
fi
ok "Docker is ready"

if ! ${DOCKER_CMD} compose version >/dev/null 2>&1; then
    err "Docker Compose plugin is not available."
    echo "Install with: sudo apt install docker-compose-v2"
    exit 1
fi

# 8. Start PostgreSQL via Docker Compose
step "Starting PostgreSQL container"
${DOCKER_CMD} compose up -d postgres
ok "PostgreSQL container started"

# 9. Wait and test DB connection
step "Testing database connection"

DB_TEST_OUTPUT=$(
"$PYTHON" -c "
import time
from dotenv import load_dotenv
load_dotenv(dotenv_path='.env')
from loader.config import Config
from loader.db import get_engine
from sqlalchemy import text

cfg = Config()
last_error = None
for _ in range(30):
    try:
        engine = get_engine(cfg.db_url)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('OK')
        break
    except Exception as e:
        last_error = e
        time.sleep(1)
else:
    print('FAIL: ' + str(last_error))
"
)

if [[ "$DB_TEST_OUTPUT" == OK* ]]; then
    ok "Database connection successful"
else
    err "Database connection failed"
    echo "$DB_TEST_OUTPUT"
    echo "Current DB config comes from .env"
    exit 1
fi

# 10. Show network info for external connectivity
step "Network access information"

DB_HOST_VALUE=$(grep -E '^DB_HOST=' .env 2>/dev/null | head -n 1 | cut -d= -f2- || true)
DB_PORT_VALUE=$(grep -E '^DB_PORT=' .env 2>/dev/null | head -n 1 | cut -d= -f2- || true)
DB_NAME_VALUE=$(grep -E '^DB_NAME=' .env 2>/dev/null | head -n 1 | cut -d= -f2- || true)
DB_USER_VALUE=$(grep -E '^DB_USER=' .env 2>/dev/null | head -n 1 | cut -d= -f2- || true)

DB_HOST_VALUE="${DB_HOST_VALUE:-localhost}"
DB_PORT_VALUE="${DB_PORT_VALUE:-5433}"
DB_NAME_VALUE="${DB_NAME_VALUE:-cms_db}"
DB_USER_VALUE="${DB_USER_VALUE:-postgres}"

IS_WSL="false"
if grep -qi microsoft /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]; then
    IS_WSL="true"
fi

WSL_IP=""

if [ "$IS_WSL" = "true" ]; then
    WSL_IP="$(get_first_ipv4 eth0)"
    if [ -z "$WSL_IP" ]; then
        WSL_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
    fi
fi

if [ "$IS_WSL" = "true" ]; then
    [ -n "$WSL_IP" ] && ok "WSL IP: ${WSL_IP}"
else
    PRIMARY_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [ -n "$PRIMARY_IP" ] && ok "Machine IP: ${PRIMARY_IP}"
fi

echo ""
echo "Sample psql command:"
echo "  PGPASSWORD=*** psql -h ${DB_HOST_VALUE} -p ${DB_PORT_VALUE} -U ${DB_USER_VALUE} -d ${DB_NAME_VALUE}"

# Done
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}   Setup complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Run the pipeline:"
echo "  Init (full load):    .venv/bin/python main.py --mode init"
echo "  Daily (incremental): .venv/bin/python main.py --mode daily"
echo ""
