# Project State: Polymarket Stat Arb

## Current Position

Phase: 1 of 5 (Setup + Database Layer)
Plan: 3 of 6 in current phase
Status: In progress
Last activity: 2026-02-16 - Completed 01-03-PLAN.md

Progress: ██░░░░░░░░ 20%

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

Last session: 2026-02-16T16:22:22Z
Stopped at: Completed 01-03-PLAN.md
Resume file: .planning/phases/01-setup-database-layer/01-04-PLAN.md
