---
phase: 01-setup-database-layer
plan: 05
subsystem: database
tags: [asyncpg, copy-protocol, bulk-insert, queries, pydantic, tdd, timescaledb]

# Dependency graph
requires:
  - phase: 01-01
    provides: asyncpg pool singleton, testcontainers test infrastructure
  - phase: 01-02
    provides: SQL migration runner with schema_migrations tracking
  - phase: 01-03
    provides: price_snapshots hypertable, PriceSnapshot model, record_to_model helper
  - phase: 01-04
    provides: shared migrated_pool fixture, ANY($1::text[]) query pattern
provides:
  - insert_price_snapshots (COPY protocol bulk insert, 10-100x faster than executemany)
  - get_latest_prices (DISTINCT ON per-token latest price)
  - get_price_history (time-range query with limit)
  - get_price_count (monitoring/health check)
affects: [01-06, phase-2]

# Tech tracking
tech-stack:
  added: []
  patterns: [COPY protocol for bulk inserts, DISTINCT ON for latest-per-group, deadlock retry for TimescaleDB background workers]

key-files:
  created:
    - src/db/queries/prices.py
    - tests/db/test_prices.py
  modified:
    - tests/db/conftest.py

key-decisions:
  - "COPY protocol via pool.copy_records_to_table() for price inserts (10-100x faster than executemany)"
  - "Added _drop_with_retry() to migrated_pool fixture for TimescaleDB deadlock resilience"
  - "Caught asyncpg.DeadlockDetectedError specifically rather than broad exception handler"

patterns-established:
  - "COPY bulk insert: pool.copy_records_to_table(table, records=list_of_tuples, columns=[...])"
  - "Deadlock retry: _drop_with_retry() with exponential backoff for TimescaleDB background worker conflicts"

issues-created: []

# Metrics
duration: 9min
completed: 2026-02-17
---

# Phase 01 Plan 05: Price Snapshot Query Functions Summary

**COPY-protocol bulk insert and read query functions for price_snapshots hypertable with deadlock-resilient test fixtures**

## Performance

- **Duration:** 9 min
- **Started:** 2026-02-16T17:26:25Z
- **Completed:** 2026-02-16T17:35:33Z
- **Tasks:** 3 (RED + GREEN + REFACTOR)
- **Files modified:** 3

## Accomplishments
- COPY-based bulk insert handling 1000+ records without error
- Latest-price-per-token query using DISTINCT ON pattern
- Time-range price history query with configurable limit
- Row count query for monitoring/health checks
- Deadlock-resilient test fixture for TimescaleDB hypertable cleanup

## TDD Cycle

### RED Phase
- Wrote 8 integration tests across 4 test classes: insert (10/1000/empty), get_latest_prices (most recent per token, nonexistent), get_price_history (time range, limit), hypertable verification
- Factory function `make_price_tuple()` creates properly-typed tuples with timezone-aware datetimes
- All 8 tests failed with `ModuleNotFoundError: No module named 'src.db.queries.prices'` as expected

### GREEN Phase
- Implemented 4 query functions in `src/db/queries/prices.py`
- `insert_price_snapshots`: Uses `pool.copy_records_to_table()` with early return for empty list
- `get_latest_prices`: `DISTINCT ON (token_id) ORDER BY token_id, ts DESC` with `ANY($1::text[])`
- `get_price_history`: Time-range query with `LIMIT` parameter, ordered `ts DESC`
- `get_price_count`: Simple `SELECT count(*)` for monitoring
- All 8 tests pass

### REFACTOR Phase
- Fixed intermittent `DeadlockDetectedError` in shared `migrated_pool` fixture
- After COPY bulk inserts of 1000 records, TimescaleDB background workers briefly held advisory locks, causing deadlocks during next test's `DROP TABLE CASCADE`
- Added `_drop_with_retry()` helper with 3 attempts and exponential backoff (0.5s, 1.0s, 1.5s)
- All 29 database tests pass reliably

## Task Commits

Each TDD phase was committed atomically:

1. **RED: Failing tests for price snapshot queries** - `a3da192` (test)
2. **GREEN: Implement price snapshot query functions** - `232de34` (feat)
3. **REFACTOR: Add deadlock retry to migrated_pool fixture** - `dabdd4a` (refactor)

## Files Created/Modified
- `src/db/queries/prices.py` - 4 query functions: insert (COPY), get_latest, get_history, get_count
- `tests/db/test_prices.py` - 8 integration tests across 4 test classes
- `tests/db/conftest.py` - Added `_drop_with_retry()` helper for deadlock resilience in migrated_pool fixture

## Decisions Made
- Used `pool.copy_records_to_table()` for bulk insert as planned (COPY protocol, 10-100x faster than executemany)
- Added `_drop_with_retry()` with `asyncpg.DeadlockDetectedError` as specific exception (not broad handler) to handle TimescaleDB background worker locks during test cleanup
- Retry uses linear backoff: `delay * (attempt + 1)` with 0.5s base, giving 0.5s/1.0s/1.5s delays

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed intermittent DeadlockDetectedError in test fixture**
- **Found during:** REFACTOR phase (after 1000-record bulk insert test)
- **Issue:** After COPY bulk inserts into hypertables, TimescaleDB background workers briefly held advisory locks. When the next test's `migrated_pool` fixture ran `DROP TABLE CASCADE`, it deadlocked against these locks.
- **Fix:** Added `_drop_with_retry()` helper to `tests/db/conftest.py` wrapping all DROP statements with 3-attempt retry and exponential backoff
- **Files modified:** tests/db/conftest.py
- **Verification:** All 29 database tests pass reliably across multiple runs
- **Committed in:** `dabdd4a`

---

**Total deviations:** 1 auto-fixed (1 bug), 0 deferred
**Impact on plan:** Fix was necessary for test reliability with COPY bulk inserts. No scope creep.

## Issues Encountered
None

## Next Phase Readiness
- All price snapshot query functions complete and tested
- Ready for 01-06 (orderbook + trade queries) — last plan in Phase 1
- 29 integration tests pass as regression safety net
- Deadlock retry pattern available for any future hypertable cleanup scenarios

---
*Phase: 01-setup-database-layer*
*Completed: 2026-02-17*
