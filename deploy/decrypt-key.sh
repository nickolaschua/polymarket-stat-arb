#!/usr/bin/env bash
# Decrypt the age-encrypted Polymarket wallet private key.
#
# This script is meant to be sourced (not executed) so the decrypted
# key is exported into the calling shell's environment:
#
#   source deploy/decrypt-key.sh
#   echo "${POLY_PRIVATE_KEY}"  # now available
#
# The plaintext key exists only in memory (shell variable) and is
# never written to disk.

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/polymarket-stat-arb}"
AGE_KEY="${INSTALL_DIR}/.age-key.txt"
ENCRYPTED_KEY="${INSTALL_DIR}/.poly-key.age"

# Validate files exist
if [ ! -f "${AGE_KEY}" ]; then
    echo "ERROR: Age identity not found: ${AGE_KEY}" >&2
    echo "Run deploy/encrypt-key.sh first." >&2
    return 1 2>/dev/null || exit 1
fi

if [ ! -f "${ENCRYPTED_KEY}" ]; then
    echo "ERROR: Encrypted key not found: ${ENCRYPTED_KEY}" >&2
    echo "Run deploy/encrypt-key.sh first." >&2
    return 1 2>/dev/null || exit 1
fi

# Decrypt and export — plaintext never touches disk
export POLY_PRIVATE_KEY
POLY_PRIVATE_KEY=$(age -d -i "${AGE_KEY}" "${ENCRYPTED_KEY}")
