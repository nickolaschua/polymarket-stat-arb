# Polymarket API Reference - Comprehensive Research

## Table of Contents
1. [Gamma API](#1-gamma-api)
2. [CLOB API](#2-clob-api)
3. [Historical Data & Backtesting](#3-historical-data--backtesting)
4. [py-clob-client Python Library](#4-py-clob-client-python-library)
5. [Rate Limits](#5-rate-limits)
6. [Key Limitations & Gotchas](#6-key-limitations--gotchas)

---

## 1. Gamma API

**Base URL:** `https://gamma-api.polymarket.com`

The Gamma API provides market metadata, discovery, and event information. It is the primary source for finding markets, understanding their structure, and getting current pricing snapshots. No authentication is required.

### 1.1 Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/markets` | GET | List all markets with filtering/pagination |
| `/markets/{id}` | GET | Get a specific market by ID |
| `/events` | GET | List all events (each event contains nested markets) |
| `/events/{id}` | GET | Get a specific event by ID |

### 1.2 GET /markets - Response Fields

The `/markets` endpoint returns an array of market objects. Key fields include:

#### Core Identity Fields
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique market identifier |
| `question` | string | The market question (e.g., "Will X happen?") |
| `conditionId` | string | On-chain condition ID (used by CLOB for trading) |
| `slug` | string | URL-friendly market identifier |
| `ticker` | string | Short ticker symbol |
| `title` | string | Market title |
| `subtitle` | string | Market subtitle |
| `description` | string | Full market description |

#### Pricing & Liquidity Fields
| Field | Type | Description |
|-------|------|-------------|
| `outcomePrices` | string | **Stringified JSON array** of prices, e.g., `'["0.52","0.48"]'` - must be parsed |
| `outcomes` | string | Stringified JSON array of outcome names, e.g., `'["Yes","No"]'` |
| `liquidity` | number | Total liquidity |
| `liquidityClob` | number/null | CLOB-specific liquidity |
| `liquidityAmm` | number/null | AMM-specific liquidity |
| `volume` | number | Total volume traded |
| `volume24hr` | number | 24-hour volume |
| `volume1wk` | number | 1-week volume |
| `volume1mo` | number | 1-month volume |
| `volume1yr` | number | 1-year volume |
| `openInterest` | number | Current open interest |

#### Token & Trading Fields
| Field | Type | Description |
|-------|------|-------------|
| `clobTokenIds` | string | **Stringified JSON array** of CLOB token IDs (needed for CLOB API calls) |
| `enableOrderBook` | boolean/null | Whether CLOB trading is enabled for this market |
| `marketMakerAddress` | string | Address of the market maker contract |
| `denominationToken` | string | Token used for denomination (usually USDC) |
| `fee` | string | Fee percentage |

#### Negative Risk Fields
| Field | Type | Description |
|-------|------|-------------|
| `negRisk` | boolean/null | Whether this is a negative-risk event market |
| `negRiskMarketID` | string/null | The neg-risk market group ID |
| `negRiskFeeBips` | integer/null | Neg-risk fee in basis points |

#### Status & Timing Fields
| Field | Type | Description |
|-------|------|-------------|
| `active` | boolean | Whether the market is currently active |
| `closed` | boolean | Whether the market has closed |
| `archived` | boolean | Whether the market is archived |
| `new` | boolean | Whether the market is newly created |
| `featured` | boolean | Whether the market is featured |
| `restricted` | boolean | Whether the market has restrictions |
| `startDate` | string | Market start date (ISO) |
| `endDate` | string | Market end date (ISO) |
| `creationDate` | string | Creation date |
| `createdAt` | string | Created timestamp |
| `updatedAt` | string | Updated timestamp |
| `closedTime` | string/null | When the market was closed |

#### Display & Metadata Fields
| Field | Type | Description |
|-------|------|-------------|
| `image` | string | Market image URL |
| `icon` | string | Market icon URL |
| `category` | string | Market category |
| `subcategory` | string | Market subcategory |
| `resolutionSource` | string | Source used for resolution |
| `commentCount` | integer/null | Number of comments |
| `commentsEnabled` | boolean | Whether comments are enabled |
| `competitive` | number | Competitive score |

#### Query Parameters
| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | integer | Number of results to return |
| `offset` | integer | Pagination offset |
| `order` | string | Field to order by (e.g., `id`, `volume`) |
| `ascending` | boolean | Sort direction |
| `closed` | boolean | Filter by closed status |
| `active` | boolean | Filter by active status |
| `tag` | string | Filter by tag |
| `slug` | string | Filter by slug |

**Example Request:**
```
GET https://gamma-api.polymarket.com/markets?limit=50&offset=0&closed=false&order=volume&ascending=false
```

### 1.3 GET /events - Response Fields

Events are containers for related markets. For example, "2024 US Presidential Election" is an event containing markets for each candidate.

#### Event-Level Fields
| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Event identifier |
| `title` | string | Event title |
| `slug` | string | URL-friendly identifier |
| `description` | string | Event description |
| `startDate` | string | Event start date |
| `endDate` | string | Event end date |
| `image` | string | Event image |
| `icon` | string | Event icon |
| `active` | boolean | Whether the event is active |
| `closed` | boolean | Whether the event is closed |
| `negRisk` | boolean/null | Whether this is a negative-risk event |
| `negRiskMarketID` | string/null | Neg-risk market group ID |
| `negRiskFeeBips` | integer/null | Neg-risk fee in basis points |
| `enableOrderBook` | boolean/null | CLOB trading enabled |
| `liquidityAmm` | number/null | AMM liquidity |
| `liquidityClob` | number/null | CLOB liquidity |
| `commentCount` | integer/null | Comment count |
| `markets` | object[] | **Nested array of full market objects** (same schema as `/markets`) |
| `tags` | object[] | Array of tag objects |
| `categories` | object[] | Array of category objects |
| `collections` | object[] | Array of collection objects |
| `series` | object[] | Array of series objects |

#### Query Parameters
Same as `/markets`: `limit`, `offset`, `order`, `ascending`, `closed`, `active`, `tag`, `slug`.

**Example Request:**
```
GET https://gamma-api.polymarket.com/events?limit=50&offset=0&closed=false&order=id&ascending=false
```

**Key Insight:** The `/events` endpoint is the most efficient way to fetch all markets because it groups related markets together. For multi-outcome events (like "Who will win the election?"), the event contains all candidate markets, and `negRisk=true` indicates they are linked.

### 1.4 Fetching Strategies

1. **By Slug** - Best for individual market/event lookups: `GET /markets?slug=will-x-happen`
2. **By Tags** - Filter by category or sport: `GET /markets?tag=politics`
3. **Via Events** - Most efficient for bulk retrieval: `GET /events?closed=false&limit=50`

---

## 2. CLOB API

**Base URL:** `https://clob.polymarket.com`

The Central Limit Order Book (CLOB) API handles all trading operations. It supports both REST and WebSocket connections.

### 2.1 REST Endpoints

#### Public (No Auth Required)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/markets` | GET | Get CLOB market data |
| `/simplified-markets` | GET | Get simplified market data (paginated) |
| `/market/{condition_id}` | GET | Get specific market by condition ID |
| `/midpoint` | GET | Get midpoint price for a token |
| `/price` | GET | Get price for a specific side (BUY/SELL) |
| `/spread` | GET | Get bid-ask spread |
| `/book` | GET | Get order book for a token |
| `/books` | GET | Get multiple order books |
| `/last-trade-price` | GET | Get last trade price |
| `/trades` | GET | Get trade history |
| `/market/trades/events/{condition_id}` | GET | Get public market trade events |
| `/prices-history` | GET | Get historical price timeseries |
| `/tick-size` | GET | Get minimum tick size for a market |

#### Authenticated (L2 - API Key Required)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/order` | POST | Place a single order |
| `/order` | DELETE | Cancel a single order |
| `/order/{id}` | GET | Get order by ID |
| `/orders` | GET | Get open orders |
| `/orders` | DELETE | Cancel multiple orders |
| `/cancel-all` | DELETE | Cancel all open orders |
| `/cancel-market-orders` | DELETE | Cancel all orders for a market |
| `/reward/markets` | GET | Get reward market info |
| `/reward/earnings` | GET | Get reward earnings |
| `/notifications` | GET | Get notifications |
| `/notifications` | DELETE | Dismiss notifications |
| `/heartbeat` | POST | Send heartbeat for order protection |

### 2.2 Order Types

All orders on Polymarket are fundamentally **limit orders**. "Market orders" are implemented as aggressively-priced limit orders that execute immediately.

| Order Type | Code | Description |
|------------|------|-------------|
| **GTC** | `OrderType.GTC` | Good Till Cancelled - remains on book until filled or cancelled |
| **GTD** | `OrderType.GTD` | Good Till Date - expires at a specified time |
| **FOK** | `OrderType.FOK` | Fill or Kill - must fill entirely immediately or cancel |
| **FAK** | - | Fill and Kill - fills what it can immediately, cancels the rest |

**Additional Order Options:**
- `post_only=True` - Order will only be placed as a maker (won't take liquidity). Cannot be combined with FOK/FAK.
- `nonce` - For on-chain cancellation support
- `expiration` - Unix timestamp for order expiration (0 = no expiration)

**Precision Requirements:**
- GTC orders: Flexible precision based on market tick size
- FOK sell orders: maker amount limited to 2 decimal places, taker amount to 4 decimal places
- FOK: product of size x price must not exceed 2 decimal places

**Batch Orders:**
- Up to **15 orders** can be submitted in a single batch request (increased from 5)

### 2.3 WebSocket Channels

**WebSocket Base URL:** `wss://ws-subscriptions-clob.polymarket.com/ws/`

There is also a separate real-time data service (RTDS): `wss://ws-live-data.polymarket.com`

#### Market Channel (Public, No Auth)
**URL:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`

Subscribe to receive real-time updates for markets:

| Event Type | Description |
|------------|-------------|
| `book` | Level 2 order book updates (bids and asks) |
| `price_change` | Price change events |
| `last_trade_price` | Last trade price updates |
| `trade` | Trade execution events |

**Subscription message format:**
```json
{
  "auth": {},
  "type": "subscribe",
  "markets": ["<condition_id>"],
  "assets_ids": ["<token_id>"]
}
```

#### User Channel (Authenticated)
**URL:** `wss://ws-subscriptions-clob.polymarket.com/ws/user`

Requires CLOB API authentication. Provides:
- Order status updates (fills, cancellations)
- Personal trade notifications
- Position changes

### 2.4 Authentication

Polymarket uses a **two-level authentication system**:

#### Level 1 (L1) - Private Key
- Used to sign orders on-chain
- Required for creating API credentials
- Supports multiple wallet types:
  - **EOA/MetaMask** (`signature_type=0`, default)
  - **Magic/Email wallets** (`signature_type=1`, requires `funder` address)
  - **Proxy wallets** (`signature_type=1`, requires `funder` address)

#### Level 2 (L2) - API Key
- Generated from L1 authentication via `create_or_derive_api_creds()`
- Consists of three parts: `apiKey`, `secret`, `passphrase`
- Used to authenticate REST API requests
- Requests signed using **HMAC-SHA256**
- Required for all authenticated endpoints (orders, cancellations, etc.)

**Authentication Flow:**
```python
# 1. Initialize client with private key (L1)
client = ClobClient("https://clob.polymarket.com", key=PRIVATE_KEY, chain_id=137)

# 2. Create API credentials (L2)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

# 3. Now you can use authenticated endpoints
client.post_order(order, OrderType.GTC)
```

**API Key Headers (sent with each authenticated request):**
- `POLY_API_KEY` - The API key
- `POLY_TIMESTAMP` - Current timestamp
- `POLY_SIGNATURE` - HMAC-SHA256 signature
- `POLY_PASSPHRASE` - The passphrase
- `POLY_NONCE` - Request nonce

### 2.5 Heartbeat System

Once started, heartbeats must be sent **every 10 seconds**. If heartbeats stop, **all open orders are automatically cancelled**. This protects against connection loss.

```python
heartbeat_id = "my-session-123"
result = client.post_heartbeat(heartbeat_id)
```

---

## 3. Historical Data & Backtesting

### 3.1 GET /prices-history Endpoint

**Endpoint:** `GET https://clob.polymarket.com/prices-history`

This is the primary endpoint for historical price data.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `market` | string | Yes | CLOB token ID (NOT condition ID) |
| `startTs` | integer | No | Start Unix timestamp |
| `endTs` | integer | No | End Unix timestamp |
| `startDate` | string | No | Start date (ISO format) |
| `endDate` | string | No | End date (ISO format) |
| `interval` | string | No | Predefined interval: `1m`, `1h`, `6h`, `1d`, `1w`, `max` |
| `fidelity` | integer | No | Custom resolution in minutes |

**Note:** `startTs/endTs` and `interval` are **mutually exclusive**. Use one or the other.

#### Response Format
```json
{
  "history": [
    { "t": 1699450000, "p": 0.52 },
    { "t": 1699453600, "p": 0.55 },
    ...
  ]
}
```

Where `t` = Unix timestamp, `p` = price.

### 3.2 GET /trades Endpoint

Provides individual trade records, useful for building your own candles/timeseries.

**Endpoint:** `GET https://clob.polymarket.com/trades`

| Parameter | Type | Description |
|-----------|------|-------------|
| `market` | string | Condition ID to filter by |
| `asset_id` | string | Token ID to filter by |
| `before` | integer | Unix timestamp upper bound |
| `after` | integer | Unix timestamp lower bound |

**Response:**
```json
[
  {
    "tradeId": "0x...",
    "market": "0xConditionId...",
    "price": 0.5,
    "size": 100.0,
    "timestamp": 1699450000
  }
]
```

### 3.3 GET /market/trades/events/{condition_id}

Public endpoint for market trade events. No authentication required.

### 3.4 CRITICAL LIMITATION: Resolved Markets

**Known Issue (GitHub Issue #216):** The `/prices-history` endpoint returns **empty data for resolved/closed markets at granularities below 12 hours**.

- Requesting `fidelity=720` (12 hours) works for resolved markets
- Requesting `fidelity=60` (1 hour) or finer returns empty `history: []`
- This affects even extremely high-volume markets like the 2024 US Presidential Election
- This is a **major limitation for backtesting**

### 3.5 Workarounds for Historical Data

1. **Use 12-hour fidelity for resolved markets:** `fidelity=720` still works but gives very coarse data
2. **Collect trade data in real-time:** Use `GET /trades` with time range filters on active markets and store locally
3. **Use the `/trades` endpoint:** Individual trade records may still be available for resolved markets (with pagination)
4. **Third-party sources:**
   - [PolymarketAnalytics.com](https://polymarketanalytics.com) - Community analytics dashboard
   - Dune Analytics - On-chain data queries for Polymarket contracts
   - Build your own data pipeline collecting from WebSocket feeds

### 3.6 Recommended Backtesting Data Pipeline

```
Active Markets:
  WebSocket (real-time) --> Local DB (tick-by-tick)
  GET /trades (polling)  --> Local DB (trade records)
  GET /prices-history    --> Local DB (OHLC candles)

Resolved Markets:
  GET /prices-history?fidelity=720  --> 12-hour candles only
  GET /trades (paginated)            --> Individual trade records
  On-chain data via Dune/Subgraph    --> All historical transactions
```

---

## 4. py-clob-client Python Library

**Package:** `py-clob-client`
**Install:** `pip install py-clob-client`
**GitHub:** https://github.com/Polymarket/py-clob-client

### 4.1 Client Initialization

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

# Read-only client (no auth needed)
client = ClobClient("https://clob.polymarket.com")

# Trading client (requires private key)
client = ClobClient(
    "https://clob.polymarket.com",
    key="0xYourPrivateKey",
    chain_id=137,                # Polygon mainnet
    signature_type=0,            # 0=EOA/MetaMask (default), 1=Magic/Proxy
    funder="0xFunderAddress"     # Required for signature_type=1
)

# Set up API credentials for authenticated calls
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)
```

### 4.2 Complete Method Reference

#### Market Data (Public, No Auth)

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `get_markets()` | - | dict | Get all markets (full format) |
| `get_simplified_markets()` | - | dict | Get simplified markets (paginated) |
| `get_market(condition_id)` | condition_id: str | dict | Get specific market by condition ID |
| `get_midpoint(token_id)` | token_id: str | dict | Get midpoint price `{"mid": "0.55"}` |
| `get_price(token_id, side)` | token_id: str, side: "BUY"/"SELL" | dict | Get price for side `{"price": "0.56"}` |
| `get_spread(token_id)` | token_id: str | dict | Get bid-ask spread |
| `get_last_trade_price(token_id)` | token_id: str | dict | Get last trade price |
| `get_order_book(token_id)` | token_id: str | OrderBook | Get L2 order book |
| `get_order_books(params)` | params: list[BookParams] | list | Get multiple order books |
| `get_tick_size(condition_id)` | condition_id: str | dict | Get minimum tick size |
| `get_market_trades_events(condition_id)` | condition_id: str | list | Get public market trade events |

#### Order Management (Authenticated)

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `create_order(order_args)` | OrderArgs | SignedOrder | Create and sign a limit order |
| `create_market_order(order_args)` | MarketOrderArgs | SignedOrder | Create and sign a market order |
| `post_order(order, order_type, post_only)` | SignedOrder, OrderType, bool | dict | Submit order to exchange |
| `get_order(order_id)` | order_id: str | dict | Get specific order by ID |
| `get_orders(params)` | OpenOrderParams | list | Get open orders (filterable) |
| `cancel(order_id)` | order_id: str | dict | Cancel a single order |
| `cancel_orders(order_ids)` | order_ids: list[str] | dict | Cancel multiple orders |
| `cancel_all()` | - | dict | Cancel ALL open orders |
| `cancel_market_orders(market)` | market: str | dict | Cancel all orders for a market |

#### Trade History (Authenticated)

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `get_trades(params)` | TradeParams (optional) | list | Get trade history with filters |

#### Heartbeat & Scoring

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `post_heartbeat(heartbeat_id)` | heartbeat_id: str | dict | Send heartbeat (every 10s) |
| `is_order_scoring(params)` | OrderScoringParams | dict | Check if order is earning rewards |
| `are_orders_scoring(params)` | OrdersScoringParams | dict | Check multiple orders for scoring |

#### Notifications

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `get_notifications()` | - | list | Get user notifications |
| `drop_notifications(params)` | DropNotificationParams | dict | Dismiss notifications |

#### Credentials

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `create_or_derive_api_creds()` | - | ApiCreds | Create or derive API key/secret/passphrase |
| `set_api_creds(creds)` | ApiCreds | None | Set credentials on the client |

### 4.3 Key Types

```python
from py_clob_client.clob_types import (
    OrderArgs,           # Limit order parameters
    MarketOrderArgs,     # Market order parameters
    OrderType,           # GTC, GTD, FOK
    OpenOrderParams,     # Filter params for get_orders()
    TradeParams,         # Filter params for get_trades()
    BookParams,          # Params for get_order_books()
    OrderScoringParams,  # Single order scoring check
    OrdersScoringParams, # Multiple orders scoring check
    DropNotificationParams,  # Notification dismissal
    ApiCreds,            # API credentials object
)
from py_clob_client.order_builder.constants import BUY, SELL
```

### 4.4 Usage Examples

#### Read-Only Price Monitoring
```python
from py_clob_client.client import ClobClient

client = ClobClient("https://clob.polymarket.com")
token_id = "34097058504275310827233323421517291090691602969494795225921954353603704046623"

midpoint = client.get_midpoint(token_id)      # {"mid": "0.55"}
buy_price = client.get_price(token_id, "BUY") # {"price": "0.56"}
sell_price = client.get_price(token_id, "SELL") # {"price": "0.54"}
spread = client.get_spread(token_id)
book = client.get_order_book(token_id)
last = client.get_last_trade_price(token_id)
```

#### Place a Limit Order
```python
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

order_args = OrderArgs(
    token_id=token_id,
    price=0.50,
    size=20.0,
    side=BUY,
    fee_rate_bps=0,
    nonce=0,
    expiration=0,
)
signed_order = client.create_order(order_args)
response = client.post_order(signed_order, OrderType.GTC)
```

#### Place a Market Order (FOK)
```python
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

buy_order = MarketOrderArgs(
    token_id=token_id,
    amount=100.0,   # $100 USDC to spend
    side=BUY,
    order_type=OrderType.FOK,
)
signed = client.create_market_order(buy_order)
response = client.post_order(signed, OrderType.FOK)
```

#### Get Trades with Filters
```python
from py_clob_client.clob_types import TradeParams

params = TradeParams(
    market="0xConditionId...",
    asset_id="token_id_here",
    before=1699500000,
    after=1699400000,
)
trades = client.get_trades(params)
```

---

## 5. Rate Limits

All rate limits are enforced using **Cloudflare's throttling system**. When limits are exceeded, requests are throttled (delayed/queued), not immediately rejected. HTTP **429** status codes are returned when throttled.

### 5.1 General Rate Limits

| Category | Limit | Notes |
|----------|-------|-------|
| Public/Read-Only (Gamma API) | ~1,000 requests/hour | Non-trading queries |
| CLOB Public Endpoints | Throttled via Cloudflare | Sliding window |
| Trading Endpoints (orders) | ~3,000 requests/10 minutes | Per API key |
| Order Placement | ~60 orders/minute | Per API key |

### 5.2 Rate Limit Behavior
- Some endpoints allow **short bursts** above the sustained rate
- Limits reset based on **sliding time windows** (per 10 seconds, per minute)
- When exceeded, requests are **throttled** (delayed), not dropped
- Repeated violations may result in temporary IP blocks

### 5.3 Practical Guidance
- For market scanning: space requests ~100ms apart (safe for Gamma API)
- For order placement: stay under 1 order/second sustained
- For price monitoring: use WebSocket instead of polling
- For bulk data: use pagination with reasonable delays between pages

---

## 6. Key Limitations & Gotchas

### 6.1 Historical Data Limitations
- `/prices-history` returns **empty data for resolved markets below 12-hour granularity**
- This is the biggest obstacle for backtesting resolved markets
- Workaround: collect data in real-time or use on-chain data sources

### 6.2 Data Format Quirks
- `outcomePrices` in Gamma API is a **stringified JSON array**, not a native array
  - Raw: `'["0.52","0.48"]'`
  - Must parse: `json.loads(market['outcomePrices'])`
- `clobTokenIds` is also a stringified JSON array
- `outcomes` is also a stringified JSON array

### 6.3 Token ID vs Condition ID
- **Condition ID**: Identifies a market (used in Gamma API and CLOB market lookups)
- **Token ID**: Identifies a specific outcome token (YES or NO) within a market (used for pricing, order book, and trading)
- A binary market has TWO token IDs (one for YES, one for NO) under ONE condition ID
- Get token IDs from Gamma API's `clobTokenIds` field

### 6.4 Negative Risk Events
- Events with `negRisk=true` have linked markets where all outcomes are mutually exclusive
- Enables capital efficiency: buying multiple outcomes in the same event shares collateral
- Important for combinatorial/portfolio strategies

### 6.5 Heartbeat Requirement
- Once you start sending heartbeats, you MUST continue every 10 seconds
- Missing heartbeats = ALL orders cancelled
- Do NOT start heartbeats unless you have a reliable connection

### 6.6 Chain Considerations
- Polymarket operates on **Polygon mainnet** (chain_id = 137)
- Orders are signed off-chain but settled on-chain
- EOA wallets need token allowances set before trading

---

## Sources

- [Polymarket API Rate Limits](https://docs.polymarket.com/quickstart/introduction/rate-limits)
- [Polymarket CLOB Introduction](https://docs.polymarket.com/developers/CLOB/introduction)
- [Polymarket Authentication](https://docs.polymarket.com/developers/CLOB/authentication)
- [Polymarket Endpoints Reference](https://docs.polymarket.com/quickstart/reference/endpoints)
- [Polymarket Methods Overview](https://docs.polymarket.com/developers/CLOB/clients/methods-overview)
- [Polymarket Historical Timeseries Data](https://docs.polymarket.com/developers/CLOB/timeseries)
- [Polymarket Get Markets (Gamma)](https://docs.polymarket.com/developers/gamma-markets-api/get-markets)
- [Polymarket Get Events (Gamma)](https://docs.polymarket.com/developers/gamma-markets-api/get-events)
- [Polymarket Gamma Structure](https://docs.polymarket.com/developers/gamma-markets-api/gamma-structure)
- [Polymarket WSS Overview](https://docs.polymarket.com/developers/CLOB/websocket/wss-overview)
- [Polymarket Place Single Order](https://docs.polymarket.com/developers/CLOB/orders/create-order)
- [Polymarket Price History API](https://docs.polymarket.com/api-reference/pricing/get-price-history-for-a-traded-token)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
- [py-clob-client Issue #216 - Empty data for resolved markets](https://github.com/Polymarket/py-clob-client/issues/216)
- [py-clob-client Issue #189 - CLOB Historical Pricing blank response](https://github.com/Polymarket/py-clob-client/issues/189)
- [py-clob-client Issue #147 - Rate limit burst vs throttle](https://github.com/Polymarket/py-clob-client/issues/147)
- [Polymarket API Architecture (Medium)](https://medium.com/@gwrx2005/the-polymarket-api-architecture-endpoints-and-use-cases-f1d88fa6c1bf)
