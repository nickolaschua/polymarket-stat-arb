# Testing Patterns

**Analysis Date:** 2026-02-16

## Test Framework

**Runner:**
- pytest >=7.0.0 - Listed in `requirements.txt`
- pytest-asyncio >=0.21.0 - Async test support in `requirements.txt`

**Assertion Library:**
- pytest built-in assert (expected, not yet used)

**Run Commands:**
```bash
pytest                                    # Run all tests (no tests exist yet)
pytest tests/unit/ -v                     # Unit tests (planned)
pytest tests/integration/ -v              # Integration tests (planned)
pytest tests/collector/ -v                # Collector tests (planned)
```

## Test File Organization

**Location:**
- No test files exist yet
- Planned structure from `docs/HANDOFF_DATA_DAEMON.md`:

**Planned Naming:**
- `test_*.py` for all test files
- `conftest.py` for shared fixtures

**Planned Structure:**
```
tests/
  conftest.py                    # Shared fixtures, respx mocks
  unit/
    __init__.py
    test_models.py               # Pydantic model validation
    test_queries.py              # DB query functions
  integration/
    __init__.py
    conftest.py                  # testcontainers TimescaleDB fixture
    test_schema.py               # Schema migration verification
    test_upserts.py              # Upsert behavior
    test_price_inserts.py        # Bulk insert verification
  collector/
    __init__.py
    test_market_metadata.py      # Market metadata collector
    test_price_snapshots.py      # Price snapshot collector
    test_orderbook_snapshots.py  # Orderbook snapshot collector
    test_trade_listener.py       # WebSocket trade listener
    test_resolution_tracker.py   # Resolution tracker
    test_daemon.py               # Daemon lifecycle
```

## Test Structure

**Planned Suite Organization:**
```python
import pytest
import pytest_asyncio

@pytest.mark.asyncio
async def test_function_success_case():
    # arrange
    # act
    # assert
    pass

@pytest.mark.asyncio
async def test_function_error_case():
    # arrange
    # act & assert
    pass
```

**Planned Patterns:**
- pytest-asyncio for all async tests
- respx for HTTP mocking (planned dependency)
- testcontainers for integration tests with real TimescaleDB
- Factory functions for test data creation

## Mocking

**Planned Framework:**
- respx >=0.21.0 - HTTP request mocking (not yet installed)
- pytest fixtures for shared setup
- unittest.mock for general mocking

**Planned Patterns:**
```python
import respx
import httpx

@respx.mock
async def test_gamma_api_call():
    respx.get("https://gamma-api.polymarket.com/events").mock(
        return_value=httpx.Response(200, json={"data": [...]})
    )
    # test code using mocked API
```

**What to Mock:**
- Polymarket API calls (Gamma, CLOB, Data)
- WebSocket connections
- File system (circuit breaker state persistence)
- Time/sleep (for retry testing)

**What NOT to Mock:**
- Pydantic model validation
- Dataclass creation
- Pure computation (arbitrage math)

## Fixtures and Factories

**Planned Test Data:**
```python
# Factory functions for test data
def create_test_market(overrides=None):
    defaults = {
        "market_id": "test-market-1",
        "question": "Test market?",
        "yes_price": 0.55,
        "no_price": 0.45,
    }
    if overrides:
        defaults.update(overrides)
    return Market(**defaults)
```

**Planned Location:**
- `tests/conftest.py` for shared fixtures
- Factory functions in test files near usage
- testcontainers fixtures in `tests/integration/conftest.py`

## Coverage

**Requirements:**
- No coverage target set
- No coverage configuration

**Planned Configuration:**
- pytest-cov (not yet in requirements)

## Test Types

**Unit Tests (planned):**
- Test Pydantic models, dataclass creation, pure functions
- Mock all external dependencies
- Fast execution

**Integration Tests (planned):**
- Test database operations against real TimescaleDB (via testcontainers)
- Test schema migrations
- Test upsert behavior and bulk inserts

**Collector Tests (planned):**
- Test each collector with mocked APIs (respx)
- Verify data parsing and storage
- Test WebSocket reconnection logic

**E2E Tests:**
- Not planned yet

## Current State

**No tests exist.** Testing infrastructure is planned in `docs/HANDOFF_DATA_DAEMON.md` with detailed test-first implementation order. The handoff document specifies TDD approach: write failing test → implement → verify.

---

*Testing analysis: 2026-02-16*
*Update when test patterns change*
