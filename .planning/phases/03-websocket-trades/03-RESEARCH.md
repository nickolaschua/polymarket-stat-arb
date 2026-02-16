# Phase 3: WebSocket Trades + Resolution Tracker - Research

**Researched:** 2026-02-17
**Domain:** Polymarket CLOB WebSocket trade stream + market resolution detection
**Confidence:** HIGH

<research_summary>
## Summary

Researched the Polymarket WebSocket API ecosystem for building a real-time trade listener and resolution tracker. The CLOB WebSocket Market Channel (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) provides unauthenticated access to `last_trade_price` events with price, size, side, and timestamp per token. The Python `websockets` library (v16.0) provides built-in async reconnection via iterator pattern, making it the ideal client library.

Key findings:
- **No authentication needed** for the market channel trade stream
- **`last_trade_price` events** provide exactly the fields we need for trade storage
- **`market_resolved` events** are available via feature flag (`custom_feature_enabled: true`) but should be supplemented with Gamma API polling for reliability
- **500 instrument limit** per WebSocket connection requires connection pooling for 8,000+ markets
- **Application-level "PING" required** every 10 seconds (separate from protocol-level ping/pong)
- **No trade_id in WebSocket events** -- our trades table trade_id column will be NULL for WebSocket trades (vs REST trades which have IDs). Dedup via (ts, token_id, price, size, side) composite.
- **websockets v16.0** has built-in reconnection, making custom retry logic unnecessary

**Primary recommendation:** Use `websockets` async iterator for auto-reconnect, subscribe to CLOB market channel for `last_trade_price` events, implement connection pooling for >500 tokens, and supplement resolution detection with Gamma API polling.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| websockets | >=16.0 | Async WebSocket client | Built-in reconnect iterator, protocol ping/pong, backpressure management. Already in requirements.txt as >=12.0 (upgrade to >=16.0) |
| asyncio.Queue | stdlib | Message buffering | Decouple WebSocket receiver from DB writer. No external dependency needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncpg | (existing) | DB writes | insert_trades() already implemented with COPY protocol |
| httpx | (existing) | Gamma API polling | Resolution tracker polls GET /markets for outcomePrices |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| websockets | aiohttp WS | aiohttp ~1.5x faster but no built-in reconnect, WS is secondary feature |
| websockets | picows | picows faster (Cython) but tiny community, callback API, no reconnect |
| websockets | websocket-client | websocket-client is synchronous (would need run_in_executor), not ideal for async codebase |
| CLOB WS | RTDS | RTDS has richer trade metadata (user info) but organizes by event_slug not token_id; CLOB aligns with our per-token data model |

### No New Dependencies Needed
The `websockets` library is already in requirements.txt. No new packages required for Phase 3. Resolution tracker uses existing httpx + Gamma API patterns from Phase 2 collectors.
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Structure
```
src/collector/
├── trade_listener.py          # WebSocket trade stream listener
├── resolution_tracker.py      # Gamma API polling for market resolution
├── market_metadata.py         # (existing) Phase 2
├── price_snapshots.py         # (existing) Phase 2
└── orderbook_snapshots.py     # (existing) Phase 2
```

### Pattern 1: Async Iterator Reconnection (websockets v14+)
**What:** Use `connect()` as async iterator for automatic reconnection with exponential backoff
**When to use:** Any production WebSocket client that needs resilience
**Source:** websockets official documentation
```python
from websockets.asyncio.client import connect

async def listen():
    async for ws in connect("wss://ws-subscriptions-clob.polymarket.com/ws/market"):
        try:
            await subscribe(ws, token_ids)
            await send_pings_and_receive(ws)
        except ConnectionClosed:
            continue  # auto-reconnects with exponential backoff
```

### Pattern 2: Producer-Consumer with asyncio.Queue
**What:** WebSocket receiver pushes to queue, DB writer drains queue in batches
**When to use:** When message rate is high and DB writes should be batched
```python
queue = asyncio.Queue(maxsize=10000)

# Producer: WebSocket receiver
async def receiver(ws, queue):
    async for message in ws:
        trade = parse_trade(message)
        await queue.put(trade)

# Consumer: batch DB writer
async def writer(pool, queue, batch_size=1000):
    batch = []
    while True:
        trade = await asyncio.wait_for(queue.get(), timeout=5.0)
        batch.append(trade)
        if len(batch) >= batch_size:
            await insert_trades(pool, batch)
            batch.clear()
```

