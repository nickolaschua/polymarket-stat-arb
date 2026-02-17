---
phase: 03-websocket-trades
plan: 03
subsystem: collector
tags: [websockets, asyncio, producer-consumer, queue, batch-insert]

# Dependency graph
requires:
  - phase: 03-websocket-trades/03-01
    provides: infer_winner() function (not directly used, but part of same phase context)
  - phase: 03-websocket-trades/03-02
    provides: ResolutionTracker collector pattern, CollectorConfig extensions
  - phase: 01-setup-database-layer/01-06
    provides: insert_trades() COPY protocol for bulk trade inserts
  - phase: 02-core-collectors/02-01
    provides: Collector class pattern, respx test mocking patterns
provides:
  - parse_trade_event() function for converting WebSocket trade events to DB tuples
  - TradeListener class with single-connection lifecycle (subscribe, PING, receive, drain)
  - asyncio.Queue producer-consumer architecture for decoupled WS receive and DB insert
affects: [03-websocket-trades/03-04, 04-daemon-supervisor]

# Tech tracking
tech-stack:
  added: [websockets>=16.0]
  patterns: [websockets-async-iterator-reconnect, asyncio-queue-producer-consumer, put_nowait-drop-on-full]

key-files:
  created:
    - src/collector/trade_listener.py
    - tests/collector/test_trade_listener.py
  modified:
    - requirements.txt
    - src/config.py

key-decisions:
  - "websockets async iterator for auto-reconnect — no hand-rolled retry logic"
  - "put_nowait with drop-on-full — never block receive loop (heartbeat would fail)"
  - "trade_id=None for all WS events — WebSocket stream doesn't include trade IDs"

patterns-established:
  - "Producer-consumer via asyncio.Queue: receive loop enqueues, drain loop batches and inserts"
  - "App-level PING every 10s as separate asyncio task alongside receive loop"

issues-created: []

# Metrics
duration: 7min
completed: 2026-02-17
---

# Phase 03 Plan 03: WebSocket Trade Listener Core Summary

**WebSocket trade listener with parse_trade_event(), single-connection lifecycle, asyncio.Queue producer-consumer, and batch DB drain using websockets>=16.0 async iterator**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-17T14:48:48Z
- **Completed:** 2026-02-17T14:56:04Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- parse_trade_event() converts WebSocket JSON events to DB-ready tuples with full edge-case handling
- TradeListener class with subscribe, PING loop, receive loop, and drain loop — all async
- asyncio.Queue (10k max) decouples receive from DB inserts for backpressure resilience
- websockets async iterator provides automatic reconnection without custom retry logic
- 12 mock-based tests covering parsing edge cases, subscription format, PING timing, batch drain, and message handling

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement parse_trade_event and TradeListener class** - `3d8840d` (feat)
2. **Task 2: Write 12 mock-based tests for TradeListener** - `4ae9891` (test)

**Plan metadata:** (pending this commit)

## Files Created/Modified
- `src/collector/trade_listener.py` - parse_trade_event() function and TradeListener class (237 lines)
- `tests/collector/test_trade_listener.py` - 12 mock-based tests across 5 test classes (329 lines)
- `requirements.txt` - Updated websockets>=12.0 to websockets>=16.0
- `src/config.py` - Added ws_ping_interval_sec, ws_max_instruments_per_conn, trade_batch_drain_timeout_sec to CollectorConfig

## Decisions Made
- websockets async iterator for auto-reconnect — avoids hand-rolled retry (per RESEARCH.md "DON'T HAND ROLL")
- put_nowait with drop-on-full — never blocks receive loop, preserves heartbeat timing
- trade_id=None for all WS events — WebSocket stream doesn't include trade IDs (RESEARCH.md pitfall 2)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- TradeListener core ready — subscribe, PING, receive, drain all working
- Ready for 03-04-PLAN.md (Connection Pooling + Health) which adds multi-connection management, run/stop lifecycle, and health state on top of this single-connection foundation

---
*Phase: 03-websocket-trades*
*Completed: 2026-02-17*
