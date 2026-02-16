# Phase 1: Setup + Database Layer - Research

**Researched:** 2026-02-16
**Domain:** TimescaleDB + asyncpg + testcontainers for Python async time-series pipeline
**Confidence:** HIGH

<research_summary>
## Summary

Researched the full stack for building an async Python database layer with TimescaleDB for time-series market data. The standard approach uses asyncpg's built-in connection pool (no external pooler needed), raw SQL migrations (either pogo-migrate or a lightweight custom runner), and testcontainers-python with the TimescaleDB Docker image for TDD.

Key finding: asyncpg's `copy_records_to_table()` is the correct bulk insert method — 10-100x faster than `executemany()` for the 60-second price snapshots across 8,000+ markets. TimescaleDB's compression (up to 98% reduction), continuous aggregates (incremental materialized views), and retention policies handle all the data lifecycle management that would otherwise require complex application code.

The existing codebase already has: async-first patterns, Pydantic v2 config models (including a `DatabaseConfig` stub with SQLite URL), Click CLI, and a `data/` directory convention. The database layer should extend these patterns, replacing the SQLite URL with a PostgreSQL DSN and adding pool management as a singleton like the existing config system.

**Primary recommendation:** Use asyncpg pool directly (min_size=2, max_size=10 for dev), pogo-migrate or a simple custom migration runner for raw SQL files, TimescaleDB hypertables with `compress_segmentby` on market identifiers, and testcontainers-python with `timescale/timescaledb:latest-pg17` image.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | >=0.29.0 | Async PostgreSQL driver + pool | Fastest Python PG driver (1M rows/s benchmarked). Binary protocol, built-in pool, COPY support. Already async-native. |
| TimescaleDB | 2.x (latest-pg17 image) | Time-series extension for PostgreSQL | Hypertables, compression (up to 98%), continuous aggregates, retention policies. All via SQL — no application code needed for data lifecycle. |
| testcontainers-python | >=4.10.0 | Docker containers for integration tests | PostgresContainer works with TimescaleDB image. Pytest fixtures for isolated DB tests. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pogo-migrate | >=0.0.22 | SQL migration runner for asyncpg | Purpose-built for asyncpg. Raw SQL + Python migrations. If too immature, fall back to custom runner. |
| docker (Python SDK) | >=7.0.0 | Docker interaction for testcontainers | Required by testcontainers-python. Already needed. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| asyncpg | psycopg3 (async mode) | psycopg3 is newer, has async support, but asyncpg is still faster for binary COPY and has more mature pool. Stick with asyncpg per project decision. |
| pogo-migrate | yoyo-migrations | yoyo is more mature but synchronous — no native asyncpg support. Would need sync psycopg2 just for migrations. |
| pogo-migrate | Custom SQL runner | ~50 lines of code, full control, no extra dependency. Good fallback if pogo-migrate is too immature. |
| testcontainers-python | Docker Compose for tests | Testcontainers is per-test isolation, auto-cleanup. Docker Compose requires manual lifecycle. Testcontainers is standard for TDD. |

**Installation:**
```bash
pip install asyncpg testcontainers[postgres] pogo-migrate
# TimescaleDB runs in Docker, not installed as Python package
```

**Docker image:**
```bash
docker pull timescale/timescaledb:latest-pg17
# Pin to specific version for reproducibility in CI
# e.g., timescale/timescaledb:2.17.2-pg17
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
src/
├── config.py                    # EXISTING - extend DatabaseConfig
├── db/
│   ├── __init__.py
│   ├── pool.py                  # Connection pool singleton (like config.get_config())
│   ├── migrations/
│   │   ├── runner.py            # Migration runner (apply numbered SQL files)
│   │   ├── 001_extensions.sql   # CREATE EXTENSION IF NOT EXISTS timescaledb;
│   │   ├── 002_markets.sql      # Market metadata table
│   │   ├── 003_price_snapshots.sql  # Hypertable for price data
│   │   ├── 004_orderbook_snapshots.sql
│   │   ├── 005_trades.sql       # WebSocket trade events
│   │   ├── 006_resolutions.sql  # Market resolution tracking
│   │   ├── 007_continuous_aggs.sql  # Materialized views
│   │   └── 008_compression.sql  # Compression + retention policies
│   ├── models.py                # Pydantic models for DB records
│   └── queries/
│       ├── markets.py           # Market metadata CRUD
│       ├── prices.py            # Price snapshot inserts + queries
│       ├── orderbooks.py        # Orderbook snapshot inserts + queries
│       ├── trades.py            # Trade event inserts + queries
│       └── resolutions.py       # Resolution tracking
├── ...
tests/
├── conftest.py                  # TimescaleDB container fixture, pool fixture
├── test_db/
│   ├── test_pool.py             # Pool lifecycle tests
│   ├── test_migrations.py       # Migration runner tests
│   ├── test_models.py           # Pydantic model validation
│   ├── test_markets.py          # Market query tests
│   ├── test_prices.py           # Price snapshot tests
│   └── test_schema.py           # Schema verification
```