### Pattern 3: Connection Pool for >500 Instruments
**What:** Multiple WebSocket connections, each handling up to 500 token IDs
**When to use:** When monitoring more than 500 tokens (our case: 8,000+ markets = 16,000+ tokens)
```python
# Split token_ids into chunks of 500
chunks = [token_ids[i:i+500] for i in range(0, len(token_ids), 500)]
# Create one WebSocket connection per chunk
tasks = [listen_chunk(chunk, queue) for chunk in chunks]
await asyncio.gather(*tasks)
```

### Pattern 4: Application-Level Heartbeat
**What:** Send "PING" text message every 10 seconds (Polymarket-specific requirement)
**When to use:** Always -- connections drop without this
```python
async def heartbeat(ws):
    while True:
        await asyncio.sleep(10)
        await ws.send("PING")
```

### Anti-Patterns to Avoid
- **Subscribing by condition_id only:** Must subscribe with `assets_ids` (token IDs), not just condition IDs
- **Skipping re-subscription after reconnect:** After reconnect, all subscriptions are lost. Must re-subscribe at the top of each reconnect loop
- **Blocking the event loop with sync CLOB calls in the listener:** Use run_in_executor for any sync operations
- **Processing messages synchronously:** Use asyncio.Queue to decouple receive from processing/DB writes
- **Single connection for all tokens:** Will fail at >500 instruments. Plan for connection pooling from the start
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket reconnection | Custom retry loop with sleep | `websockets` async iterator pattern | Built-in exponential backoff, handles all edge cases (DNS, TLS, protocol errors) |
| Protocol ping/pong | Manual ping frame sending | `websockets` default `ping_interval=20` | Library handles automatically, tracks latency |
| Trade deduplication | Complex hash-based dedup | PostgreSQL UNIQUE index + ON CONFLICT | DB-level dedup is atomic and correct. trades.trade_id index handles REST trades; for WS trades without trade_id, use (ts, token_id, price, size, side) |
| Message parsing | Manual JSON field extraction | Pydantic model or simple dict access | Event structure is well-defined, use type checking |
| Batch insert | Custom batching logic | asyncio.Queue + existing insert_trades() | Queue provides natural buffering, COPY protocol handles throughput |

**Key insight:** The `websockets` library v14+ solved the reconnection problem that used to require custom code. The async iterator pattern replaces hundreds of lines of retry/backoff/state management with a simple `async for ws in connect(url)` loop.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Missing Application-Level PING
**What goes wrong:** WebSocket connection silently drops after ~30 seconds
**Why it happens:** Polymarket requires a text "PING" message every 10 seconds. This is NOT the same as WebSocket protocol-level ping/pong (which `websockets` handles automatically). You need both.
**How to avoid:** Run a concurrent heartbeat task that sends `await ws.send("PING")` every 10 seconds
**Warning signs:** Connection drops regularly at ~30s intervals, no error messages

### Pitfall 2: No trade_id in WebSocket Events
**What goes wrong:** trades.trade_id is NULL for all WebSocket trades, breaking dedup assumptions
**Why it happens:** The `last_trade_price` event does NOT include a trade_id field. Only REST API trade queries provide trade_id.
**How to avoid:** Accept NULL trade_id for WebSocket trades. Dedup strategy: the COPY insert with UniqueViolationError fallback handles duplicates at DB level. For WS trades, near-simultaneous identical (ts, token_id, price, size, side) tuples are rare enough that some duplication is acceptable.
**Warning signs:** NULL trade_id in trades table (expected, not a bug)

### Pitfall 3: 500-Instrument Limit Per Connection
**What goes wrong:** Subscription silently fails or connection becomes unstable with >500 token IDs
**Why it happens:** Polymarket enforces a maximum of 500 instruments per CLOB WebSocket connection
**How to avoid:** Implement connection pooling from the start. Split token_ids into chunks of <=500 per connection.
**Warning signs:** Missing trade data for some tokens, no explicit error message

