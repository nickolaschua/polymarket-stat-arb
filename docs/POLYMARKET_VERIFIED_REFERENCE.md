# Polymarket Verified Reference

**Research Date:** 2026-02-15  
**Sources:** Official Polymarket docs, GitHub repos, Polygonscan

---

## Section 1: Rate Limits ✅ VERIFIED

**Source:** https://docs.polymarket.com/quickstart/introduction/rate-limits

### Enforcement Mechanism
- **Cloudflare throttling** — requests over limit are **delayed/queued**, not dropped
- **Burst allowances** for some endpoints
- **Sliding time windows** (per 10s, per minute, per 10 minutes)

### Gamma API Limits (per 10 seconds)
| Endpoint | Limit |
|----------|-------|
| General | 4,000/10s |
| /events | 500/10s |
| /markets | 300/10s |
| /markets /events listing | 900/10s |
| Search | 350/10s |
| Tags | 200/10s |
| Get Comments | 200/10s |

### CLOB API Limits
| Endpoint | Limit | Notes |
|----------|-------|-------|
| General | 9,000/10s | |
| /book | 1,500/10s | |
| /books | 500/10s | |
| /price | 1,500/10s | |
| /prices | 500/10s | |
| /midprice | 1,500/10s | |
| /midprices | 500/10s | |
| Price History | 1,000/10s | |
| Market Tick Size | 200/10s | |

### CLOB Trading Limits
| Endpoint | Burst | Sustained |
|----------|-------|-----------|
| POST /order | 3,500/10s (500/s) | 36,000/10min (60/s) |
| DELETE /order | 3,000/10s (300/s) | 30,000/10min (50/s) |
| POST /orders (batch) | 1,000/10s (100/s) | 15,000/10min (25/s) |
| DELETE /orders | 1,000/10s (100/s) | 15,000/10min (25/s) |
| DELETE /cancel-all | 250/10s (25/s) | 6,000/10min (10/s) |
| DELETE /cancel-market-orders | 1,000/10s (100/s) | 1,500/10min (25/s) |

### Data API Limits
| Endpoint | Limit |
|----------|-------|
| General | 1,000/10s |
| /trades | 200/10s |
| /positions | 150/10s |
| /closed-positions | 150/10s |

### Other Limits
| Endpoint | Limit |
|----------|-------|
| RELAYER /submit | 25/1min |
| User PNL API | 200/10s |
| API Keys | 100/10s |
| Balance Allowance GET | 200/10s |
| Balance Allowance UPDATE | 50/10s |

**CHANGED from our assumptions:**
- Gamma API is 4,000/10s, not 1,000/hour
- CLOB trading is 60/s sustained (not 60/min)
- These are much more generous than we assumed

---

## Section 2: Historical Data & Resolved Markets ⚠️ PARTIALLY VERIFIED

### Known Issue (GitHub #216) ✅ CONFIRMED
- `/prices-history` returns **empty data for resolved markets at fidelity < 720 (12 hours)**
- Only 12+ hour granularity works for closed markets
- **This is NOT fixed** as of Feb 2026

### Market Fields for Closed Markets
From Gamma API response:
- `closed: boolean` — indicates market is closed
- `closedTime: string` — timestamp when closed
- `outcomePrices: string` — **last traded prices, NOT settlement prices**
- `umaResolutionStatus: string` — UMA oracle status
- `resolvedBy: string` — resolver identifier
- `automaticallyResolved: boolean` — if auto-resolved

**UNVERIFIED:** No explicit `resolution: "Yes"` field found. Must infer from final prices (0.00/1.00).

### Pagination
- Maximum `limit` for Gamma API: **100** (confirmed from usage)
- Data API `/trades` and `/activity`: **limit: 500, offset: 1,000** (per changelog Aug 2025)

---

## Section 3: CLOB API Endpoints ✅ VERIFIED

**Source:** https://docs.polymarket.com/developers/CLOB/clients/methods-l2

