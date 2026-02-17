# Project State: Polymarket Stat Arb

## Current Position

Phase: 4 of 5 (Daemon Supervisor + CLI)
Plan: 2 of 3 in current phase
Status: In progress
Last activity: 2026-02-18 - Completed 04-02-PLAN.md (Health Logging + CLI)

Progress: █████████████░░ 88%

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
- Token list fetched once at startup — no dynamic refresh in run(), Phase 4 daemon handles restarts (03-04)
- Single drain loop shared across all WS connections — one queue, one consumer (03-04)
- get_health() returns shallow copy for safe external access (03-04)
- Cross-platform signal handling: loop.add_signal_handler on Linux, signal.signal on Windows (04-01)
- TradeListener fully recreated on crash (internal state may be corrupted) (04-01)
- Polling collectors reuse existing instance on restart (04-01)
- Health logger is non-critical: not restarted on crash (04-02)
- get_health() uses copy.deepcopy for collector_stats to prevent mutation (04-02)
- collect CLI command uses lazy imports to avoid circular deps (04-02)

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

Last session: 2026-02-18
Stopped at: Completed 04-02-PLAN.md (Health Logging + CLI)
Resume file: none
