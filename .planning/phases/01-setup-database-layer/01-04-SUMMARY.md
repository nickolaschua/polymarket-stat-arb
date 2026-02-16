---
phase: 01-setup-database-layer
plan: 04
subsystem: database
tags: [asyncpg, queries, upsert, pydantic, tdd]

# Dependency graph
requires:
  - phase: 01-01
    provides: asyncpg pool singleton, testcontainers test infrastructure
  - phase: 01-02
    provides: SQL migration runner with schema_migrations tracking
  - phase: 01-03
    provides: markets + resolutions tables, Pydantic models, record_to_model helper
provides:
  - Market query functions (upsert, batch upsert, get, get_active, get_by_ids)
  - Resolution query functions (upsert, get, get_unresolved)
  - Shared migrated_pool fixture in tests/db/conftest.py
affects: [01-05, 01-06, phase-2]

# Tech tracking
tech-stack:
  added: []
  patterns: [upsert via ON CONFLICT DO UPDATE, ANY($1::text[]) for array params, LEFT JOIN for missing records]

key-files:
  created:
    - src/db/queries/__init__.py
    - src/db/queries/markets.py
    - src/db/queries/resolutions.py
    - tests/db/test_markets.py
    - tests/db/test_resolutions.py
    - tests/db/conftest.py
  modified:
    - tests/db/test_schema.py

key-decisions:
  - "Extracted migrated_pool fixture to shared tests/db/conftest.py for reuse across test files"
  - "Batch upsert via simple loop (not executemany) since 5-min interval is not perf-critical"
  - "get_unresolved_markets returns list[str] not list[MarketRecord] (only needs condition_ids)"

patterns-established:
  - "Upsert pattern: INSERT ... ON CONFLICT (pk) DO UPDATE SET col=EXCLUDED.col, updated_at=NOW()"
  - "Array query pattern: WHERE col = ANY($1::text[])"
  - "Query return pattern: record_to_model(row, ModelClass) for Pydantic conversion"

issues-created: []

# Metrics
duration: ~10min
completed: 2026-02-17
---

# Phase 01 Plan 04: Market + Resolution Query Functions Summary

**UPSERT and read query functions for markets and resolutions tables with full TDD cycle against real TimescaleDB**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 (RED + GREEN; REFACTOR skipped -- implementation clean)
- **Files modified:** 7

## Accomplishments
- 5 market query functions: upsert_market, upsert_markets, get_market, get_active_markets, get_markets_by_ids
- 3 resolution query functions: upsert_resolution, get_resolution, get_unresolved_markets
- All functions use asyncpg pool directly and return Pydantic models
- Idempotent upserts via INSERT ON CONFLICT DO UPDATE
- Array parameter queries use ANY($1::text[]) pattern
- Shared migrated_pool fixture extracted to tests/db/conftest.py

## TDD Cycle

### RED Phase
- Wrote 5 market test cases: insert, update (with updated_at change), batch insert, active-only filter, get-by-ids with array param
- Wrote 3 resolution test cases: insert, update outcome, get unresolved via LEFT JOIN
- All 8 tests failed with NotImplementedError (stubs only)

### GREEN Phase
- Implemented all 8 functions following plan specifications exactly
- Market upserts use EXCLUDED.column for all mutable fields, updated_at=NOW() on conflict
- Resolution upserts use EXCLUDED for outcome, winner_token_id, resolved_at, payout_price, detection_method
- get_unresolved_markets uses LEFT JOIN markets/resolutions WHERE r.condition_id IS NULL AND m.closed = true
- All 8 tests pass; all 21 db tests pass (8 new + 6 migration + 7 schema)

### REFACTOR Phase
- Skipped -- implementation was clean and concise, no improvements needed

## Task Commits

Each TDD phase was committed atomically:

1. **RED: Failing tests for market + resolution queries** - `8de7956` (test)
2. **GREEN: Implement query functions** - `8ea59b2` (feat)

_REFACTOR skipped -- no commit needed_

## Files Created/Modified
- `src/db/queries/__init__.py` - Package init with docstring
- `src/db/queries/markets.py` - 5 query functions for markets table
- `src/db/queries/resolutions.py` - 3 query functions for resolutions table
- `tests/db/test_markets.py` - 5 integration tests for market queries
- `tests/db/test_resolutions.py` - 3 integration tests for resolution queries
- `tests/db/conftest.py` - Shared migrated_pool fixture (extracted from test_schema.py)
- `tests/db/test_schema.py` - Removed local migrated_pool fixture (now uses shared one)

## Decisions Made
- Extracted migrated_pool fixture to tests/db/conftest.py so all db test files can reuse it without duplication
- Batch upsert uses simple loop over upsert_market (not executemany) since collector runs every 5 minutes -- simplicity over micro-optimization
- get_unresolved_markets returns list[str] (condition_ids only), not full MarketRecord objects, matching the plan specification

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Extracted migrated_pool fixture to shared conftest**
- **Found during:** RED phase (test setup)
- **Issue:** Plan referenced migrated_pool as an existing fixture, but it was only defined locally in test_schema.py. New test files needed it too.
- **Fix:** Created tests/db/conftest.py with the migrated_pool fixture; removed duplicate from test_schema.py
- **Files modified:** tests/db/conftest.py (new), tests/db/test_schema.py (modified)
- **Verification:** All 21 tests pass including existing schema tests

---

**Total deviations:** 1 auto-fixed (1 blocking), 0 deferred
**Impact on plan:** Minimal -- fixture extraction was necessary infrastructure, no scope creep.

## Issues Encountered
None

## Next Phase Readiness
- Query function pattern established for 01-05 (price snapshot queries using COPY)
- Query function pattern established for 01-06 (orderbook + trade queries)
- Shared migrated_pool fixture available for all future db test files
- All 21 integration tests pass as regression safety net

---
*Phase: 01-setup-database-layer*
*Completed: 2026-02-17*
