# Wallet Onboarding & USDC Acquisition Guide

## Overview

This guide covers the complete flow from having an existing crypto wallet to being ready to trade on Polymarket via your bot. All API interactions happen from your EU-based server, not from your local machine.

---

## Prerequisites

- An existing EOA wallet (MetaMask, hardware wallet, etc.)
- Fiat currency to purchase crypto
- Your EU server deployed (Hetzner/AWS Frankfurt) with a non-blocked IP

---

## Step 1: Create a Dedicated Trading Wallet

**Do NOT use your personal wallet for the bot.** Create a separate wallet exclusively for Polymarket bot trading.

### Why a Dedicated Wallet

1. **Isolation**: If the bot key is compromised, only trading capital is at risk
2. **Operational security**: The bot wallet's private key lives on the server; your personal wallet stays on your hardware wallet/phone
3. **Audit trail**: All transactions are bot-related, making P&L tracking simple
4. **IP consistency**: The dedicated wallet only ever interacts from your EU server IP

### How to Create

```bash
# Option A: Generate with Python (on your EU server)
python3 -c "
from eth_account import Account
acct = Account.create()
print(f'Address:     {acct.address}')
print(f'Private key: {acct.key.hex()}')
"

# Option B: Generate with cast (foundry)
cast wallet new
```

**Immediately save the private key securely.** You will need it for the bot config.

### Private Key Storage on Server

For Hetzner (no managed secrets service):

```bash
# Encrypt with age (recommended)
# Install: apt install age
age-keygen -o /root/.age-key.txt
echo "0xYourPrivateKeyHere" | age -r $(grep "public key" /root/.age-key.txt | awk '{print $NF}') > /root/.poly-key.enc

# Decrypt at bot startup (in your systemd service or start script)
export POLY_PRIVATE_KEY=$(age -d -i /root/.age-key.txt /root/.poly-key.enc)
```

For AWS:
```bash
# Store in Secrets Manager
aws secretsmanager create-secret \
  --name polymarket/bot/private-key \
  --secret-string '{"private_key":"0x..."}'
```

---

## Step 2: Acquire USDC

USDC is the settlement currency on Polymarket (USDC on Polygon network). You need USDC in your dedicated trading wallet on Polygon.

### Option A: Buy on Exchange, Withdraw to Polygon (Recommended)

This is the simplest path. Many exchanges support direct Polygon USDC withdrawal.

| Exchange | Polygon USDC Withdrawal | KYC Required | Available in Most Countries |
|----------|------------------------|--------------|----------------------------|
| **Binance** | Yes (Polygon network) | Yes | Yes (check your country) |
| **Kraken** | Yes (Polygon network) | Yes | Most countries |
| **Bybit** | Yes (Polygon network) | Yes | Most countries |
| **KuCoin** | Yes (Polygon network) | Varies | Most countries |
| **OKX** | Yes (Polygon network) | Yes | Most countries |

**Process:**
1. Buy USDC on the exchange (use fiat deposit or swap from another crypto)
2. Withdraw USDC to your **dedicated trading wallet address**
3. **Select "Polygon" as the withdrawal network** (NOT Ethereum — much cheaper)
4. Withdrawal fee is typically $1-2 for Polygon network
5. Arrives in ~2-5 minutes

### Option B: Bridge from Ethereum to Polygon

If you already have USDC on Ethereum mainnet:

1. **Polygon Portal Bridge** (official): https://portal.polygon.technology/bridge
   - Connect your wallet, select USDC, bridge to Polygon
   - Takes 15-30 minutes
   - Gas cost: ~$2-10 depending on Ethereum gas prices

2. **Third-party bridges** (faster, sometimes cheaper):
   - Jumper.exchange (aggregates bridges)
   - Stargate Finance
   - Across Protocol

### Option C: Swap on Polygon DEX

If you have MATIC/POL or other tokens on Polygon:

