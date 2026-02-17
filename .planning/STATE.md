# Project State: Polymarket Stat Arb

## Current Position

Phase: 3 of 5 (WebSocket Trades + Resolution Tracker)
Plan: 3 of 4 in current phase
Status: In progress
Last activity: 2026-02-17 - Completed 03-03-PLAN.md (WebSocket Trade Listener Core)

Progress: █████████░ 76%

## Accumulated Context

### Key Decisions
- TimescaleDB over SQLite for time-series data (compression, continuous aggregates)
- asyncpg directly, no ORM (raw SQL for TimescaleDB features, 3x faster bulk inserts)
- Hetzner CPX31 Frankfurt for production ($14/mo, non-geoblocked IP)
- GTC limit orders, not market orders (edge from better estimates, not speed)
- Data daemon first (prerequisite for ML training, irreplaceable data)
- 70% rate limit safety margins (gamma_limiter, clob_read_limiter)
- Pool state tracked via _pool_closed boolean, not asyncpg private attrs (01-01)
- testcontainers import guarded with try/except for non-integration tests (01-01)
- Container session-scoped, pool function-scoped for test isolation (01-01)
- INSERT tracking row outside DDL transaction to avoid extension auto-commit issues (01-02)
- Single connection via pool.acquire() for consistent schema_migrations reads (01-02)
- Unique index on trades.trade_id must include ts column (TimescaleDB hypertable partitioning requirement) (01-03)
- Continuous aggregates created before compression policies for compatibility ordering (01-03)
- Extracted migrated_pool fixture to shared tests/db/conftest.py for reuse across test files (01-04)
- Batch upsert via simple loop (not executemany) since 5-min collector interval is not perf-critical (01-04)
- COPY protocol via pool.copy_records_to_table() for price inserts (10-100x faster than executemany) (01-05)
- _drop_with_retry() with asyncpg.DeadlockDetectedError for TimescaleDB background worker deadlocks in test fixtures (01-05)
- executemany with $x::jsonb cast for orderbook inserts — COPY cannot encode Python dicts to JSONB (01-06)
- Per-connection JSONB codec via set_type_codec() for dict round-trip on reads (01-06)
- COPY protocol for trade inserts with UniqueViolationError fallback to ON CONFLICT DO NOTHING (01-06)
- Duplicated migrated_pool fixture into tests/collector/conftest.py for pytest conftest scoping (02-01)
- infer_winner never raises — returns None on any error to prevent one malformed market from crashing collection loop (03-01)
- websockets async iterator for auto-reconnect — no hand-rolled retry logic (03-03)
- put_nowait with drop-on-full — never block receive loop to preserve heartbeat timing (03-03)
- trade_id=None for all WS events — WebSocket stream doesn't include trade IDs (03-03)

### Critical Constraints
- Geoblocking: Local Windows machine cannot access Polymarket APIs. All local tests use mocked responses (respx). Live data collection only from Hetzner.
- External research pattern: Phase 3 WebSocket research requires external agent handoff (write RESEARCH-REQUEST.md, wait for response).
- py-clob-client is synchronous: All CLOB calls must use `run_in_executor()` in async context.
- Gamma API stringified JSON: `outcomePrices` and `clobTokenIds` are stringified JSON arrays.
- Windows dev: asyncpg requires `WindowsSelectorEventLoopPolicy`.

### Blockers/Concerns Carried Forward
- None

### Roadmap Evolution
- Milestone v0.1 Data Foundation created: data collection pipeline, 5 phases (Phase 1-5)

## Session Continuity

Last session: 2026-02-17
Stopped at: 03-03 complete, ready for 03-04 (Connection Pooling + Health)
Resume file: none
