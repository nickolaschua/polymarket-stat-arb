#!/usr/bin/env bash
# systemd entry point for the Polymarket collector daemon.
#
# This wrapper:
#   1. Decrypts the age-encrypted wallet private key (plaintext stays in memory)
#   2. Sources .env.production for database and other env vars
#   3. exec's the Python collector (replaces shell, so systemd tracks Python PID)
#
# Referenced by: deploy/polymarket-collector.service ExecStart

set -euo pipefail

INSTALL_DIR="/opt/polymarket-stat-arb"

# ---------------------------------------------------------------------------
# 1. Source environment variables
# ---------------------------------------------------------------------------
ENV_FILE="${INSTALL_DIR}/.env.production"
if [ -f "${ENV_FILE}" ]; then
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
else
    echo "WARNING: ${ENV_FILE} not found. Continuing without it." >&2
fi

# ---------------------------------------------------------------------------
# 2. Decrypt wallet private key (if encrypted key exists)
# ---------------------------------------------------------------------------
AGE_KEY="${INSTALL_DIR}/.age-key.txt"
ENCRYPTED_KEY="${INSTALL_DIR}/.poly-key.age"

if [ -f "${AGE_KEY}" ] && [ -f "${ENCRYPTED_KEY}" ]; then
    export POLY_PRIVATE_KEY
    POLY_PRIVATE_KEY=$(age -d -i "${AGE_KEY}" "${ENCRYPTED_KEY}")
fi

# ---------------------------------------------------------------------------
# 3. Launch the collector daemon (exec replaces this shell process)
# ---------------------------------------------------------------------------
cd "${INSTALL_DIR}"
exec "${INSTALL_DIR}/venv/bin/python" -m src.main collect
