---
phase: 01-setup-database-layer
plan: 03
subsystem: database
tags: [timescaledb, asyncpg, pydantic, hypertables, continuous-aggregates, compression]

# Dependency graph
requires:
  - phase: 01-01
    provides: docker-compose TimescaleDB, asyncpg pool, test infrastructure
  - phase: 01-02
    provides: SQL migration runner with schema_migrations tracking
provides:
  - 5 core tables (markets, price_snapshots, orderbook_snapshots, trades, resolutions)
  - 3 hypertables with chunking (price_snapshots 1d, orderbook_snapshots 7d, trades 1d)
  - 2 continuous aggregates (price_candles_1h, trade_volume_1h)
  - Compression policies on all hypertables (segmentby=token_id, 7-day delay)
  - Retention policies on price_snapshots and trades (90 days)
  - Pydantic DB record models for all 5 tables
  - record_to_model() helper for asyncpg Record conversion
affects: [01-04, 01-05, 01-06, phase-2]

# Tech tracking
tech-stack:
  added: [pydantic]
  patterns: [hypertable-per-timeseries, continuous-aggregate-for-rollups, segmentby-compression]

key-files:
  created:
    - src/db/migrations/002_markets.sql
    - src/db/migrations/003_price_snapshots.sql
    - src/db/migrations/004_orderbook_snapshots.sql
    - src/db/migrations/005_trades.sql
    - src/db/migrations/006_resolutions.sql
    - src/db/migrations/007_continuous_aggs.sql
    - src/db/migrations/008_compression.sql
    - src/db/models.py
    - tests/db/test_schema.py
  modified:
    - tests/conftest.py

key-decisions:
  - "Unique index on trades.trade_id includes ts column (TimescaleDB hypertable partitioning requirement)"
  - "Continuous aggregates created before compression (007 before 008) for compatibility"
  - "No retention on orderbook_snapshots (lower volume, keep longer)"

patterns-established:
  - "Hypertable pattern: CREATE TABLE → create_hypertable(by_range) → index(token_id, ts DESC)"
  - "Compression pattern: segmentby=token_id, orderby=ts DESC, compress after 7 days"
  - "Pydantic models as DB record types with record_to_model() converter"

issues-created: []

# Metrics
duration: 6min
completed: 2026-02-16
---

# Phase 1 Plan 3: Database Schema + Models Summary

**7 SQL migrations (002-008) creating 5 tables with 3 hypertables, 2 continuous aggregates, compression/retention policies, plus Pydantic record models and schema verification tests**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-16T16:16:09Z
- **Completed:** 2026-02-16T16:22:22Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments
- Created complete TimescaleDB schema: markets, price_snapshots, orderbook_snapshots, trades, resolutions
- 3 hypertables with appropriate chunk intervals (1-day for high-frequency, 7-day for orderbooks)
- 2 continuous aggregates (price_candles_1h OHLCV, trade_volume_1h) with hourly refresh policies
- Compression on all hypertables with segmentby=token_id + retention on price_snapshots/trades (90 days)
- Pydantic models for type-safe DB record handling with record_to_model() helper
- 13 integration tests passing (7 schema verification + 6 migration runner)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create core table migrations** - `df1e9e4` (feat)
2. **Task 2: Add continuous aggregates and compression policies** - `5781b0d` (feat)
3. **Task 3: Add Pydantic DB models and schema verification test** - `8b9d6c5` (feat)

## Files Created/Modified
- `src/db/migrations/002_markets.sql` - Markets metadata table with partial index on active
- `src/db/migrations/003_price_snapshots.sql` - Price hypertable, 1-day chunks
- `src/db/migrations/004_orderbook_snapshots.sql` - Orderbook hypertable, 7-day chunks
- `src/db/migrations/005_trades.sql` - Trades hypertable, 1-day chunks, unique trade_id index
- `src/db/migrations/006_resolutions.sql` - Resolution records table
- `src/db/migrations/007_continuous_aggs.sql` - price_candles_1h and trade_volume_1h aggregates
- `src/db/migrations/008_compression.sql` - Compression + retention policies
- `src/db/models.py` - Pydantic models for all 5 tables + record_to_model helper
- `tests/db/test_schema.py` - 7 integration tests verifying full schema end-state
- `tests/conftest.py` - Updated _APPLICATION_TABLES for proper test cleanup

## Decisions Made
- Unique index on trades.trade_id includes ts column — TimescaleDB requires partitioning column in unique indexes. Still provides dedup within time chunks.
- Continuous aggregates created in migration 007 before compression in 008 — ordering ensures aggregate sources exist before compression is enabled on them.
- No retention policy on orderbook_snapshots — lower volume than price/trades, worth keeping longer for analysis.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed unique index on trades.trade_id to include ts column**
- **Found during:** Task 1 (core table migrations)
- **Issue:** TimescaleDB hypertables require the partitioning column (ts) in any unique index. Plan specified `(trade_id) WHERE trade_id IS NOT NULL` which fails on hypertable.
- **Fix:** Changed to `CREATE UNIQUE INDEX idx_trades_trade_id ON trades (trade_id, ts) WHERE trade_id IS NOT NULL`
- **Files modified:** src/db/migrations/005_trades.sql
- **Verification:** Migration applies successfully, test_schema passes
- **Committed in:** df1e9e4 (Task 1), updated in 8b9d6c5 (Task 3)

**2. [Rule 3 - Blocking] Updated _APPLICATION_TABLES in conftest.py**
- **Found during:** Task 1 (core table migrations)
- **Issue:** conftest.py had placeholder table name `market_metadata` that didn't match actual schema. Tests needed correct table list for cleanup.
- **Fix:** Replaced with actual table names including continuous aggregate views
- **Files modified:** tests/conftest.py
- **Verification:** All tests pass with proper cleanup
- **Committed in:** df1e9e4 (Task 1)

---

**Total deviations:** 2 auto-fixed (2 blocking), 0 deferred
**Impact on plan:** Both fixes necessary for correct operation. No scope creep.

## Issues Encountered
None

## Next Phase Readiness
- Complete schema in place — all 8 migrations apply cleanly
- Pydantic models ready for use in query functions (01-04, 01-05, 01-06)
- record_to_model() helper available for asyncpg Record conversion
- Schema verification tests provide regression safety for future changes

---
*Phase: 01-setup-database-layer*
*Completed: 2026-02-16*