### Pitfall 4: Subscription Lost After Reconnect
**What goes wrong:** After auto-reconnect, no trade messages arrive
**Why it happens:** WebSocket subscriptions are ephemeral -- they don't survive reconnection. The async iterator reconnects the transport, but the application must re-subscribe.
**How to avoid:** Always re-send subscription message at the top of the reconnect loop (inside the `async for ws in connect(...)` block)
**Warning signs:** Trade messages stop after network blip, connection appears healthy

### Pitfall 5: Events Arrive as JSON Arrays
**What goes wrong:** Parser expects single event object, gets array of events
**Why it happens:** Polymarket batches multiple events in a single WebSocket message as a JSON array
**How to avoid:** Always check if parsed message is a list vs dict. Process each event in the array individually.
**Warning signs:** JSON parse errors, missing events

### Pitfall 6: String vs Numeric Types in Trade Events
**What goes wrong:** Type errors when inserting price/size as strings into float columns
**Why it happens:** CLOB WebSocket trade events use string types for price ("0.52") and size ("100"), not numeric. Timestamp is also a string of Unix milliseconds.
**How to avoid:** Explicit type conversion: `float(event["price"])`, `float(event["size"])`, `datetime.fromtimestamp(int(event["timestamp"]) / 1000, tz=timezone.utc)`
**Warning signs:** asyncpg DataError on insert, incorrect timestamp values

### Pitfall 7: market_resolved Feature Flag
**What goes wrong:** No resolution events received despite subscribing
**Why it happens:** The `market_resolved` WebSocket event requires `custom_feature_enabled: true` in the subscription message. This is a feature flag that may not be available to all clients.
**How to avoid:** Don't rely solely on WebSocket for resolution detection. Use Gamma API polling as primary resolution tracker, WebSocket events as supplementary/real-time notification.
**Warning signs:** Markets resolve on the website but no WebSocket event received
</common_pitfalls>

<code_examples>
## Code Examples

### CLOB WebSocket Subscription Format
Source: Polymarket official documentation (docs.polymarket.com/developers/CLOB/websocket/market-channel)
```python
# Initial subscription (sent on connection open)
subscription = {
    "assets_ids": [
        "87769991026114894163580777793845523168226980076553814689875238288185044414090",
        "65818619657568813474341868652308942079804919287380422192892211131408793125422"
    ],
    "type": "market"
}
await ws.send(json.dumps(subscription))

# With feature flags for resolution events
subscription_with_features = {
    "assets_ids": ["<token_id_1>", "<token_id_2>"],
    "type": "market",
    "custom_feature_enabled": True
}
```

### last_trade_price Event Schema
Source: Polymarket official documentation
```python
# Incoming WebSocket message (after JSON parse)
trade_event = {
    "event_type": "last_trade_price",
    "asset_id": "<token_id>",           # maps to trades.token_id
    "market": "<condition_id>",          # parent market
    "price": "0.52",                     # string! must float()
    "size": "100",                       # string! must float()
    "side": "BUY",                       # "BUY" or "SELL"
    "fee_rate_bps": "200",               # basis points
    "timestamp": "1700000000000"         # Unix milliseconds string
}

# Transform to DB tuple:
trade_tuple = (
    datetime.fromtimestamp(int(event["timestamp"]) / 1000, tz=timezone.utc),  # ts
    event["asset_id"],                                                          # token_id
    event["side"],                                                              # side
    float(event["price"]),                                                      # price
    float(event["size"]),                                                       # size
    None,                                                                       # trade_id (not in WS events)
)
```

### market_resolved Event Schema
Source: Polymarket official documentation
```python
resolved_event = {
    "event_type": "market_resolved",
    "id": "<market_id>",
    "market": "<condition_id>",
    "winning_asset_id": "<token_id_of_winner>",
    "winning_outcome": "Yes",
    "assets_ids": ["<yes_token>", "<no_token>"],
    "outcomes": ["Yes", "No"],
    "timestamp": "1700000000000"
}
```

