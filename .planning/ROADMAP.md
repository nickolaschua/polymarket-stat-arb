# Roadmap: Polymarket Statistical Arbitrage Bot

## Overview

Build the complete data-to-trading pipeline: starting with a 24/7 data collection daemon that accumulates minute-level market data from Polymarket into TimescaleDB, then layering on relationship detection, probability modeling, and automated trade execution. Data collection is the critical first step — every day without it means permanently lost training data.

## Domain Expertise

- None currently configured

## Milestones

- :construction: **v0.1 Data Foundation** - Phases 1-5 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

### :construction: v0.1 Data Foundation (In Progress)

**Milestone Goal:** Build the complete data collection pipeline from code to live deployment, so training data starts accumulating 24/7 from a non-geoblocked server.

#### Phase 1: Setup + Database Layer

**Goal**: docker-compose.yml, extend config.py (DatabaseConfig, CollectorConfig), asyncpg connection pool, Pydantic DB models, SQL migration runner + schema files, full TimescaleDB schema with hypertables/indexes/continuous aggregates/compression policies, query functions. TDD with testcontainers.
**Depends on**: Nothing (first phase)
**Research**: Likely (TimescaleDB hypertables, continuous aggregates, compression policies — new to project)
**Research topics**: TimescaleDB DDL syntax (hypertables, continuous aggregates, compression policies), testcontainers-python with TimescaleDB, asyncpg connection pool patterns
**Plans**: 6 plans (comprehensive depth)

Plans:
- [x] 01-01: Infrastructure Setup (docker-compose, config, pool, test infra)
- [x] 01-02: Migration Runner (TDD)
- [x] 01-03: Database Schema + Models (SQL migrations 002-008, Pydantic models)
- [x] 01-04: Market + Resolution Queries (TDD, upsert patterns)
- [ ] 01-05: Price Snapshot Queries (TDD, COPY bulk inserts)
- [ ] 01-06: Orderbook + Trade Queries (TDD, JSONB + integration)

#### Phase 2: Core Collectors

**Goal**: Market metadata collector (Gamma API pagination -> upserts), price snapshot collector (bulk inserts every 60s), orderbook snapshot collector (CLOB sync->async wrapping, JSONB). All with respx-mocked tests.
**Depends on**: Phase 1
**Research**: Unlikely (reuses existing Gamma API, CLOB client, rate limiting, and JSON parsing patterns already in codebase)
**Plans**: TBD

Plans:
- [ ] 02-01: TBD (run /gsd:plan-phase 2 to break down)

#### Phase 3: WebSocket Trades + Resolution Tracker

**Goal**: WebSocket trade listener with reconnect/buffer/batch logic from `wss://ws-subscriptions-clob.polymarket.com`, resolution tracker with winner inference from final prices. Thorough async testing.
**Depends on**: Phase 2
**Research**: Likely (new WebSocket integration — Polymarket trade stream API)
**Research topics**: Polymarket WebSocket API trade stream format, subscription management, reconnection patterns
**Research method**: External agent handoff (geoblocked — local IP cannot access Polymarket APIs). Write RESEARCH-REQUEST.md, wait for external agent to produce response.
**Plans**: TBD

Plans:
- [ ] 03-01: TBD (run /gsd:plan-phase 3 to break down)

#### Phase 4: Daemon Supervisor + CLI

**Goal**: Task orchestrator managing all 5 collectors as asyncio tasks, graceful shutdown on SIGINT/SIGTERM, crash recovery (restart failed tasks), health status logging. `collect` CLI command integration. End-to-end local test with Docker TimescaleDB.
**Depends on**: Phase 3
**Research**: Unlikely (internal asyncio task management, Click CLI, signal handling — patterns exist in heartbeat.py)
**Plans**: TBD

Plans:
- [ ] 04-01: TBD (run /gsd:plan-phase 4 to break down)

#### Phase 5: Hetzner Deployment

**Goal**: Server provisioning (CPX31 Frankfurt), Docker Compose for TimescaleDB on production, deploy daemon as systemd service with auto-restart, log rotation, age-encrypted private key storage, smoke test verifying data accumulation.
**Depends on**: Phase 4
**Research**: Likely (Hetzner Cloud provisioning, age-encryption for private keys, systemd service configuration)
**Research topics**: Hetzner Cloud server provisioning, age-encryption for private key management, systemd service with auto-restart and log rotation
**Plans**: TBD

Plans:
- [ ] 05-01: TBD (run /gsd:plan-phase 5 to break down)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
| 1. Setup + Database Layer | v0.1 | 4/6 | In progress | - |
| 2. Core Collectors | v0.1 | 0/? | Not started | - |
| 3. WebSocket Trades + Resolution Tracker | v0.1 | 0/? | Not started | - |
| 4. Daemon Supervisor + CLI | v0.1 | 0/? | Not started | - |
| 5. Hetzner Deployment | v0.1 | 0/? | Not started | - |
