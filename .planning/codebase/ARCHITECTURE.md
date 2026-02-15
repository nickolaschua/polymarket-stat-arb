# Architecture

**Analysis Date:** 2026-02-16

## Pattern Overview

**Overall:** Modular Async CLI Application (Scanner-Executor-Monitor)

**Key Characteristics:**
- Async-first design (asyncio + httpx throughout)
- Modular pipeline: Scanner → Executor → Monitor (only Scanner implemented)
- Single-process with multiple asyncio tasks
- Paper trading mode by default (safe read-only operation)
- Wrapper pattern around third-party API client (py-clob-client)

## Layers

**CLI Layer:**
- Purpose: Parse user commands, configure logging, invoke modules
- Contains: Click commands (`scan`, `run`, `check`, `price`, `book`)
- Location: `src/main.py`
- Depends on: Scanner, Client, Config
- Used by: User via command line

**Scanner Layer:**
- Purpose: Market discovery, data parsing, arbitrage detection
- Contains: Market fetching, event grouping, arbitrage algorithms
- Location: `src/scanner/main.py`, `src/scanner/arbitrage.py`
- Depends on: Client (API access), Utils (rate limiting)
- Used by: CLI layer

**Client Layer:**
- Purpose: Unified API wrapper for all Polymarket endpoints
- Contains: Market data reads, authenticated trading, heartbeat management
- Location: `src/utils/client.py`
- Depends on: py-clob-client, httpx, Config
- Used by: Scanner, future Executor/Monitor

**Risk/Resilience Layer:**
- Purpose: Protect against losses, API failures, rate limits
- Contains: Circuit breaker, retry logic, rate limiters, heartbeat
- Location: `src/utils/circuit_breaker.py`, `src/utils/retry.py`, `src/utils/heartbeat.py`
- Depends on: Config
- Used by: Client, Scanner, future Executor

**Config Layer:**
- Purpose: Type-safe configuration from YAML + environment variables
- Contains: Pydantic models for all config sections
- Location: `src/config.py`
- Depends on: pyyaml, pydantic
- Used by: All other layers

**Stub Layers (not yet implemented):**
- Executor (`src/executor/__init__.py`) — order placement, signing, position management
- Monitor (`src/monitor/__init__.py`) — P&L tracking, alerts, metrics

## Data Flow

**Market Scanning (primary flow):**

1. CLI invokes `MarketScanner.run()` (`src/main.py`)
2. `refresh_markets()` calls `PolymarketClient.get_all_active_markets()` (`src/scanner/main.py`)
3. Client paginates Gamma API `/events` endpoint with async httpx (`src/utils/client.py`)
4. Rate limiter gates requests (token-bucket at 70% of API limit) (`src/utils/retry.py`)
5. Raw API responses parsed into `Market` dataclasses (`src/scanner/arbitrage.py`)
6. Stringified JSON arrays (`outcomePrices`, `clobTokenIds`) parsed defensively (`src/scanner/arbitrage.py`)
7. `ArbitrageScanner.scan_same_market()` checks YES + NO price < $1.00 (`src/scanner/arbitrage.py`)
8. Opportunities filtered by min spread % and liquidity thresholds
9. Results displayed in Rich table sorted by spread % (`src/scanner/main.py`)
10. Loop repeats after configurable interval

**State Management:**
- File-based: Circuit breaker state persists to JSON on disk (`src/utils/circuit_breaker.py`)
- In-memory: Rate limiter token buckets, heartbeat stats
- No database yet (SQLAlchemy imported but unused)

## Key Abstractions

**PolymarketClient:**
- Purpose: Unified interface to 4 Polymarket APIs (Gamma, CLOB, Data, WebSocket)
- Location: `src/utils/client.py`
- Pattern: Wrapper around py-clob-client + async httpx for Gamma API
- Handles: Authentication, paper trading flag, heartbeat lifecycle

**Market / ArbitrageOpportunity (dataclasses):**
- Purpose: Type-safe data containers for market data and detected opportunities
- Location: `src/scanner/arbitrage.py`
- Pattern: Python dataclasses with computed fields

**CircuitBreaker:**
- Purpose: Automatic trading halt on risk threshold breach
- Location: `src/utils/circuit_breaker.py`
- Pattern: State machine (closed → open → half-open) with disk persistence

**RateLimiter:**
- Purpose: Token-bucket rate limiting per API endpoint
- Location: `src/utils/retry.py`
- Pattern: Pre-configured singleton instances (`gamma_limiter`, `clob_read_limiter`, `clob_trade_limiter`)

**HeartbeatManager:**
- Purpose: Background task sending CLOB heartbeats every 8s (10s server requirement)
- Location: `src/utils/heartbeat.py`
- Pattern: asyncio background task with failure counting and emergency callback

**Config (Pydantic):**
- Purpose: Typed, validated configuration with nested sections
- Location: `src/config.py`
- Pattern: Pydantic BaseModel with global singleton accessor `get_config()`

## Entry Points

**CLI Entry (`src/main.py`):**
- Triggers: `python -m src.main <command>`
- Commands: `scan`, `run`, `check`, `price`, `book`
- Responsibilities: Parse args, configure logging, invoke scanner/client

**Scanner Direct (`src/scanner/main.py`):**
- Triggers: `python -m src.scanner.main`
- Responsibilities: Run scanner loop directly (bypass CLI)

**Test Connection (`scripts/test_connection.py`):**
- Triggers: `python scripts/test_connection.py`
- Responsibilities: Quick API connectivity check

## Error Handling

**Strategy:** Decorator-based retry with exception classification + circuit breaker halt

**Patterns:**
- `@retry()` decorator catches transient errors (timeouts, 429, 5xx) and retries with exponential backoff (`src/utils/retry.py`)
- Non-retryable errors (400, 401, 403, 404) propagate immediately
- Rate limiter proactively avoids 429s; `record_response()` handles 429 backoff
- Circuit breaker trips on cumulative losses, halting all trading (`src/utils/circuit_breaker.py`)
- HeartbeatManager counts consecutive failures, triggers emergency callback after 3 (`src/utils/heartbeat.py`)

## Cross-Cutting Concerns

**Logging:**
- Python `logging` module with configurable level via config
- Structured log messages in scanner and utilities
- Rich console output for CLI display

**Validation:**
- Pydantic V2 for config validation at load time (`src/config.py`)
- Defensive JSON parsing for Gamma API stringified arrays (`src/scanner/arbitrage.py`)
- `paper_trading` flag gates all real order placement (`src/utils/client.py`)

**Rate Limiting:**
- Token-bucket algorithm at 70% of documented API limits (`src/utils/retry.py`)
- Three pre-configured limiters: Gamma (200/10s), CLOB read (1000/10s), CLOB trade (400/10s)
- Respects `Retry-After` header on 429 responses

---

*Architecture analysis: 2026-02-16*
*Update when major patterns change*
