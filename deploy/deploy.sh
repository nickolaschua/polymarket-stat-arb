#!/usr/bin/env bash
# Polymarket Stat Arb — Idempotent Server Bootstrap Script
#
# Provisions a fresh Ubuntu/Debian server (Hetzner CPX31) with everything
# needed to run the collector daemon:
#   - Docker + TimescaleDB
#   - Python 3 venv + dependencies
#   - systemd service
#   - Database migrations
#
# Usage (as root):
#   bash deploy/deploy.sh
#   # or with custom install path:
#   bash deploy/deploy.sh /srv/polymarket-stat-arb
#
# This script is idempotent — safe to run multiple times.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INSTALL_DIR="${1:-/opt/polymarket-stat-arb}"
REPO_URL="${REPO_URL:-https://github.com/YOUR_USER/polymarket-stat-arb.git}"
SERVICE_NAME="polymarket-collector"
SERVICE_USER="polymarket"
ENV_FILE="${INSTALL_DIR}/.env.production"

echo "============================================"
echo "Polymarket Stat Arb — Server Bootstrap"
echo "Install directory: ${INSTALL_DIR}"
echo "============================================"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Install system dependencies
# ---------------------------------------------------------------------------
echo "[1/9] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    docker.io \
    docker-compose-plugin \
    python3 \
    python3-venv \
    python3-pip \
    git \
    age \
    curl \
    > /dev/null

# Enable and start Docker
systemctl enable docker
systemctl start docker
echo "  -> System dependencies installed"

# ---------------------------------------------------------------------------
# Step 2: Create service user
# ---------------------------------------------------------------------------
echo "[2/9] Creating service user '${SERVICE_USER}'..."
if id "${SERVICE_USER}" &>/dev/null; then
    echo "  -> User '${SERVICE_USER}' already exists"
else
    useradd --system --home-dir "${INSTALL_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
    echo "  -> User '${SERVICE_USER}' created"
fi

# Add polymarket user to docker group so it can interact with Docker
usermod -aG docker "${SERVICE_USER}" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 3: Clone or update repository
# ---------------------------------------------------------------------------
echo "[3/9] Setting up repository..."
if [ -d "${INSTALL_DIR}/.git" ]; then
    echo "  -> Repository exists, pulling latest..."
    cd "${INSTALL_DIR}"
    git pull
else
    echo "  -> Cloning repository..."
    git clone "${REPO_URL}" "${INSTALL_DIR}"
    cd "${INSTALL_DIR}"
fi

# ---------------------------------------------------------------------------
# Step 4: Create Python venv and install dependencies
# ---------------------------------------------------------------------------
echo "[4/9] Setting up Python virtual environment..."
cd "${INSTALL_DIR}"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  -> Virtual environment created"
else
    echo "  -> Virtual environment already exists"
fi

venv/bin/pip install --quiet --upgrade pip
venv/bin/pip install --quiet -r requirements.txt
echo "  -> Python dependencies installed"

# ---------------------------------------------------------------------------
# Step 5: Copy production config
# ---------------------------------------------------------------------------
echo "[5/9] Setting up configuration..."
if [ ! -f "${INSTALL_DIR}/config.yaml" ]; then
    cp "${INSTALL_DIR}/config.prod.yaml" "${INSTALL_DIR}/config.yaml"
    echo "  -> Copied config.prod.yaml to config.yaml"

    # Substitute env vars from .env.production if it exists
    if [ -f "${ENV_FILE}" ]; then
        # shellcheck source=/dev/null
        source "${ENV_FILE}"
        sed -i "s/POSTGRES_USER/${POSTGRES_USER:-polymarket}/g" "${INSTALL_DIR}/config.yaml"
        sed -i "s/POSTGRES_PASSWORD/${POSTGRES_PASSWORD:-changeme}/g" "${INSTALL_DIR}/config.yaml"
        echo "  -> Substituted database credentials in config.yaml"
    else
        echo "  -> WARNING: ${ENV_FILE} not found. Edit config.yaml manually with database credentials."
    fi
else
    echo "  -> config.yaml already exists, skipping"
fi

# ---------------------------------------------------------------------------
# Step 6: Start TimescaleDB
# ---------------------------------------------------------------------------
echo "[6/9] Starting TimescaleDB..."
cd "${INSTALL_DIR}"

# Source env vars for Docker Compose
if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
fi

docker compose -f deploy/docker-compose.prod.yml up -d

# Wait for TimescaleDB to be ready
echo "  -> Waiting for TimescaleDB to be healthy..."
RETRIES=30
until docker compose -f deploy/docker-compose.prod.yml exec -T timescaledb pg_isready -U "${POSTGRES_USER:-polymarket}" -q 2>/dev/null; do
    RETRIES=$((RETRIES - 1))
    if [ "${RETRIES}" -le 0 ]; then
        echo "  -> ERROR: TimescaleDB failed to start after 30 attempts"
        exit 1
    fi
    sleep 2
done
echo "  -> TimescaleDB is ready"

# ---------------------------------------------------------------------------
# Step 7: Run database migrations
# ---------------------------------------------------------------------------
echo "[7/9] Running database migrations..."
cd "${INSTALL_DIR}"

# Source env vars so the Python config can read them
if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
fi

sudo -u "${SERVICE_USER}" \
    env "PATH=${INSTALL_DIR}/venv/bin:${PATH}" \
    "${INSTALL_DIR}/venv/bin/python" "${INSTALL_DIR}/deploy/run-migrations.py"
echo "  -> Migrations complete"

# ---------------------------------------------------------------------------
# Step 8: Install systemd service
# ---------------------------------------------------------------------------
echo "[8/9] Installing systemd service..."
cp "${INSTALL_DIR}/deploy/polymarket-collector.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
echo "  -> Service '${SERVICE_NAME}' installed and enabled"

# ---------------------------------------------------------------------------
# Step 9: Create directories and fix ownership
# ---------------------------------------------------------------------------
echo "[9/9] Setting up directories and permissions..."
mkdir -p "${INSTALL_DIR}/logs"
mkdir -p "${INSTALL_DIR}/data"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

# Ensure shell scripts are executable
chmod +x "${INSTALL_DIR}/deploy/"*.sh

echo ""
echo "============================================"
echo "Bootstrap complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Create .env.production:  cp .env.production.example .env.production"
echo "  2. Edit .env.production with real credentials"
echo "  3. Encrypt your private key:  bash deploy/encrypt-key.sh"
echo "  4. Start the collector:  systemctl start ${SERVICE_NAME}"
echo "  5. Check status:  systemctl status ${SERVICE_NAME}"
echo "  6. View logs:  journalctl -u ${SERVICE_NAME} -f"
echo ""
