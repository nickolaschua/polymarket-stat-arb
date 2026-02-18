---
phase: 05-hetzner-deployment
plan: 02
subsystem: infra
tags: [hetzner, deployment, systemd, docker, timescaledb, production]

# Dependency graph
requires:
  - phase: 05-hetzner-deployment
    provides: deploy/ artifacts (docker-compose, systemd, deploy.sh, age encryption)
provides:
  - live 24/7 collector daemon on Hetzner CPX31 Nuremberg
  - data accumulating in TimescaleDB (markets, prices, orderbooks, trades)
  - systemd auto-restart for resilience
affects: [v0.2 milestone, ML training data availability]

# Tech tracking
tech-stack:
  added: [hetzner-cloud]
  patterns: [Windows OpenSSH agent for remote automation, sslmode=disable for localhost Docker DB]

key-files:
  created: []
  modified:
    - deploy/deploy.sh
    - config.prod.yaml
    - src/utils/client.py
    - src/collector/market_metadata.py
    - src/collector/price_snapshots.py
    - src/collector/orderbook_snapshots.py
    - src/collector/trade_listener.py
    - src/db/queries/markets.py

key-decisions:
  - "Docker from official apt repo, not Ubuntu default (docker-compose-plugin unavailable otherwise)"
  - "sslmode=disable for localhost Docker TimescaleDB (no SSL needed for local connection)"
  - "max_markets=10000 cap on all collectors to prevent unbounded memory/API usage"
  - "Trade listener retry loop (30x10s) for markets table race condition on startup"
  - "OrderBookSummary attribute access (not dict) for py-clob-client compatibility"

patterns-established:
  - "Windows OpenSSH ssh.exe for agent-forwarded SSH from Claude Code"
  - "Cap all unbounded pagination/queries with max_markets config"

issues-created: []

# Metrics
duration: 440min
completed: 2026-02-18
---

# Phase 5 Plan 2: Server Provisioning + Deployment + Smoke Test Summary

**Live collector daemon on Hetzner CPX31 Nuremberg with all 5 collectors writing to TimescaleDB — markets (99k), prices (8M+), orderbooks (2.7k), trades (66)**

## Performance

- **Duration:** 7h 20m (interactive deployment with debugging)
- **Started:** 2026-02-18T10:44:21Z
- **Completed:** 2026-02-18T18:04:35Z
- **Tasks:** 3 (all checkpoints — guided deployment)
- **Files modified:** 8

## Accomplishments
- Hetzner CPX31 provisioned in Nuremberg with Ubuntu 24.04, SSH access confirmed
- Full deployment automated via SSH: repo clone, deploy.sh bootstrap, Docker + TimescaleDB + migrations + systemd
- All 5 collectors running 24/7: metadata, prices, orderbooks, trades (WebSocket), resolutions
- Data actively accumulating in TimescaleDB (verified non-zero counts across all tables)
- Service auto-restarts on failure (systemd Restart=always)

## Task Commits

Each fix was committed atomically:

1. **Fix: Docker official repo** - `c659730` (fix) — Ubuntu default repos lack docker-compose-plugin
2. **Fix: SSL disable for localhost DB** - `746b649` (fix) — asyncpg SSL negotiation fails on plain Docker
3. **Fix: Pagination cap + trade listener race** - `9c02327` (fix) — unbounded 100k+ event fetch consumed 6GB+
4. **Fix: OrderBookSummary attribute access** - `6e3a463` (fix) — py-clob-client returns objects not dicts
5. **Fix: Cap active market queries** - `7b971f6` (fix) — orderbook collector tried 200k+ CLOB API calls