### Resolution Detection via Gamma API Polling
Source: Polymarket Gamma API (gamma-api.polymarket.com)
```python
# Poll for closed markets
response = await client.get("https://gamma-api.polymarket.com/events",
    params={"closed": True, "limit": 100, "offset": 0})

# Check outcomePrices for resolution
# When resolved: outcomePrices = '["1","0"]' (winner=1.0, loser=0.0)
# When unresolved: outcomePrices = '["0.52","0.48"]' (current prices)
for market in response:
    prices = json.loads(market["outcomePrices"])
    if "1" in prices:
        winner_idx = prices.index("1")
        winner_outcome = json.loads(market["outcomes"])[winner_idx]
        winner_token = json.loads(market["clobTokenIds"])[winner_idx]
```

### websockets Async Iterator Reconnection
Source: websockets v16.0 official documentation
```python
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

async def trade_listener(url, token_ids, queue):
    async for ws in connect(url):
        try:
            # Re-subscribe on every (re)connect
            await ws.send(json.dumps({
                "assets_ids": token_ids,
                "type": "market"
            }))
            # Start heartbeat task
            heartbeat = asyncio.create_task(ping_loop(ws))
            try:
                async for raw in ws:
                    events = json.loads(raw)
                    if isinstance(events, list):
                        for event in events:
                            if event.get("event_type") == "last_trade_price":
                                await queue.put(event)
                    elif isinstance(events, dict):
                        if events.get("event_type") == "last_trade_price":
                            await queue.put(events)
            finally:
                heartbeat.cancel()
        except ConnectionClosed:
            continue  # auto-reconnects
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| websockets legacy API | websockets v14+ async iterator | 2024 | Built-in reconnect, no custom retry code needed |
| Manual ping/pong code | websockets auto ping_interval=20 | Always | Protocol-level keepalive is automatic |
| websocket-client (sync) | websockets (async) | 2023+ | Async is standard for Python event loops |
| Custom reconnect with exponential backoff | `async for ws in connect(url)` | websockets v14 | One line replaces 50+ lines of retry logic |

**New patterns to consider:**
- **websockets v15.0+ proxy support:** Automatic SOCKS/HTTP proxy detection from system settings
- **websockets v16.0:** Requires Python >=3.10, has C extension for performance

**Deprecated/outdated:**
- **websockets.legacy module:** Deprecated in v14, removal planned by 2030. Use `websockets.asyncio.client` instead
- **websocket-client for async code:** Use `websockets` for async, `websocket-client` only for simple sync scripts
</sota_updates>

<polymarket_specific>
## Polymarket-Specific Details

### Connection Limits
- **Max 500 instruments (token_ids) per CLOB WebSocket connection**
- No documented maximum connections per IP
- No explicit message rate limits on receiving

### Heartbeat Requirements
| Service | Heartbeat Interval | Message |
|---------|-------------------|---------|
| CLOB WebSocket | Every 10 seconds | Send text `"PING"` |
| RTDS | Every 5 seconds | Send PING |
| CLOB REST (orders) | Every 10 seconds | POST /heartbeat (existing heartbeat.py) |

### Event Types Available on Market Channel
| Event Type | Triggered By | Use Case |
|------------|-------------|----------|
| `last_trade_price` | Trade execution (maker+taker match) | **Primary: trade data collection** |
| `book` | Initial subscribe + orderbook changes | Orderbook state recovery after reconnect |
| `price_change` | Order place/cancel affecting book | Incremental orderbook updates |
| `tick_size_change` | Price crossing 0.96/0.04 threshold | Tick size awareness |
| `best_bid_ask` | Best price changes (feature-flagged) | Spread monitoring |
| `market_resolved` | Market resolution (feature-flagged) | **Resolution detection (supplementary)** |
| `new_market` | New market created (feature-flagged) | Market discovery |

### Dynamic Subscription Management
```python
# Subscribe to additional tokens after initial connection
await ws.send(json.dumps({
    "assets_ids": ["<new_token_id>"],
    "type": "market",
    "operation": "subscribe"
}))

# Unsubscribe from tokens
await ws.send(json.dumps({
    "assets_ids": ["<old_token_id>"],
    "type": "market",
    "operation": "unsubscribe"
}))
```

### RTDS Alternative (Not Recommended for Our Use Case)
The Real-Time Data Socket at `wss://ws-live-data.polymarket.com` provides richer trade data (user pseudonyms, profile images) but organizes by event_slug/market_slug rather than token_id. Our per-token data model aligns better with the CLOB WebSocket.
</polymarket_specific>

<open_questions>
## Open Questions