1. Go to QuickSwap (https://quickswap.exchange) or Uniswap on Polygon
2. Swap your tokens for USDC
3. USDC on Polygon address: `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` (native USDC)
4. Legacy USDC.e: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (bridged — this is what Polymarket uses)

**IMPORTANT: Polymarket uses USDC.e (bridged USDC), NOT native USDC on Polygon.**
- USDC.e contract: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
- If you withdraw from an exchange, ensure you get USDC.e (most exchanges send this by default on Polygon)
- If you have native USDC, you'll need to swap it for USDC.e on a DEX

### How Much USDC to Start

| Phase | USDC Needed | Notes |
|-------|-------------|-------|
| Testing/paper trade validation | $10-50 | Enough to place a few real orders and verify the full flow works |
| Initial live trading | $500-1,000 | As planned in your roadmap |
| Scaled trading | $1,000-2,000 | After validating edge |

---

## Step 3: Get MATIC/POL for Gas

Polygon transactions require MATIC (now POL) for gas fees. Gas is very cheap on Polygon (~$0.001-0.01 per transaction), but you need a small amount.

### How Much

**$1-2 worth of MATIC is enough for months of bot operation.**

Token approval transactions (one-time): ~$0.01-0.05 each
Order signing happens off-chain (no gas cost).
Settlement is handled by Polymarket's relayer (no gas cost to you).

### How to Get MATIC

1. **From exchange**: Withdraw a small amount of MATIC to your Polygon wallet
2. **Polygon faucet** (for testnet only — not useful for mainnet)
3. **Swap a tiny amount of USDC for MATIC** on QuickSwap after your USDC arrives

---

## Step 4: Set Token Approvals

Before your bot can trade, you must approve Polymarket's exchange contracts to spend your USDC and conditional tokens. This is a one-time setup.

### Contract Addresses (Polygon Mainnet)

```
# Your tokens
USDC.e:              0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
Conditional Tokens:  0x4D97DCd97eC945f40cF65F87097ACe5EA0476045

# Polymarket exchange contracts (approve BOTH tokens for ALL three)
CTF Exchange:        0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
Neg Risk CTF Exch:   0xC5d563A36AE78145C45a50134d48A1215220f80a
Neg Risk Adapter:    0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296
```

### Approval Matrix

You need **6 approvals total** (2 tokens x 3 contracts):

| Token | Spender Contract | Why |
|-------|-----------------|-----|
| USDC.e | CTF Exchange | Standard market trading |
| USDC.e | Neg Risk CTF Exchange | Trading in multi-outcome (negRisk) markets |
| USDC.e | Neg Risk Adapter | Capital efficiency for negRisk events |
| Conditional Tokens | CTF Exchange | Selling/redeeming outcome tokens |
| Conditional Tokens | Neg Risk CTF Exchange | Selling in negRisk markets |
| Conditional Tokens | Neg Risk Adapter | Redeeming negRisk positions |

### Method A: Using py-clob-client (Recommended)

The py-clob-client library can handle approvals programmatically:

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
PRIVATE_KEY = "0xYourDedicatedWalletKey"

client = ClobClient(HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID)
client.set_api_creds(client.create_or_derive_api_creds())

# Check current USDC allowance
collateral_params = BalanceAllowanceParams(
    asset_type=AssetType.COLLATERAL,
    signature_type=-1  # Auto-detect
)
balance = client.get_balance_allowance(collateral_params)
print(f"USDC Balance & Allowance: {balance}")

# Update/set USDC allowance (sends approval transaction)
client.update_balance_allowance(collateral_params)
print("USDC approval set")

# Check and set conditional token allowance
# (Need a token_id from any market for this call)
token_id = "YOUR_TOKEN_ID_HERE"  # Get from Gamma API
cond_params = BalanceAllowanceParams(
    asset_type=AssetType.CONDITIONAL,
    token_id=token_id,
)
client.update_balance_allowance(cond_params)
print("Conditional token approval set")
```

### Method B: Using cast (foundry) or web3.py

If you prefer manual approval:

```bash
# Approve USDC.e for CTF Exchange (max uint256 approval)
cast send 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174 \
  "approve(address,uint256)" \
  0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E \
  0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff \
  --rpc-url https://polygon-rpc.com \
  --private-key $POLY_PRIVATE_KEY

# Repeat for each token+contract combination (6 total)
```

### Verification

After setting approvals, verify they're active:

```python
# Using py-clob-client
collateral = client.get_balance_allowance(
    BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=-1)
)
print(f"USDC: balance={collateral}")

