# Handoff: TimescaleDB Schema + Data Collection Daemon

**Date:** 2026-02-15
**Status:** Planned, not yet implemented
**Priority:** URGENT — every day without data farming is a day of lost training data

---

## Why This Is Urgent

Resolved Polymarket markets only offer 12-hour price candles (GitHub issue #216, confirmed still broken as of Feb 2026). We need minute-level data for ML model training. The only way to get it is to start collecting from active markets NOW. If we start today and need 30 days of data to train, we can't start backtesting until mid-March.

---

## What We're Building

A data collection daemon that runs on the Hetzner server 24/7 and stores market data in TimescaleDB.

**Five collector components:**
1. **Market metadata refresher** — Gamma API `/events` every 5 min → upsert events + markets
2. **Price snapshot collector** — All active market prices every 60s
3. **Orderbook snapshot collector** — CLOB `/books` top-5 levels every 5 min
4. **WebSocket trade listener** — Real-time trades from WebSocket
5. **Resolution tracker** — Detect market closures, record outcomes every 10 min

---

## Architecture Decisions (Already Made)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Database | TimescaleDB (self-hosted on Hetzner via Docker) | Time-series optimized, compression, continuous aggregates, free |
| DB driver | asyncpg directly (not SQLAlchemy ORM) | TimescaleDB features need raw SQL anyway, asyncpg is 3x faster for bulk inserts |
| Data models | Pydantic | Consistent with existing codebase (config.py, arbitrage.py) |
| Daemon architecture | Single process, multiple asyncio tasks | Matches existing patterns (HeartbeatManager, MarketScanner) |
| Orderbook storage | JSONB (top 5 levels packed per row) | Compact, 1 row per snapshot instead of 10+ |
| Compression | After 7 days | ~60-70% space savings |
| Retention | Drop raw after 6 months, keep hourly aggregates forever | Balances storage vs data needs |
| Testing | testcontainers (real TimescaleDB) + respx (HTTP mocking) | Catches real SQL bugs, pytest-asyncio for async |
| Migrations | Numbered SQL files, not Alembic | Schema is 80% TimescaleDB-specific DDL |

---

## File Structure

```
NEW FILES:
  docker-compose.yml                         # TimescaleDB for local dev
  src/db/__init__.py
  src/db/connection.py                       # asyncpg pool management
  src/db/models.py                           # Pydantic models for DB records
  src/db/queries.py                          # Parameterized upserts, bulk inserts, reads
  src/db/migrations/__init__.py
  src/db/migrations/runner.py                # Executes numbered SQL files
  src/db/migrations/001_initial_schema.sql   # Tables, hypertables, indexes
  src/db/migrations/002_continuous_aggregates.sql
  src/db/migrations/003_compression_policies.sql
  src/collector/__init__.py
  src/collector/daemon.py                    # Task supervisor, lifecycle
  src/collector/market_metadata.py           # Gamma API /events → events + markets tables
  src/collector/price_snapshots.py           # All active market prices every 60s
  src/collector/orderbook_snapshots.py       # CLOB /books top-5 levels every 5min
  src/collector/trade_listener.py            # WebSocket real-time trades
  src/collector/resolution_tracker.py        # Detect closures, record outcomes
  tests/conftest.py                          # Shared fixtures, respx mocks
  tests/unit/__init__.py
  tests/unit/test_models.py
  tests/unit/test_queries.py
  tests/integration/__init__.py
  tests/integration/conftest.py              # testcontainers TimescaleDB fixture
  tests/integration/test_schema.py
  tests/integration/test_upserts.py
  tests/integration/test_price_inserts.py
  tests/collector/__init__.py
  tests/collector/test_market_metadata.py
  tests/collector/test_price_snapshots.py
  tests/collector/test_orderbook_snapshots.py
  tests/collector/test_trade_listener.py
  tests/collector/test_resolution_tracker.py
  tests/collector/test_daemon.py

MODIFIED FILES:
  requirements.txt                           # Add asyncpg, testcontainers, respx
  src/config.py                              # Add CollectorConfig, extend DatabaseConfig
  src/main.py                                # Add 'collect' CLI command
  config.example.yaml                        # Add collector + database sections
```

---

## Database Schema

### Dimension Tables (regular Postgres)

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    slug            TEXT,
    title           TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    start_date      TIMESTAMPTZ,
    end_date        TIMESTAMPTZ,
    neg_risk        BOOLEAN DEFAULT FALSE,
    neg_risk_market_id TEXT,
    active          BOOLEAN DEFAULT TRUE,
    closed          BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS markets (
    market_id       TEXT PRIMARY KEY,
    event_id        TEXT REFERENCES events(event_id),
    condition_id    TEXT NOT NULL,
    slug            TEXT,
    question        TEXT NOT NULL,
    outcomes        JSONB,                         -- ["Yes", "No"]
    clob_token_ids  JSONB,                         -- ["token_yes", "token_no"]
    neg_risk        BOOLEAN DEFAULT FALSE,
    tick_size       TEXT DEFAULT '0.01',
    active          BOOLEAN DEFAULT TRUE,
    closed          BOOLEAN DEFAULT FALSE,
    accepting_orders BOOLEAN DEFAULT TRUE,
    volume_total    NUMERIC,
    liquidity       NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_markets_event_id ON markets(event_id);
CREATE INDEX IF NOT EXISTS idx_markets_condition_id ON markets(condition_id);
CREATE INDEX IF NOT EXISTS idx_markets_active ON markets(active) WHERE active = TRUE;

CREATE TABLE IF NOT EXISTS market_resolutions (
    market_id       TEXT PRIMARY KEY REFERENCES markets(market_id),
    resolved_at     TIMESTAMPTZ NOT NULL,
    winning_outcome TEXT,                          -- "Yes" or "No"
    final_prices    JSONB,                         -- {"Yes": 1.00, "No": 0.00}
    resolution_source TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Hypertables (TimescaleDB time-series)

```sql
CREATE TABLE IF NOT EXISTS price_snapshots (
    ts              TIMESTAMPTZ NOT NULL,
    market_id       TEXT NOT NULL,
    yes_price       NUMERIC(10, 6) NOT NULL,
    no_price        NUMERIC(10, 6) NOT NULL,
    volume_24h      NUMERIC,
    liquidity       NUMERIC,
    spread          NUMERIC(10, 6),
    last_trade_price NUMERIC(10, 6)
);
SELECT create_hypertable('price_snapshots', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_price_snapshots_market
    ON price_snapshots(market_id, ts DESC);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    ts              TIMESTAMPTZ NOT NULL,
    market_id       TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    side            TEXT NOT NULL,                  -- 'yes' or 'no'
    bids            JSONB NOT NULL,                -- [{"p": "0.55", "s": "100"}, ...]
    asks            JSONB NOT NULL,
    bid_depth_usd   NUMERIC,
    ask_depth_usd   NUMERIC
);
SELECT create_hypertable('orderbook_snapshots', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_orderbook_market
    ON orderbook_snapshots(market_id, ts DESC);

CREATE TABLE IF NOT EXISTS trades (
    ts              TIMESTAMPTZ NOT NULL,
    market_id       TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    price           NUMERIC(10, 6) NOT NULL,
    size            NUMERIC NOT NULL,
    side            TEXT,
    trade_id        TEXT
);
SELECT create_hypertable('trades', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_trades_token ON trades(token_id, ts DESC);
```

### Strategy + Operational Tables

```sql
CREATE TABLE IF NOT EXISTS market_relationships (
    id              SERIAL PRIMARY KEY,
    market_id_a     TEXT NOT NULL REFERENCES markets(market_id),
    market_id_b     TEXT NOT NULL REFERENCES markets(market_id),
    relationship_type TEXT NOT NULL,
    confidence      NUMERIC(5, 4),
    metadata        JSONB,
    detected_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(market_id_a, market_id_b, relationship_type)
);

CREATE TABLE IF NOT EXISTS bot_trades (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ DEFAULT NOW(),
    market_id       TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    side            TEXT NOT NULL,
    price           NUMERIC(10, 6) NOT NULL,
    size            NUMERIC NOT NULL,
    order_id        TEXT,
    strategy        TEXT,
    paper_trade     BOOLEAN DEFAULT TRUE,
    pnl             NUMERIC
);

CREATE TABLE IF NOT EXISTS bot_positions (
    id              SERIAL PRIMARY KEY,
    market_id       TEXT NOT NULL,
    token_id        TEXT NOT NULL,
    side            TEXT NOT NULL,
    size            NUMERIC NOT NULL,
    avg_entry_price NUMERIC(10, 6) NOT NULL,
    current_price   NUMERIC(10, 6),
    strategy        TEXT,
    opened_at       TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    status          TEXT DEFAULT 'open',
    pnl             NUMERIC DEFAULT 0,
    UNIQUE(market_id, token_id, side, strategy)
);

CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    applied_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Continuous Aggregate (002_continuous_aggregates.sql)

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS price_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    market_id,
    first(yes_price, ts) AS open,
    max(yes_price) AS high,
    min(yes_price) AS low,
    last(yes_price, ts) AS close,
    avg(yes_price) AS vwap,
    last(volume_24h, ts) AS volume_24h,
    count(*) AS sample_count
FROM price_snapshots
GROUP BY bucket, market_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('price_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
```

### Compression & Retention (003_compression_policies.sql)

```sql
-- Compress after 7 days
ALTER TABLE price_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'market_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('price_snapshots', INTERVAL '7 days', if_not_exists => TRUE);

ALTER TABLE orderbook_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'market_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('orderbook_snapshots', INTERVAL '7 days', if_not_exists => TRUE);

ALTER TABLE trades SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'market_id',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('trades', INTERVAL '7 days', if_not_exists => TRUE);

-- Drop raw data after 6 months (hourly aggregates preserved)
SELECT add_retention_policy('price_snapshots', INTERVAL '6 months', if_not_exists => TRUE);
SELECT add_retention_policy('orderbook_snapshots', INTERVAL '6 months', if_not_exists => TRUE);
SELECT add_retention_policy('trades', INTERVAL '6 months', if_not_exists => TRUE);
```

---

## Implementation Order (TDD)

### Phase 0: Setup (no tests needed)

1. Create `docker-compose.yml`:
   ```yaml
   services:
     timescaledb:
       image: timescale/timescaledb:latest-pg16
       ports:
         - "5432:5432"
       environment:
         POSTGRES_USER: polymarket
         POSTGRES_PASSWORD: polymarket
         POSTGRES_DB: polymarket
       volumes:
         - timescale_data:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U polymarket"]
         interval: 5s
         timeout: 5s
         retries: 5
   volumes:
     timescale_data:
   ```

2. Update `requirements.txt` — add:
   ```
   asyncpg>=0.29.0
   testcontainers[postgres]>=4.0.0
   respx>=0.21.0
   pytest-timeout>=2.2.0
   ```

3. Update `src/config.py` — extend `DatabaseConfig`, add `CollectorConfig`:
   ```python
   class DatabaseConfig(BaseModel):
       url: str = "postgresql://polymarket:polymarket@localhost:5432/polymarket"
       pool_size: int = 5

       @property
       def asyncpg_dsn(self) -> str:
           return self.url.replace("postgresql+asyncpg://", "postgresql://")

   class CollectorConfig(BaseModel):
       market_refresh_interval: int = 300     # 5 min
       price_snapshot_interval: int = 60      # 60s
       orderbook_snapshot_interval: int = 300 # 5 min
       resolution_check_interval: int = 600   # 10 min
       orderbook_depth: int = 5
       enable_websocket_trades: bool = True
   ```

4. Create test fixtures (`tests/conftest.py`, `tests/integration/conftest.py`)

5. Windows asyncio fix in tests and main.py:
   ```python
   import sys
   if sys.platform == "win32":
       asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
   ```

### Phase 1: Database Layer — tests/impl for `src/db/`

| Step | Test First | Then Implement |
|------|-----------|---------------|
| 1.1 Connection pool | `test_connection.py`: pool creates, closes, context manager works | `connection.py`: `create_pool()`, `close_pool()` |
| 1.2 Pydantic models | `test_models.py`: validate from Gamma API format, parse stringified JSON, handle edge cases | `models.py`: `EventRecord`, `MarketRecord`, `PriceSnapshot`, `OrderbookSnapshot`, `TradeRecord`, `MarketResolution` |
| 1.3 Schema migration | `test_schema.py` (integration): tables exist, hypertables confirmed, idempotent, version tracked | `runner.py` + SQL files |
| 1.4 Query functions | `test_upserts.py`, `test_price_inserts.py` (integration): upsert behavior, bulk insert, latest price query | `queries.py`: all CRUD functions |

### Phase 2: Collectors — tests/impl for `src/collector/`

| Step | Test First | Then Implement |
|------|-----------|---------------|
| 2.1 Market metadata | Mock Gamma `/events`, verify pagination + upserts | `market_metadata.py` |
| 2.2 Price snapshots | Mock Gamma API, verify batch insert | `price_snapshots.py` |
| 2.3 Orderbook snapshots | Mock CLOB `get_order_books()`, verify top-5 JSONB | `orderbook_snapshots.py` |
| 2.4 WebSocket trades | Mock WebSocket, verify subscribe/parse/reconnect/buffer | `trade_listener.py` |
| 2.5 Resolution tracker | Mock Gamma with `closed=True`, verify resolution inference | `resolution_tracker.py` |

### Phase 3: Daemon + CLI

| Step | Test First | Then Implement |
|------|-----------|---------------|
| 3.1 Daemon | Test task supervision, graceful shutdown, crash recovery | `daemon.py` |
| 3.2 CLI | Manual test: `python -m src.main collect --once` | Modify `src/main.py` |

---

## Key Code Patterns to Reuse

| Pattern | Source | Use In |
|---------|--------|--------|
| Stringified JSON array parsing | `src/scanner/arbitrage.py:201-219` (`_parse_stringified_json_array`) | `src/db/models.py` Pydantic validators |
| Rate-limited API calls | `src/utils/retry.py` (`gamma_limiter`, `clob_read_limiter`) | Every collector's API call |
| Sync → async wrapping | `src/utils/heartbeat.py:147` (`asyncio.get_running_loop().run_in_executor`) | Orderbook collector (py-clob-client is sync) |
| Background task loop | `src/utils/heartbeat.py:165-192` (`_heartbeat_loop`) | All collector `run_loop()` methods |
| Pagination | `src/utils/client.py:135-157` (`get_all_active_markets`) | Market metadata collector |
| Config pattern | `src/config.py` (Pydantic BaseModel) | `CollectorConfig`, `DatabaseConfig` extension |

---

## Config Changes (`config.example.yaml` additions)

```yaml
database:
  url: "postgresql://polymarket:polymarket@localhost:5432/polymarket"
  pool_size: 5

collector:
  market_refresh_interval: 300     # Refresh market metadata every 5 min
  price_snapshot_interval: 60      # Snapshot prices every 60s
  orderbook_snapshot_interval: 300  # Snapshot orderbooks every 5 min
  resolution_check_interval: 600   # Check for resolutions every 10 min
  orderbook_depth: 5               # Top N orderbook levels to store
  enable_websocket_trades: true    # Enable real-time trade collection
```

---

## Verification Checklist

```
[ ] docker compose up -d — TimescaleDB starts, health check passes
[ ] pytest tests/unit/ -v — all unit tests pass (no Docker needed)
[ ] pytest tests/integration/ -v — schema, inserts, aggregates verified
[ ] pytest tests/collector/ -v — all collectors pass with mocked APIs
[ ] python -m src.main collect --once — single cycle populates DB
[ ] python -m src.main collect — daemon runs, logs show collection stats
[ ] psql: SELECT count(*) FROM price_snapshots — grows each minute
[ ] psql: SELECT * FROM price_hourly LIMIT 5 — hourly aggregates populated
```

---

## Gotchas to Watch For

1. **py-clob-client is synchronous** — wrap all CLOB calls with `run_in_executor()`, never call directly in async context
2. **asyncpg on Windows** — requires `WindowsSelectorEventLoopPolicy`, won't work with default `ProactorEventLoop`
3. **Gamma API returns stringified JSON** — `outcomePrices` and `clobTokenIds` must be parsed with `json.loads()`, not split by comma
4. **No explicit resolution field** — infer winner from final prices (>0.95 = winner)
5. **Rate limits are per 10-second window** — our limiters use 70% of documented limits as safety margin
6. **WebSocket has no subscription limit** (removed May 2025) but subscribing to 1000+ tokens on one connection may be impractical — consider 2-3 connections

---

## Estimated Data Volumes

| Data Type | Frequency | Raw/Month | Compressed/Month |
|-----------|-----------|-----------|-----------------|
| Price snapshots | 60s, ~1000 markets | ~8-9 GB | ~2-3 GB |
| Orderbook snapshots | 5 min, ~1000 markets | ~4-5 GB | ~1-2 GB |
| WebSocket trades | Real-time | ~200 MB | ~60 MB |
| Market metadata | 5 min | ~700 MB | ~200 MB |
| **Total** | | **~14 GB** | **~4-5 GB** |

Hetzner CPX31 has 160 GB disk → ~3+ years of compressed data before running out.