### Pattern 1: Pool Singleton (matches existing config pattern)
**What:** Single connection pool shared across the application, initialized once
**When to use:** All database access throughout the daemon
**Example:**
```python
# src/db/pool.py
import asyncpg
from src.config import get_config

_pool: asyncpg.Pool | None = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None or _pool._closed:
        cfg = get_config().database
        _pool = await asyncpg.create_pool(
            dsn=cfg.url,
            min_size=cfg.min_pool_size,  # 2 for dev, 5 for prod
            max_size=cfg.max_pool_size,  # 10 for dev, 20 for prod
            max_inactive_connection_lifetime=300.0,
            command_timeout=60,
        )
    return _pool

async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

### Pattern 2: Bulk Insert via COPY (not executemany)
**What:** Use asyncpg's binary COPY protocol for bulk inserts
**When to use:** Price snapshots (8000+ rows every 60s), orderbook snapshots
**Example:**
```python
# Source: asyncpg official docs
async def insert_price_snapshots(pool: asyncpg.Pool, snapshots: list[tuple]):
    """Insert price snapshots using binary COPY.

    Each tuple: (timestamp, token_id, price, volume_24h)
    """
    await pool.copy_records_to_table(
        'price_snapshots',
        records=snapshots,
        columns=['ts', 'token_id', 'price', 'volume_24h'],
    )