## Files Created/Modified
- `deploy/deploy.sh` - Added Docker official apt repository setup (Ubuntu 24.04 compatibility)
- `config.prod.yaml` - Added `?sslmode=disable` to database URL for localhost Docker
- `src/utils/client.py` - Added `max_events` parameter to `get_all_active_markets()`
- `src/collector/market_metadata.py` - Passes `max_markets` to cap pagination
- `src/collector/price_snapshots.py` - Passes `max_markets` to cap pagination
- `src/collector/orderbook_snapshots.py` - Passes `max_markets` to cap DB query; fixed OrderBookSummary attribute access
- `src/collector/trade_listener.py` - Added 30-retry loop for markets table race condition; capped market query
- `src/db/queries/markets.py` - Added `limit` parameter to `get_active_markets()`

## Decisions Made
- Docker must be installed from official apt repository on Ubuntu 24.04 (default repos don't include docker-compose-plugin)
- sslmode=disable for localhost Docker TimescaleDB — no SSL overhead for local-only connection
- max_markets=10000 enforced across all collectors to prevent memory exhaustion and API overload
- Trade listener retries token fetch 30 times (5 min) to handle metadata collector startup race condition
- OrderBookSummary from py-clob-client uses attribute access (.bids, .asks) not dict access

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Docker official apt repository required**
- **Found during:** Task 2 (deploy.sh execution)
- **Issue:** `docker-compose-plugin` not available in Ubuntu 24.04 default repos
- **Fix:** Added Docker official GPG key and apt repo to deploy.sh step 1
- **Committed in:** `c659730`

**2. [Rule 3 - Blocking] SSL negotiation fails on localhost Docker**
- **Found during:** Task 2 (migration runner)
- **Issue:** asyncpg defaults to SSL, Docker TimescaleDB has no SSL configured
- **Fix:** Added `?sslmode=disable` to production database URL
- **Committed in:** `746b649`

**3. [Rule 1 - Bug] Unbounded event pagination consumed 6GB+ memory**
- **Found during:** Task 2 (first collector run)
- **Issue:** `get_all_active_markets()` fetched ALL 100k+ events without limit, server nearly OOM'd
- **Fix:** Added `max_events` parameter, collectors pass `config.max_markets` (10,000)
- **Committed in:** `9c02327`

**4. [Rule 1 - Bug] Trade listener race condition on startup**
- **Found during:** Task 2 (daemon startup)
- **Issue:** Trade listener exited immediately when markets table empty (metadata collector not finished)
- **Fix:** Added 30-retry loop with 10s intervals (5 min total wait)
- **Committed in:** `9c02327`

**5. [Rule 1 - Bug] OrderBookSummary attribute access**
- **Found during:** Task 2 (orderbook collection)
- **Issue:** py-clob-client returns OrderBookSummary objects, code used dict .get() access
- **Fix:** Changed to attribute access with hasattr fallback
- **Committed in:** `6e3a463`

**6. [Rule 1 - Bug] Orderbook collector queried all 99k active markets**
- **Found during:** Task 3 verification
- **Issue:** 99k markets = 200k tokens = 10,000 CLOB API calls per cycle, never completing in 5 min
- **Fix:** Added limit parameter to `get_active_markets()`, orderbook + trade listener pass max_markets
- **Committed in:** `7b971f6`

---

**Total deviations:** 6 auto-fixed (3 bugs, 3 blocking), 0 deferred
**Impact on plan:** All fixes essential for production operation. No scope creep.

## Issues Encountered
- Server became unresponsive after 6GB+ memory spike from unbounded pagination — required Hetzner console reboot
- SSH agent passphrase not available to Git Bash — resolved by using Windows OpenSSH ssh.exe directly
- Polymarket /api/geoblock returns blocked=true for Germany, but actual APIs (Gamma, CLOB) work fine — frontend-only restriction

## Next Phase Readiness
- v0.1 Data Foundation milestone COMPLETE
- Collector daemon running 24/7 on Hetzner CPX31 Nuremberg
- Data accumulating in all tables, ready for ML training pipeline
- No blockers

---
*Phase: 05-hetzner-deployment*
*Completed: 2026-02-18*
