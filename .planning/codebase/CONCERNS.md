# Codebase Concerns

**Analysis Date:** 2026-02-16

## Tech Debt

**No test coverage at all:**
- Issue: Zero test files despite pytest/pytest-asyncio in requirements
- Files: Entire `src/` directory untested
- Why: Rapid prototyping phase, research-first approach
- Impact: No regression safety, can't refactor confidently
- Fix approach: TDD for new code (data daemon), backfill critical paths

**Stub modules with no implementation:**
- Issue: Executor and Monitor modules are empty placeholders
- Files: `src/executor/__init__.py`, `src/monitor/__init__.py`
- Why: Scanner-first development approach
- Impact: No trading or position tracking capability
- Fix approach: Implement after data collection infrastructure is in place

**SQLAlchemy imported but unused:**
- Issue: `sqlalchemy>=2.0.0` and `aiosqlite>=0.19.0` in dependencies but never used
- Files: `requirements.txt`
- Why: Originally planned for persistence, decision changed to asyncpg + TimescaleDB
- Impact: Unnecessary dependency bloat
- Fix approach: Remove when switching to asyncpg for TimescaleDB

**ML dependencies installed but unused:**
- Issue: chromadb, sentence-transformers, pandas, numpy listed but not imported anywhere
- Files: `requirements.txt`
- Why: Forward-looking dependency list for planned features
- Impact: Heavy install footprint (~2GB+ for sentence-transformers alone)
- Fix approach: Move to separate `requirements-ml.txt` or install when needed

## Known Bugs

**No known runtime bugs detected.**
- Codebase is relatively new and scanner has been manually tested

## Security Considerations

**Private key handling:**
- Risk: Wallet private key loaded from environment variable into memory
- Files: `src/config.py` (WalletConfig reads `POLY_PRIVATE_KEY`)
- Current mitigation: Env var approach (never in config file), `.gitignore` excludes `.env`
- Recommendations: Ensure process memory is protected, consider vault integration for production

**Paper trading flag is a boolean:**
- Risk: Single boolean `paper_trading: true` separates read-only from real-money trading
- Files: `src/utils/client.py` (checked before order placement), `config.example.yaml`
- Current mitigation: Default is `true` (safe)
- Recommendations: Consider requiring explicit `--live` CLI flag AND config setting to enable real trading

**No input validation on CLI token IDs:**
- Risk: `price` and `book` commands accept arbitrary token_id strings without validation
- Files: `src/main.py` (Click commands)
- Current mitigation: API will reject invalid IDs
- Recommendations: Low risk — API-side validation is sufficient

## Performance Bottlenecks

**Synchronous py-clob-client in async context:**
- Problem: py-clob-client is synchronous, must be wrapped with `run_in_executor`
- Files: `src/utils/heartbeat.py` (heartbeat send), `src/utils/client.py` (orderbook, orders)
- Measurement: Each `run_in_executor` call adds thread pool overhead
- Cause: Third-party library design limitation
- Improvement path: Accept as necessary overhead, or contribute async support to py-clob-client

**Sequential market fetching:**
- Problem: `get_all_active_markets()` paginates sequentially (one page at a time)
- Files: `src/utils/client.py`
- Measurement: ~1000 markets across multiple pages, each waiting for previous
- Cause: Pagination requires previous response's cursor
- Improvement path: Acceptable — pagination is inherently sequential, rate limiter prevents faster

## Fragile Areas

**Stringified JSON array parsing:**
- Files: `src/scanner/arbitrage.py` (`_parse_stringified_json_array`)
- Why fragile: Gamma API returns prices as `'["0.52","0.48"]'` (string, not array). Parsing depends on exact format.
- Common failures: Format changes, empty strings, malformed JSON
- Safe modification: Defensive parsing already in place with try/except
- Test coverage: None — this is a high-priority test target

**Heartbeat timing:**
- Files: `src/utils/heartbeat.py`
- Why fragile: CLOB requires heartbeat every 10s, bot sends every 8s (2s margin). Network delays or GC pauses could miss window.
- Common failures: All open orders cancelled if heartbeat missed
- Safe modification: Emergency callback mechanism exists for 3 consecutive failures
- Test coverage: None

## Scaling Limits

**In-memory rate limiters:**
- Current capacity: Handles single-process operation well
- Limit: If multiple bot instances run, rate limits aren't shared
- Symptoms at limit: 429 errors from API
- Scaling path: Centralized rate limiting (Redis) if scaling to multiple processes

**Hetzner CPX31 disk (planned):**
- Current capacity: 160 GB disk
- Limit: ~3+ years of compressed TimescaleDB data before full
- Scaling path: Increase disk or add retention policies (already planned)

## Dependencies at Risk

**py-clob-client:**
- Risk: Polymarket's official Python client — must track their API changes
- Impact: All trading and orderbook operations break if API changes
- Migration plan: Pin version, monitor Polymarket GitHub for breaking changes

**chromadb + sentence-transformers:**
- Risk: Heavy dependencies (large models, complex build), not yet used
- Impact: Slows installation, potential version conflicts
- Migration plan: Remove from main requirements until actively needed

## Missing Critical Features

**Data collection daemon:**
- Problem: No minute-level price data collection for ML training
- Current workaround: None — Polymarket only offers 12-hour candles for resolved markets
- Blocks: ML model training, backtesting, all advanced strategies
- Implementation complexity: Medium-High (detailed plan in `docs/HANDOFF_DATA_DAEMON.md`)

**Order execution:**
- Problem: Can detect arbitrage but can't act on it
- Current workaround: Manual trading based on scanner output
- Blocks: Automated profit capture
- Implementation complexity: Medium (auth + signing + risk checks)

**Position monitoring:**
- Problem: No P&L tracking, no position awareness
- Current workaround: Manual checking via Polymarket UI
- Blocks: Risk management, performance analysis
- Implementation complexity: Medium

## Test Coverage Gaps

**Entire codebase untested:**
- What's not tested: All 1,534 lines of application code
- Risk: Any change could silently break functionality
- Priority: High — especially for `src/scanner/arbitrage.py` (core logic) and `src/utils/retry.py` (resilience)
- Difficulty to test: Moderate — async code needs pytest-asyncio, API calls need mocking

**Critical untested paths:**
1. `src/scanner/arbitrage.py` - Arbitrage detection math, JSON parsing
2. `src/utils/retry.py` - Retry logic, rate limiting behavior
3. `src/utils/circuit_breaker.py` - State transitions, persistence
4. `src/utils/heartbeat.py` - Timing, failure recovery
5. `src/config.py` - Config loading, env var resolution

---

*Concerns audit: 2026-02-16*
*Update as issues are fixed or new ones discovered*