# Check contract addresses are correct
print(f"Collateral (USDC):     {client.get_collateral_address()}")
print(f"Conditional Tokens:    {client.get_conditional_address()}")
print(f"Exchange:              {client.get_exchange_address()}")
```

---

## Step 5: Verify Full Setup

Run this verification script from your EU server to confirm everything works:

```python
#!/usr/bin/env python3
"""Verify Polymarket wallet setup is complete."""

import json
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
PRIVATE_KEY = "0xYourKey"  # Load from secure storage!

print("=" * 60)
print("Polymarket Wallet Setup Verification")
print("=" * 60)

# 1. Initialize client
print("\n[1] Initializing client...")
client = ClobClient(HOST, key=PRIVATE_KEY, chain_id=CHAIN_ID)

# 2. Create API credentials
print("[2] Creating API credentials...")
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)
print(f"    API Key: {creds.api_key[:12]}...")

# 3. Check server connectivity
print("[3] Checking CLOB server...")
ok = client.get_ok()
print(f"    Server OK: {ok}")

# 4. Check USDC balance
print("[4] Checking USDC balance...")
bal = client.get_balance_allowance(
    BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=-1)
)
print(f"    USDC Balance & Allowance: {bal}")

# 5. Fetch a market to verify data access
print("[5] Fetching sample market...")
import httpx
resp = httpx.get(
    "https://gamma-api.polymarket.com/markets",
    params={"limit": 1, "active": "true", "order": "volume", "ascending": "false"}
)
markets = resp.json()
if markets:
    m = markets[0]
    prices = json.loads(m.get("outcomePrices", "[]"))
    print(f"    Market: {m['question'][:60]}...")
    print(f"    Prices: {prices}")
    print(f"    Volume: ${m.get('volume24hr', 0):,.0f}")

print("\n" + "=" * 60)
print("Setup complete! Ready to trade.")
print("=" * 60)
```

---

## Step 6: Configure Your Bot

Update your `config.yaml`:

```yaml
wallet:
  private_key_env: "POLY_PRIVATE_KEY"  # Env var holding your key
  funder_address: "0xYourDedicatedWalletAddress"
  signature_type: 0  # 0 for EOA/MetaMask wallets

# Start in paper trading mode
paper_trading: true
```

Set the environment variable on your server:
```bash
# In your .bashrc or systemd service file
export POLY_PRIVATE_KEY="0xYourPrivateKey"
```

---

## Operational Security Checklist

```
[ ] Dedicated wallet created (NOT your personal wallet)
[ ] Private key stored encrypted on server (age or Secrets Manager)
[ ] Private key NEVER appears in code, git, or logs
[ ] Wallet funded with USDC.e on Polygon
[ ] Small amount of MATIC for gas
[ ] All 6 token approvals set
[ ] Bot accesses wallet ONLY from EU server IP
[ ] You NEVER access the trading wallet from a restricted-country IP
[ ] To check on things, SSH into your EU server — don't use Polymarket UI locally
[ ] Paper trading mode enabled for initial testing
[ ] Verification script passes all checks
```

---

## Costs Summary

| Item | Cost | Frequency |
|------|------|-----------|
| USDC withdrawal from exchange (Polygon) | $1-2 | One-time |
| MATIC for gas (6 approvals + buffer) | $1-2 | One-time |
| Trading capital (USDC) | $500-2,000 | One-time (add more as profitable) |
| **Total to get started** | **~$505-2,005** | |

---

## Troubleshooting

### "Insufficient allowance" error when placing orders
- Re-run the approval step for both USDC.e and Conditional Tokens
- Use `client.update_balance_allowance()` to refresh

### "Geoblocked" error from CLOB API
- Your server IP is in a blocked region
- Verify: `curl https://polymarket.com/api/geoblock` from your server
- Must show `"blocked": false`

### "Invalid API credentials" error
- API credentials may have expired or been invalidated
- Re-derive: `creds = client.create_or_derive_api_creds()`
- Credentials are derived from your private key, so they're deterministic

### Orders cancelled unexpectedly
- Heartbeat may have stopped — check heartbeat manager logs
- See `src/utils/heartbeat.py` for heartbeat management

### USDC.e vs native USDC confusion
- Polymarket uses **USDC.e** (bridged): `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
- NOT native USDC: `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359`
- If you have native USDC, swap for USDC.e on QuickSwap or Uniswap (Polygon)

---

*Sources: py-clob-client README, Polymarket Developer Docs, Context7*
