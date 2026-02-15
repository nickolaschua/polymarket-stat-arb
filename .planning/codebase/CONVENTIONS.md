# Coding Conventions

**Analysis Date:** 2026-02-16

## Naming Patterns

**Files:**
- snake_case.py for all Python modules (`circuit_breaker.py`, `test_connection.py`)
- `main.py` for entry points within packages
- `__init__.py` for package markers (some empty for stubs)

**Functions:**
- snake_case for all functions (`scan_same_market`, `get_all_active_markets`, `record_trade`)
- Async functions prefixed with `async` keyword, no naming distinction (`async def refresh_markets`)
- Private methods prefixed with underscore (`_parse_stringified_json_array`, `_heartbeat_loop`)

**Variables:**
- snake_case for variables and parameters (`min_spread_pct`, `token_id`, `max_retries`)
- UPPER_SNAKE_CASE for module-level constants (`DEFAULT_CLOB_HOST`, `MAX_DELAY`)
- Private attributes with underscore prefix (`self._pool`, `self._clob_client`)

**Classes:**
- PascalCase for classes (`PolymarketClient`, `ArbitrageScanner`, `CircuitBreaker`)
- PascalCase for dataclasses (`Market`, `ArbitrageOpportunity`, `CircuitBreakerState`)
- PascalCase for Pydantic models (`Config`, `RiskConfig`, `StrategyConfig`)

## Code Style

**Formatting:**
- No formatter config detected (no `.flake8`, `pyproject.toml` [tool.black], or similar)
- 4-space indentation (Python standard)
- Double quotes for strings (predominant in `src/utils/client.py`, `src/config.py`)
- Single quotes also used (mixed usage in `src/scanner/arbitrage.py`)
- No enforced line length

**Linting:**
- No linter configuration detected
- No pre-commit hooks

## Import Organization

**Order (observed pattern):**
1. Standard library (`import asyncio`, `import json`, `import logging`, `from dataclasses import dataclass`)
2. Third-party packages (`import httpx`, `from pydantic import BaseModel`, `import click`)
3. Local imports (`from src.config import get_config`, `from src.utils.retry import retry`)

**Grouping:**
- Blank lines between standard lib, third-party, and local groups
- No enforced sorting within groups

**Path Style:**
- Absolute imports from project root (`from src.config import ...`)
- No path aliases configured

## Error Handling

**Patterns:**
- Decorator-based retry for transient failures (`@retry()` in `src/utils/retry.py`)
- Exception classification: retryable vs non-retryable (`src/utils/retry.py`)
- Circuit breaker for cumulative risk management (`src/utils/circuit_breaker.py`)
- `try/except` blocks in scanner loop and API calls

**Error Types:**
- Catch specific exceptions: `httpx.TimeoutException`, `ConnectionError`, `json.JSONDecodeError`
- Never retry: `KeyboardInterrupt`, `SystemExit`, `MemoryError`
- HTTP status-based: retry on 429/5xx, fail on 4xx

**Async Error Handling:**
- `asyncio.CancelledError` handled in heartbeat for graceful shutdown (`src/utils/heartbeat.py`)
- `run_in_executor` wraps sync py-clob-client calls in async context (`src/utils/heartbeat.py`)

## Logging

**Framework:**
- Python `logging` module (standard library)
- Logger per module: `logger = logging.getLogger(__name__)`

**Patterns:**
- `logger.info()` for operational events ("Found N markets", "Scanning...")
- `logger.warning()` for degraded states ("Rate limited", "Heartbeat failure")
- `logger.error()` for failures with context
- `logger.debug()` for verbose diagnostic output
- Rich console for CLI-facing output (tables, formatted text)

## Comments

**When to Comment:**
- Docstrings on classes and key public methods (descriptive, not exhaustive)
- Inline comments for non-obvious logic (rate limit calculations, API quirks)
- Section comments in longer functions

**Docstring Style:**
- Triple double-quotes (`"""..."""`)
- Brief one-liner for simple functions
- Multi-line with description for complex classes (see `CircuitBreaker`, `HeartbeatManager`)
- No enforced format (not NumPy, Google, or Sphinx style consistently)

**TODO Comments:**
- Not systematically used in current codebase

## Function Design

**Size:**
- Most functions 10-40 lines
- Longer functions exist in client.py and retry.py (up to 50+ lines)

**Parameters:**
- Explicit keyword arguments with defaults: `def __init__(self, min_spread_pct: float = 2.0)`
- Type hints used on function signatures (not universally)
- Config objects passed as parameters or accessed via `get_config()` singleton

**Return Values:**
- Explicit returns with type hints where used
- Optional returns for nullable results
- Dataclass instances for structured data

## Module Design

**Exports:**
- No barrel file pattern (no re-exports from `__init__.py`)
- Most `__init__.py` files are empty
- Direct imports from specific modules preferred

**Async Pattern:**
- Async methods for I/O operations (API calls, file operations)
- `run_in_executor` to wrap sync third-party calls (py-clob-client)
- Background tasks via `asyncio.create_task()` for heartbeat and monitoring loops

---

*Convention analysis: 2026-02-16*
*Update when patterns change*