### Public Endpoints (No Auth)
- `GET /ok` — health check
- `GET /server-time` — server timestamp
- `GET /book?token_id=` — orderbook
- `GET /books` — multiple orderbooks
- `GET /price?token_id=&side=` — current price
- `GET /prices` — multiple prices
- `GET /midpoint?token_id=` — midpoint price
- `GET /midpoints` — multiple midpoints
- `GET /spread?token_id=` — spread
- `GET /last-trade-price?token_id=` — last trade
- `GET /tick-size?token_id=` — tick size for market
- `GET /prices-history?market=&interval=&fidelity=` — historical prices

### Authenticated Endpoints (L2)
- `POST /order` — place single order
- `POST /orders` — place batch orders (max 15)
- `DELETE /order/{order_id}` — cancel single order
- `DELETE /orders` — cancel multiple orders
- `DELETE /cancel-all` — cancel all orders
- `DELETE /cancel-market-orders` — cancel by market (takes `market` or `asset_id`)
- `GET /orders` — get open orders
- `GET /order/{order_id}` — get specific order
- `GET /trades` — get trade history
- `GET /balance-allowance` — check balance/allowance
- `POST /balance-allowance` — update cached balance
- `GET /notifications` — get notifications
- `DELETE /notifications` — clear notifications
- `GET /api-keys` — list API keys
- `DELETE /api-key` — revoke API key

### NEW Endpoints (2025-2026)
- **Heartbeats API** (Jan 2026) — connection monitoring, auto-cancel on disconnect
- **Post-Only Orders** (Jan 2026) — rejected if would immediately match
- **FAK Order Type** (May 2025) — Fill-and-Kill (partial fill allowed)

### Batch Orders
- **Max batch size: 15** (increased from 5 in Aug 2025)

---

## Section 4: Order Types & Precision ✅ VERIFIED

**Source:** py-clob-client README, docs

### Order Types
| Type | Description |
|------|-------------|
| GTC | Good-til-Cancelled (default limit order) |
| GTD | Good-til-Date (expires at specified time) |
| FOK | Fill-or-Kill (fill entire order or cancel) |
| FAK | Fill-and-Kill (partial fill allowed, rest cancelled) |

### Tick Sizes
Available tick sizes: `"0.1"`, `"0.01"`, `"0.001"`, `"0.0001"`

Market's tick size determines price precision. Query via `GET /tick-size?token_id=`.

### Order Parameters
```python
OrderArgs(
    token_id: str,       # Token ID
    price: float,        # 0.00 to 1.00 (must align with tick size)
    size: float,         # Number of shares
    side: BUY | SELL,
    fee_rate_bps: int,   # Optional fee rate
    nonce: int,          # Optional, auto-generated
    expiration: int,     # For GTD orders, Unix timestamp
    taker: str,          # Optional taker address
)
```

### Order Response
```python
{
    "success": bool,
    "errorMsg": str,
    "orderID": str,
    "transactionsHashes": list[str],
    "status": str,  # "LIVE", "MATCHED", "CANCELLED", etc.
    "takingAmount": str,
    "makingAmount": str,
}
```

### Post-Only Orders
- Set `post_only=True` when posting
- Order is **rejected** (not silently cancelled) if it would immediately match

---

## Section 5: WebSocket ✅ VERIFIED

**Source:** https://docs.polymarket.com/developers/CLOB/websocket/

### Endpoints
- Market channel: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- User channel: `wss://ws-subscriptions-clob.polymarket.com/ws/user`

### Subscription Message
```json
{
    "auth": {...},           // Auth object (see WSS Auth docs)
    "markets": ["..."],      // Condition IDs for user channel
    "assets_ids": ["..."],   // Token IDs for market channel
    "type": "USER" | "MARKET",
    "custom_feature_enabled": bool
}
```

### Dynamic Subscription
```json
{
    "assets_ids": ["..."],
    "markets": ["..."],
    "operation": "subscribe" | "unsubscribe",
    "custom_feature_enabled": bool
}
```