1. **custom_feature_enabled reliability**
   - What we know: `market_resolved` and `best_bid_ask` events require this flag
   - What's unclear: Whether this flag is available to all clients or requires special access
   - Recommendation: Don't rely on it. Use Gamma API polling as primary resolution tracker, treat WebSocket `market_resolved` as a nice-to-have optimization

2. **Connection limit per IP**
   - What we know: 500 instruments per connection. No documented per-IP connection limit.
   - What's unclear: Whether there's an undocumented connection limit that would affect monitoring 16,000+ tokens (32+ connections)
   - Recommendation: Start with ~10 connections, monitor for throttling. Can test from Hetzner where we have live access.

3. **Trade deduplication without trade_id**
   - What we know: WebSocket `last_trade_price` events don't include trade_id. REST API trades do.
   - What's unclear: How often identical (ts, token_id, price, size, side) tuples occur legitimately
   - Recommendation: Accept potential minor duplication for WebSocket trades. The continuous aggregates (OHLCV) are volume-weighted so small duplicates have negligible impact. Can refine dedup strategy after observing real data.

4. **Message batching behavior**
   - What we know: Events can arrive as JSON arrays (batched)
   - What's unclear: Under what conditions batching occurs, typical batch sizes
   - Recommendation: Always handle both single-event (dict) and batched (list) formats. Test from Hetzner with real data.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- Polymarket official docs: docs.polymarket.com/developers/CLOB/websocket/wss-overview — WebSocket overview, channel types
- Polymarket official docs: docs.polymarket.com/developers/CLOB/websocket/market-channel — Market channel subscription format, event types, schemas
- Polymarket official docs: docs.polymarket.com/developers/CLOB/websocket/user-channel — User channel auth format
- Polymarket official docs: docs.polymarket.com/developers/RTDS/RTDS-overview — RTDS alternative
- Polymarket official docs: docs.polymarket.com/quickstart/websocket/WSS-Quickstart — Quickstart with example code
- Polymarket official docs: docs.polymarket.com/quickstart/introduction/rate-limits — Rate limits
- websockets v16.0 docs: websockets.readthedocs.io — Client API, reconnection, memory management, ping/pong
- Existing codebase: docs/POLYMARKET_API_REFERENCE.md — Local API reference (cross-verified)
- Existing codebase: src/config.py — ws_host, websocket_reconnect_delay, trade_buffer_size

### Secondary (MEDIUM confidence)
- Polymarket real-time-data-client (GitHub): github.com/Polymarket/real-time-data-client — TypeScript reference implementation for RTDS
- PolyTrack WebSocket Tutorial: polytrackhq.app/blog/polymarket-websocket-tutorial — Example Python WebSocket code (verified against official docs)
- Polymarket py-clob-client (GitHub): github.com/Polymarket/py-clob-client — Confirmed NO WebSocket support in SDK

### Tertiary (LOW confidence - needs validation from Hetzner)
- 500-instrument limit per connection — documented but exact behavior on exceeding not tested
- `custom_feature_enabled` flag — documented but availability to our account unknown
- Application-level "PING" interval (10s) — documented, needs Hetzner validation
- Event batching behavior — documented as possible, actual batch sizes unknown
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Polymarket CLOB WebSocket API + websockets Python library
- Ecosystem: asyncio.Queue for buffering, asyncpg for DB writes, httpx for Gamma API polling
- Patterns: Async iterator reconnection, producer-consumer queue, connection pooling, application-level heartbeat
- Pitfalls: Missing PING, no trade_id, 500-instrument limit, lost subscriptions, string types, feature flags

**Confidence breakdown:**
- Standard stack: HIGH - websockets already in requirements, well-documented
- Architecture: HIGH - async iterator pattern is well-established, producer-consumer is standard
- Polymarket API format: HIGH - verified against official docs site + existing local API reference
- Pitfalls: HIGH - documented in official docs and community examples
- Resolution tracking: MEDIUM - Gamma API polling verified, WebSocket feature flag uncertain

**Research date:** 2026-02-17
**Valid until:** 2026-03-17 (30 days - WebSocket API stable, no breaking changes expected)
</metadata>

---

*Phase: 03-websocket-trades*
*Research completed: 2026-02-17*
*Ready for planning: yes*
