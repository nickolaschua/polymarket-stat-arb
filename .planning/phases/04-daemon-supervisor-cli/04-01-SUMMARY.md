---
phase: 04-daemon-supervisor-cli
plan: 01
subsystem: collector
tags: [asyncio, signal-handling, crash-recovery, daemon, orchestrator]

# Dependency graph
requires:
  - phase: 03-websocket-trades/03-04
    provides: TradeListener run()/stop() lifecycle, TradeListenerHealth
  - phase: 02-core-collectors/02-01
    provides: MarketMetadataCollector collect_once() pattern
  - phase: 02-core-collectors/02-02
    provides: PriceSnapshotCollector collect_once() pattern
  - phase: 02-core-collectors/02-03
    provides: OrderbookSnapshotCollector collect_once() pattern
  - phase: 03-websocket-trades/03-02
    provides: ResolutionTracker collect_once() pattern
provides:
  - CollectorDaemon orchestrator class with run()/stop() lifecycle
  - Cross-platform signal handling (SIGINT/SIGTERM)
  - Crash recovery with exponential backoff (5s→60s, max 5 restarts)
  - TradeListener recreation on crash (fresh internal state)
affects: [04-daemon-supervisor-cli/04-02, 04-daemon-supervisor-cli/04-03]

# Tech tracking
tech-stack:
  added: []
  patterns: [daemon-orchestrator, cross-platform-signal-handling, exponential-backoff-restart, monitor-task-pattern]

key-files:
  created:
    - src/collector/daemon.py
  modified: []

key-decisions:
  - "Cross-platform signal handling: loop.add_signal_handler on Linux, signal.signal on Windows"
  - "TradeListener fully recreated on crash (internal state may be corrupted)"
  - "Polling collectors reuse existing instance on restart"
  - "Monitor task skips itself in crash detection"

patterns-established:
  - "Daemon orchestrator: CollectorDaemon(pool, client, config) with run()/stop()"
  - "Crash recovery: _monitor_tasks every 10s with exponential backoff"

issues-created: []

# Metrics
duration: 5min
completed: 2026-02-17
---

# Phase 4 Plan 1: Collector Daemon Core Summary

**CollectorDaemon orchestrator managing 5 collectors as asyncio tasks with cross-platform signal handling and exponential-backoff crash recovery**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-17T15:40:13Z
- **Completed:** 2026-02-17T15:45:13Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- CollectorDaemon class orchestrating all 5 collectors (4 polling + 1 WebSocket)
- Cross-platform signal handling (SIGINT/SIGTERM on Linux, SIGINT on Windows)
- Crash recovery with exponential backoff (5s→10s→20s→40s→60s cap, max 5 restarts)
- TradeListener recreation on crash for clean internal state

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CollectorDaemon with run/stop lifecycle** - `8dedb7b` (feat)
2. **Task 2: Add crash recovery with auto-restart** - `c30e8b1` (feat)

## Files Created/Modified
- `src/collector/daemon.py` - CollectorDaemon orchestrator class (281 lines)

## Decisions Made
- Cross-platform signal handling: `loop.add_signal_handler` on non-Windows, `signal.signal` on Windows (loop handler not supported)
- TradeListener fully recreated on crash because internal state (queue, health, tasks) may be corrupted
- Polling collectors reuse existing instance on restart (stateless collect_once pattern)
- Monitor task skips itself (`_monitor`) in crash detection loop

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- CollectorDaemon ready for health logging integration (04-02)
- Ready for daemon test suite (04-03)
- No blockers

---
*Phase: 04-daemon-supervisor-cli*
*Completed: 2026-02-17*