### Market Channel Events
- `book` — orderbook snapshot/updates
- `price_change` — price updates (format changed Sept 2025, see migration guide)
- `last_trade_price` — last trade
- `trade` — trade occurred

### NEW: No Subscription Limit
- **100 token subscription limit removed** (May 2025)
- Can subscribe to unlimited token IDs

### initial_dump Option
- Set `initial_dump: false` to skip initial orderbook state on subscription

---

## Section 6: Authentication ✅ VERIFIED

**Source:** https://docs.polymarket.com/developers/CLOB/authentication

### Two-Level Authentication
1. **L1 (Private Key)** — EIP-712 signature to create/derive API creds
2. **L2 (API Key)** — HMAC-SHA256 signature for trading

### L1 Headers
| Header | Description |
|--------|-------------|
| POLY_ADDRESS | Polygon signer address |
| POLY_SIGNATURE | EIP-712 signature |
| POLY_TIMESTAMP | Unix timestamp |
| POLY_NONCE | Nonce (default 0) |

### L2 Headers
| Header | Description |
|--------|-------------|
| POLY_ADDRESS | Polygon signer address |
| POLY_SIGNATURE | HMAC-SHA256 signature |
| POLY_TIMESTAMP | Unix timestamp |
| POLY_API_KEY | API key |
| POLY_PASSPHRASE | Passphrase |

### API Credentials
```json
{
    "apiKey": "UUID",
    "secret": "base64-encoded-string",
    "passphrase": "random-string"
}
```

### create_or_derive_api_creds()
- **Deterministically derives** from private key (not random each time)
- Creates new creds only if none exist

### Signature Types
| Type | ID | Description |
|------|-----|-------------|
| EOA | 0 | Standard wallet (MetaMask, hardware) |
| POLY_PROXY | 1 | Magic/email wallet |
| POLY_GNOSIS_SAFE | 2 | Browser wallet proxy (most common) |

### Funder Address
- Required for **all authenticated trading**
- For EOA (type 0): same as signer address
- For proxy wallets: the Polymarket-deployed wallet address
- **NEW:** Rust client auto-derives via CREATE2

---

## Section 7: Heartbeat System ✅ VERIFIED

**Source:** Changelog Jan 2026, rs-clob-client

### Overview
- **Added January 2026**
- Monitors connection status
- **Auto-cancels ALL open orders** if client disconnects

### From Rust Client
> "heartbeats feature that automatically sends heartbeat messages to the Polymarket server, if the client disconnects all open orders will be cancelled"

### Interval
- **UNVERIFIED:** Specific interval (likely 10s based on other implementations)

### Scope
- Cancels **ALL orders for the account**, not just session orders

---

## Section 8: Contract Addresses ✅ VERIFIED

**Source:** py-clob-client README, Polygonscan

### USDC (Bridged)
- Address: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`
- **Still the token Polymarket uses** (USDC.e)

### Conditional Tokens Framework
- Address: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`