```

### Pattern 3: Query Functions (Repository pattern, raw SQL)
**What:** Thin query functions that take a pool and return Pydantic models
**When to use:** All database reads
**Example:**
```python
# src/db/queries/prices.py
async def get_latest_prices(
    pool: asyncpg.Pool,
    token_ids: list[str],
    limit: int = 1,
) -> list[PriceSnapshot]:
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (token_id) ts, token_id, price, volume_24h
        FROM price_snapshots
        WHERE token_id = ANY($1::text[])
        ORDER BY token_id, ts DESC
        LIMIT $2
        """,
        token_ids, limit,
    )
    return [PriceSnapshot(**dict(r)) for r in rows]
```

### Pattern 4: Simple SQL Migration Runner
**What:** Number-prefixed .sql files applied in order, tracked in a `schema_migrations` table
**When to use:** Schema changes during development and deployment
**Example:**
```python
# src/db/migrations/runner.py
async def run_migrations(pool: asyncpg.Pool, migrations_dir: Path):
    """Apply pending SQL migrations in order."""
    async with pool.acquire() as conn:
        # Create tracking table if not exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INT PRIMARY KEY,
                filename TEXT NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        applied = {r['version'] for r in await conn.fetch(
            "SELECT version FROM schema_migrations"
        )}
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            version = int(sql_file.name.split("_")[0])
            if version not in applied:
                async with conn.transaction():
                    await conn.execute(sql_file.read_text())
                    await conn.execute(
                        "INSERT INTO schema_migrations (version, filename) VALUES ($1, $2)",
                        version, sql_file.name,
                    )
```

### Pattern 5: Testcontainers Fixture with TimescaleDB
**What:** Pytest fixture that spins up TimescaleDB in Docker for each test session
**When to use:** All database integration tests
**Example:**
```python
# tests/conftest.py
import pytest
import asyncpg
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def timescaledb_container():
    """Spin up TimescaleDB container for test session."""
    container = PostgresContainer(
        image="timescale/timescaledb:latest-pg17",
        username="test",
        password="test",
        dbname="testdb",
    )
    container.start()
    yield container
    container.stop()

@pytest.fixture
async def db_pool(timescaledb_container):
    """Create asyncpg pool connected to test TimescaleDB."""
    container = timescaledb_container
    # testcontainers exposes host:port
    pool = await asyncpg.create_pool(
        host=container.get_container_host_ip(),
        port=container.get_exposed_port(5432),
        user="test",
        password="test",
        database="testdb",
        min_size=1,
        max_size=5,
    )
    # Run migrations
    await run_migrations(pool, Path("src/db/migrations"))
    yield pool
    await pool.close()
```

### Anti-Patterns to Avoid
- **Using executemany() for bulk inserts:** COPY is 10-100x faster. asyncpg's `copy_records_to_table` handles the binary protocol.
- **Caching prepared statements across pool.release():** Prepared statements become invalid when connection returns to pool. Use pool-level methods (`pool.fetch`, `pool.execute`) which handle this internally.
- **Using an external connection pooler (pgbouncer):** asyncpg's built-in pool is sufficient and avoids prepared statement incompatibility issues. Only add pgbouncer if you need 100+ concurrent connections.
- **Creating connections per request:** Always use the pool. Connection creation is expensive (~50ms).
- **Storing JSONB without indexes:** If querying JSONB fields (e.g., orderbook data), add GIN indexes on frequently accessed paths.
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time-series partitioning | Custom date-based table sharding | TimescaleDB hypertables | Automatic chunk management, transparent queries, partition pruning |
| Data compression | Application-level compression (zlib on blobs) | TimescaleDB native compression | Up to 98% reduction, query-time decompression transparent, segmentby for fast filtered access |
| Downsampled aggregates | Cron jobs running GROUP BY queries | TimescaleDB continuous aggregates | Incremental refresh, real-time mode merges cached + fresh data, hierarchical rollups |
| Old data cleanup | Custom DELETE jobs with WHERE clauses | `add_retention_policy()` | Drops entire chunks efficiently (not row-by-row DELETE), policy-based scheduling |
| Connection pooling | Custom connection management / external pgbouncer | `asyncpg.create_pool()` | Handles connection lifecycle, prepared statement caching, health checks, min/max sizing |
| Bulk inserts | Building multi-row INSERT VALUES strings | `pool.copy_records_to_table()` | Binary COPY protocol, handles type encoding, 10-100x faster for large batches |
| Migration tracking | Custom version tracking in config files | Migration runner with `schema_migrations` table | Atomic apply, rollback support, version tracking per-database |

**Key insight:** TimescaleDB eliminates 80% of the data lifecycle code that time-series applications typically hand-roll. Compression, aggregation, retention, and partitioning are all declarative SQL policies — not application code. The asyncpg pool handles connection management. The only application code needed is: migrations, insert functions, and query functions.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Prepared Statement Invalidation After Pool Release
**What goes wrong:** Caching a PreparedStatement object, releasing the connection, then trying to use the statement on a different connection — raises InterfaceError.
**Why it happens:** asyncpg prepared statements are bound to a specific connection. Pool.release() returns the connection, and Pool.acquire() may give you a different one.
**How to avoid:** Use pool-level convenience methods (`pool.fetch()`, `pool.execute()`, `pool.copy_records_to_table()`) which handle statement lifecycle internally. Never store PreparedStatement objects beyond a single `async with pool.acquire() as conn:` block.
**Warning signs:** Intermittent InterfaceError about "released connection" or "invalid prepared statement."

### Pitfall 2: Wrong chunk_time_interval for Data Patterns
**What goes wrong:** Default chunk interval (7 days) is too large or too small for your insert/query pattern, causing either too many chunks (slow planning) or chunks too large to compress efficiently.
**Why it happens:** TimescaleDB's default 7-day chunks assume moderate write volumes. With 8000+ markets every 60 seconds, chunks fill faster.
**How to avoid:** For 60-second price snapshots at 8000 markets: ~11.5M rows/day. Use `chunk_time_interval => INTERVAL '1 day'` for price_snapshots. For orderbook (5-min, fewer markets): `INTERVAL '7 days'` is fine.
**Warning signs:** `SELECT count(*) FROM timescaledb_information.chunks` shows unexpected chunk counts. Compression jobs taking too long.

### Pitfall 3: Forgetting to CREATE EXTENSION timescaledb
**What goes wrong:** `create_hypertable()` fails with "function does not exist."
**Why it happens:** TimescaleDB extension must be explicitly enabled per database, even if the Docker image includes it.
**How to avoid:** First migration file (001_extensions.sql) must be `CREATE EXTENSION IF NOT EXISTS timescaledb;`. Run this before any hypertable DDL.
**Warning signs:** Any "function create_hypertable does not exist" error.

### Pitfall 4: Missing compress_segmentby on High-Cardinality Columns
**What goes wrong:** Compression ratio is poor, and filtered queries on compressed data are slow.
**Why it happens:** Without `segmentby`, TimescaleDB compresses the entire chunk as one segment. Queries filtering by token_id must decompress everything.
**How to avoid:** Always set `compress_segmentby` to columns you filter on. For price_snapshots: `segmentby = 'token_id'`. For orderbooks: `segmentby = 'token_id'`.
**Warning signs:** Compressed chunk queries slower than raw data queries. Poor compression ratios (<80%).

### Pitfall 5: asyncpg Pool Sizing vs PostgreSQL max_connections
**What goes wrong:** Pool creation fails or connections are refused.
**Why it happens:** PostgreSQL default `max_connections = 100`. If pool `max_size` exceeds this (or multiple pools compete), connections are refused.
**How to avoid:** Set pool max_size to 10-20 (well under the default 100). For Docker dev: explicitly set `max_connections=200` in PostgreSQL config if needed. Monitor with `SELECT count(*) FROM pg_stat_activity;`.
**Warning signs:** `asyncpg.TooManyConnectionsError` or "sorry, too many clients already."

### Pitfall 6: Windows asyncio Event Loop Policy
**What goes wrong:** asyncpg operations hang or fail on Windows.
**Why it happens:** Windows default ProactorEventLoop doesn't support some asyncio features asyncpg needs.
**How to avoid:** Set `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` at program start. Already documented as a project constraint.
**Warning signs:** Hangs during `create_pool()` or first query on Windows.

### Pitfall 7: IN Clause with Array Parameters
**What goes wrong:** `WHERE token_id IN $1` raises syntax error.
**Why it happens:** PostgreSQL doesn't accept parameterized IN lists. asyncpg FAQ explicitly warns about this.
**How to avoid:** Use `WHERE token_id = ANY($1::text[])` instead. Pass Python list directly — asyncpg handles array encoding.
**Warning signs:** `PostgresSyntaxError` on queries with IN clauses.

### Pitfall 8: Cursors Outside Transactions
**What goes wrong:** `Connection.cursor()` raises InterfaceError.
**Why it happens:** PostgreSQL requires non-scrollable cursors to be inside a transaction.
**How to avoid:** Always wrap cursor usage in `async with conn.transaction():`. Or use `DECLARE ... CURSOR WITH HOLD` for transaction-independent cursors.
**Warning signs:** InterfaceError about cursor operations outside transaction block.
</common_pitfalls>

<code_examples>
## Code Examples

Verified patterns from official sources:

### TimescaleDB Hypertable Creation
```sql
-- Source: Timescale official docs (Context7)
-- Price snapshots hypertable
CREATE TABLE price_snapshots (
    ts          TIMESTAMPTZ NOT NULL,
    token_id    TEXT        NOT NULL,
    price       DOUBLE PRECISION NOT NULL,
    volume_24h  DOUBLE PRECISION
);

SELECT create_hypertable('price_snapshots', by_range('ts', INTERVAL '1 day'));

-- Create index for common query pattern
CREATE INDEX idx_price_snapshots_token_time
    ON price_snapshots (token_id, ts DESC);
```

### TimescaleDB Compression Setup
```sql
-- Source: Timescale official docs (Context7)
-- Enable compression with segmentby for filtered queries
ALTER TABLE price_snapshots SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'token_id',
    timescaledb.compress_orderby = 'ts DESC'
);

-- Auto-compress chunks older than 7 days
SELECT add_compression_policy('price_snapshots', INTERVAL '7 days');
```

### TimescaleDB Continuous Aggregate
```sql
-- Source: Timescale official docs (Context7)
-- 1-hour OHLCV candles from 60-second snapshots
CREATE MATERIALIZED VIEW price_candles_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', ts) AS bucket,
    token_id,
    first(price, ts)  AS open,
    max(price)         AS high,
    min(price)         AS low,
    last(price, ts)    AS close,
    avg(volume_24h)    AS avg_volume
FROM price_snapshots
GROUP BY bucket, token_id;

-- Refresh policy: update hourly, look back 3 hours for late data
SELECT add_continuous_aggregate_policy('price_candles_1h',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
```

### TimescaleDB Retention Policy
```sql
-- Source: Timescale official docs (Context7)
-- Drop raw price data older than 90 days (keep aggregates forever)
SELECT add_retention_policy('price_snapshots', drop_after => INTERVAL '90 days');
```

### asyncpg Pool Initialization
```python
# Source: asyncpg official docs (Context7)
import asyncpg

async def init_pool():
    pool = await asyncpg.create_pool(
        dsn="postgresql://user:pass@localhost:5432/polymarket",
        min_size=2,
        max_size=10,
        max_queries=50000,
        max_inactive_connection_lifetime=300.0,
        command_timeout=60,
    )
    return pool
```

### asyncpg Bulk Insert via COPY
```python
# Source: asyncpg official docs (Context7)
async def bulk_insert_prices(pool, snapshots):
    """Insert price snapshots using binary COPY.

    snapshots: list of tuples (ts, token_id, price, volume_24h)
    """
    await pool.copy_records_to_table(
        'price_snapshots',
        records=snapshots,
        columns=['ts', 'token_id', 'price', 'volume_24h'],
    )
```

### asyncpg Query with Array Parameter
```python
# Source: asyncpg FAQ (verified)
async def get_prices_for_tokens(pool, token_ids: list[str]):
    """Use ANY($1::text[]) instead of IN for parameterized lists."""
    return await pool.fetch(
        """
        SELECT DISTINCT ON (token_id) ts, token_id, price
        FROM price_snapshots
        WHERE token_id = ANY($1::text[])
        ORDER BY token_id, ts DESC
        """,
        token_ids,
    )
```

### Testcontainers with TimescaleDB
```python
# Source: testcontainers-python docs (Context7) + TimescaleDB image pattern
import pytest
import asyncpg
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def timescaledb():
    # Use TimescaleDB image as drop-in for PostgresContainer
    with PostgresContainer("timescale/timescaledb:latest-pg17") as container:
        yield container

@pytest.fixture
async def pool(timescaledb):
    pool = await asyncpg.create_pool(
        host=timescaledb.get_container_host_ip(),
        port=int(timescaledb.get_exposed_port(5432)),
        user=timescaledb.username,
        password=timescaledb.password,
        database=timescaledb.dbname,
        min_size=1,
        max_size=3,
    )
    # Enable TimescaleDB + run migrations
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    yield pool
    await pool.close()
```

### Docker Compose for Development
```yaml
# docker-compose.yml
services:
  timescaledb:
    image: timescale/timescaledb:latest-pg17
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: polymarket
      POSTGRES_PASSWORD: polymarket_dev
      POSTGRES_DB: polymarket
      TIMESCALEDB_TELEMETRY: "off"
    volumes:
      - timescaledb_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U polymarket"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  timescaledb_data:
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `create_hypertable('table', 'time')` | `create_hypertable('table', by_range('time', INTERVAL))` | TimescaleDB 2.13+ | New `by_range()` syntax is preferred. Old syntax still works. |
| PostgreSQL 15/16 base images | PostgreSQL 17 base images | 2024-2025 | `timescale/timescaledb:latest-pg17` is current. PG17 has incremental backup and performance improvements. |
| Manual VACUUM on compressed data | Automatic compression background workers | TimescaleDB 2.x | Compression policies handle everything. No manual VACUUM needed for compressed chunks. |
| `WITH (timescaledb.continuous, timescaledb.materialized_only = false)` | Real-time mode is default for continuous aggregates | TimescaleDB 2.7+ | Real-time aggregates (merging materialized + fresh data) are default. No extra config needed. |
| Separate TimescaleDB Toolkit extension | Built-in time_bucket, first(), last() | Ongoing | Many Toolkit functions are now in core TimescaleDB. Toolkit still useful for percentile_agg, heartbeat_agg. |
| testcontainers 3.x | testcontainers 4.x | 2024 | Major API changes. PostgresContainer constructor params changed (username/password/dbname instead of POSTGRES_* env vars). |

**New tools/patterns to consider:**
- **TimescaleDB columnar compression:** Newer versions offer even more aggressive columnar storage for analytics workloads
- **Hierarchical continuous aggregates:** Stack aggregates (1min -> 1hour -> 1day) since TimescaleDB 2.9
- **asyncpg Pool `setup` callback:** Auto-configure each connection (e.g., set timezone, enable extensions) when acquired from pool

**Deprecated/outdated:**
- **aiopg:** Superseded by asyncpg for async PostgreSQL in Python. asyncpg is faster and better maintained.
- **SQLAlchemy for raw time-series:** Project explicitly chose asyncpg without ORM. No benefit from SQLAlchemy for bulk COPY inserts.
- **pgbouncer with asyncpg:** Causes prepared statement issues. asyncpg's built-in pool is sufficient for our scale.
</sota_updates>

<open_questions>
## Open Questions

1. **pogo-migrate maturity**
   - What we know: pogo-migrate is purpose-built for asyncpg with raw SQL support
   - What's unclear: How mature is it? Only at version 0.0.22. Few GitHub stars.
   - Recommendation: Build a simple custom migration runner (~50 lines). It's so simple there's no benefit to a dependency. Can always switch later.

2. **Testcontainers TimescaleDB image compatibility**
   - What we know: PostgresContainer accepts custom images. TimescaleDB image is PostgreSQL-compatible.
   - What's unclear: Whether `get_connection_url()` works correctly with TimescaleDB image, or if we need to manually construct the DSN.
   - Recommendation: Test during implementation. Fallback: use `get_container_host_ip()` + `get_exposed_port()` to construct DSN manually (shown in code examples above).

3. **Optimal chunk_time_interval for our workload**
   - What we know: 8000 markets x 60s = ~11.5M rows/day for price_snapshots. TimescaleDB docs recommend "each chunk should be 25% of available RAM" for insert-heavy workloads.
   - What's unclear: Exact row size and resulting chunk size at 1-day interval. May need tuning after observing real data.
   - Recommendation: Start with `INTERVAL '1 day'` for price_snapshots, `INTERVAL '7 days'` for orderbooks and trades. Monitor chunk sizes after first week of data.

4. **asyncpg on Windows + testcontainers**
   - What we know: asyncpg needs WindowsSelectorEventLoopPolicy on Windows. Testcontainers needs Docker Desktop on Windows.
   - What's unclear: Whether pytest-asyncio properly sets the event loop policy when combined with testcontainers fixtures.
   - Recommendation: Set the event loop policy in conftest.py at module level. Test early in implementation.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- /timescale/docs (Context7) — hypertable creation, compression policies, continuous aggregates, retention policies, ALTER TABLE compression, add_retention_policy
- /websites/magicstack_github_io_asyncpg_current (Context7) — create_pool API, copy_records_to_table, cursors, prepared statements
- /testcontainers/testcontainers-python (Context7) — PostgresContainer setup, custom images, pytest fixtures
- asyncpg FAQ (https://magicstack.github.io/asyncpg/current/faq.html) — pgbouncer issues, array parameter syntax, cursor transactions

### Secondary (MEDIUM confidence)
- [TimescaleDB Docker Hub](https://hub.docker.com/r/timescale/timescaledb) — image tags, latest-pg17
- [Timescale official docs on compression](https://www.tigerdata.com/docs/use-timescale/latest/continuous-aggregates/about-continuous-aggregates) — hierarchical aggregates, real-time mode
- [pogo-migrate PyPI](https://pypi.org/project/pogo-migrate/0.0.22/) — asyncpg migration tool
- [asyncpg GitHub issues](https://github.com/MagicStack/asyncpg/issues/51) — prepared statement pool behavior

### Tertiary (LOW confidence - needs validation)
- [Testcontainers Timescale Module page](https://testcontainers.com/modules/timescale/) — Java-focused, Python pattern inferred from PostgresContainer docs
- pogo-migrate maturity assessment — based on version number and limited community, not on direct evaluation
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: TimescaleDB (hypertables, compression, continuous aggregates, retention) + asyncpg (pool, COPY, queries)
- Ecosystem: testcontainers-python, pogo-migrate, Docker Compose
- Patterns: Pool singleton, bulk insert via COPY, raw SQL query functions, simple migration runner, testcontainers fixtures
- Pitfalls: Prepared statement invalidation, chunk sizing, missing extension, segmentby, pool sizing, Windows event loop, IN clause syntax, cursors outside transactions

**Confidence breakdown:**
- Standard stack: HIGH — asyncpg and TimescaleDB are well-documented, verified via Context7
- Architecture: HIGH — patterns derived from official docs and existing codebase conventions
- Pitfalls: HIGH — from official FAQ, GitHub issues, and Context7 documentation
- Code examples: HIGH — from Context7 official sources, verified against documentation

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (30 days — asyncpg and TimescaleDB ecosystems are stable)
</metadata>

---

*Phase: 01-setup-database-layer*
*Research completed: 2026-02-16*
*Ready for planning: yes*
