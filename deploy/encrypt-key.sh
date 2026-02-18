#!/usr/bin/env bash
# Encrypt a Polymarket wallet private key with age.
#
# The private key is read from stdin and piped directly to age.
# It is NEVER written to disk in plaintext.
#
# Usage:
#   echo "0x..." | bash deploy/encrypt-key.sh
#   # or interactively:
#   bash deploy/encrypt-key.sh
#   (paste key, then Ctrl+D)
#
# Files created:
#   .age-key.txt    — age identity (private key for decryption)
#   .poly-key.age   — encrypted Polymarket private key
#
# Both files have 600 permissions (owner read/write only).

set -euo pipefail

INSTALL_DIR="${1:-/opt/polymarket-stat-arb}"
AGE_KEY="${INSTALL_DIR}/.age-key.txt"
ENCRYPTED_KEY="${INSTALL_DIR}/.poly-key.age"

# Check that age is installed
command -v age >/dev/null 2>&1 || {
    echo "ERROR: 'age' is not installed."
    echo "Install it: apt-get install age"
    exit 1
}

command -v age-keygen >/dev/null 2>&1 || {
    echo "ERROR: 'age-keygen' is not installed."
    echo "Install it: apt-get install age"
    exit 1
}

# Generate age keypair if none exists
if [ ! -f "${AGE_KEY}" ]; then
    echo "Generating age identity keypair..."
    age-keygen -o "${AGE_KEY}" 2>/dev/null
    chmod 600 "${AGE_KEY}"
    echo "  -> Age identity created: ${AGE_KEY}"
else
    echo "  -> Age identity already exists: ${AGE_KEY}"
fi

# Extract public key
PUBLIC_KEY=$(age-keygen -y "${AGE_KEY}")
echo "  -> Public key: ${PUBLIC_KEY}"

# Read private key from stdin and encrypt
echo ""
echo "Paste your Polymarket wallet private key (then press Ctrl+D):"
echo "(The key will NOT be echoed or written to disk in plaintext)"
echo ""

age -r "${PUBLIC_KEY}" -o "${ENCRYPTED_KEY}" < /dev/stdin

chmod 600 "${ENCRYPTED_KEY}"

echo ""
echo "============================================"
echo "Private key encrypted successfully!"
echo "============================================"
echo ""
echo "Files:"
echo "  Identity (keep safe):  ${AGE_KEY}"
echo "  Encrypted key:         ${ENCRYPTED_KEY}"
echo ""
echo "To decrypt (test):"
echo "  age -d -i ${AGE_KEY} ${ENCRYPTED_KEY}"
echo ""
echo "IMPORTANT: Back up ${AGE_KEY} securely."
echo "If lost, you cannot decrypt the wallet key."
echo ""