### Exchange Contracts (Approve USDC + CTF for these)
1. **CTF Exchange:** `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
2. **Neg Risk CTF Exchange:** `0xC5d563A36AE78145C45a50134d48A1215220f80a`
3. **Neg Risk Adapter:** `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296`

### Total Approvals Needed
- **6 approvals:** 2 tokens × 3 contracts

### Native USDC Migration
- **No migration announced** as of Feb 2026
- Still using bridged USDC.e

---

## Section 9: Negative Risk (NegRisk) Events ✅ VERIFIED

**Source:** https://docs.polymarket.com/developers/neg-risk/overview

### Overview
- For "winner-take-all" events (multiple outcomes, one winner)
- Identified by `negRisk: true` in event data
- Enables **capital efficiency** via convert action

### Key Mechanism
- **NO share in any market can convert to 1 YES share in all other markets**
- Conversions via Neg Risk Adapter contract

### Augmented Negative Risk
- `enableNegRisk: true` AND `negRiskAugmented: true`
- Allows adding new outcomes via placeholder clarification
- "Other" outcome can change definition

### Fees
- `negRiskFeeBips` field specifies fees for neg risk trades

### Trading Considerations
- Only trade on **named outcomes**
- Unnamed outcomes should be ignored until clarified
- Polymarket UI hides unnamed outcomes

---

## Section 10: Fees ✅ VERIFIED

**Source:** Changelog, docs

### Trading Fees
- **Base fee: 0%** for most markets
- **Taker fees enabled** for:
  - 15-minute crypto markets (Jan 2026): peaks at **1.56%** at 50% probability
  - NCAAB basketball (Feb 2026)
  - Serie A soccer (Feb 2026)

### Maker Rebates
- Daily USDC rebates to liquidity providers
- Funded by taker fees
- **Per-market calculation** (makers compete within same market)

### Neg Risk Fees
- Specified by `negRiskFeeBips` field per event

### Gas Costs
- Order **signing is free** (off-chain)
- Order **submission is free** (gasless via operator)
- **You pay gas for:**
  - Initial token approvals
  - On-chain cancellations (if needed)
  - Redemption after resolution

---

## Section 11: Geoblocking ✅ VERIFIED

**Source:** https://docs.polymarket.com/developers/CLOB/geoblock

### Endpoint
```
GET https://polymarket.com/api/geoblock
```

### Response
```json
{
    "blocked": boolean,
    "ip": "string",
    "country": "XX",
    "region": "string"
}
```

### Blocked Countries (33 total)
AU, BE, BY, BI, CF, CD, CU, DE, ET, FR, GB, IR, IQ, IT, KP, LB, LY, MM, NI, PL, RU, **SG**, SO, SS, SD, SY, TH, TW, UM, **US**, VE, YE, ZW

**Singapore (SG) is blocked** — confirms why Nick can't access directly.

### Blocked Regions
- Canada: Ontario (ON)
- Ukraine: Crimea (43), Donetsk (14), Luhansk (09)

### Enforcement Level
- API-level blocking (CLOB rejects from blocked IPs)
- Gamma API (read-only) **may** have same restrictions

---

## Section 12: py-clob-client Library ✅ VERIFIED

**Source:** PyPI, GitHub

### Current Version
- Check: `pip index versions py-clob-client`

### Python Compatibility
- **Python 3.9+** required

### Key Types
```python
from py_clob_client.clob_types import (
    OrderArgs,
    MarketOrderArgs,
    BookParams,
    OpenOrderParams,
    TradeParams,
    BalanceAllowanceParams,
    ApiCreds,
    OrderType,
)
from py_clob_client.order_builder.constants import BUY, SELL

class AssetType(Enum):
    COLLATERAL = "COLLATERAL"
    CONDITIONAL = "CONDITIONAL"
```

### Synchronous Library
- All methods are **synchronous**
- Use `asyncio.to_thread()` or `run_in_executor()` for async

### Known Issues
- #216: `/prices-history` empty for resolved markets at < 12h fidelity

### Methods for Positions/Balances
- `get_balance_allowance(BalanceAllowanceParams)` — check balance
- `update_balance_allowance(BalanceAllowanceParams)` — refresh cache
- No direct "get positions" — use Data API

---

## Summary of Changes from Our Assumptions

| Item | Our Assumption | Verified Value | Status |
|------|---------------|----------------|--------|
| Gamma rate limit | 1,000/hour | 4,000/10s | **CHANGED** |
| CLOB order rate | 60/min | 60/s sustained | **CHANGED** |
| Batch order max | 15 | 15 | ✅ Correct |
| Historical data | Works for resolved | Only 12h+ fidelity | **CHANGED** |
| Resolution field | Explicit field | Must infer from prices | **CHANGED** |
| USDC token | Bridged | Bridged (USDC.e) | ✅ Correct |
| Contract addresses | Listed | All confirmed | ✅ Correct |
| Heartbeat interval | 10s | Unverified | ❓ |
| Singapore blocked | Yes | Yes (SG in list) | ✅ Correct |

---

## Section 13: Data API ✅ VERIFIED

**Source:** https://docs.polymarket.com/developers/misc-endpoints/data-api-get-positions

### Endpoint
```
GET https://data-api.polymarket.com/positions
```

### Parameters
- `address` — User address (proxy wallet or EOA)
- `market` — Filter by condition ID (optional)
- `event` — Filter by event slug (optional)

### Response Fields
```json
{
    "proxyWallet": "0x...",
    "asset": "token_id",
    "conditionId": "0x...",
    "size": 123,              // Position size
    "avgPrice": 0.50,         // Average entry price
    "initialValue": 123,      // Entry value
    "currentValue": 150,      // Current value
    "cashPnl": 27,            // Absolute PnL
    "percentPnl": 21.9,       // Percent PnL
    "totalBought": 123,       // Total bought
    "realizedPnl": 0,         // Realized PnL
    "curPrice": 0.61,         // Current market price
    "redeemable": false,      // Can redeem (resolved winning)
    "mergeable": false,       // Can merge
    "title": "...",           // Market title
    "slug": "...",            // Market slug
    "eventSlug": "...",       // Event slug
    "outcome": "Yes",         // Position outcome
    "oppositeOutcome": "No",  // Opposite outcome
    "oppositeAsset": "...",   // Opposite token ID
    "negativeRisk": true      // Neg risk market
}
```

### Closed Positions
```
GET https://data-api.polymarket.com/closed-positions
```

### Trades
```
GET https://data-api.polymarket.com/trades
```

---

## Section 14: Market Data Fields (Gamma) ✅ VERIFIED

### Event Fields
```json
{
    "id": "string",
    "slug": "string",
    "title": "string",
    "description": "string",
    "negRisk": boolean,
    "negRiskAugmented": boolean,
    "negRiskFeeBips": number,
    "enableOrderBook": boolean,
    "closed": boolean,
    "closedTime": "ISO8601",
    "markets": [Market]
}
```

### Market Fields
```json
{
    "id": "string",
    "question": "string",
    "conditionId": "0x...",
    "slug": "string",
    "outcomes": ["Yes", "No"],
    "outcomePrices": "0.65,0.35",  // Comma-separated
    "volume": "1234567.89",
    "volume24hr": 50000.0,
    "liquidity": "123456.78",
    "bestBid": 0.64,
    "bestAsk": 0.66,
    "spread": 0.02,
    "lastTradePrice": 0.65,
    "clobTokenIds": ["tokenId_yes", "tokenId_no"],
    "closed": boolean,
    "active": boolean,
    "archived": boolean,
    "acceptingOrders": boolean,
    "enableOrderBook": boolean,
    "negRisk": boolean,
    "tickSize": "0.01"
}
```

### Key Relationships
- **Event ID → Markets:** Event contains markets array
- **Condition ID:** Links CLOB order to market
- **CLOB Token IDs:** Required for placing orders

---

## References

1. Rate Limits: https://docs.polymarket.com/quickstart/introduction/rate-limits
2. Authentication: https://docs.polymarket.com/developers/CLOB/authentication
3. Orders: https://docs.polymarket.com/developers/CLOB/orders/orders
4. WebSocket: https://docs.polymarket.com/developers/CLOB/websocket/wss-overview
5. Neg Risk: https://docs.polymarket.com/developers/neg-risk/overview
6. Geoblock: https://docs.polymarket.com/developers/CLOB/geoblock
7. Changelog: https://docs.polymarket.com/changelog/changelog
8. py-clob-client: https://github.com/Polymarket/py-clob-client
9. rs-clob-client: https://github.com/Polymarket/rs-clob-client
10. L2 Methods: https://docs.polymarket.com/developers/CLOB/clients/methods-l2
