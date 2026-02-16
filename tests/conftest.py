"""Shared pytest fixtures for the polymarket-stat-arb test suite.

Provides:
- Windows event loop policy fixture (session-scoped)
- TimescaleDB testcontainer fixture (session-scoped)
- asyncpg pool fixture connected to the test container (function-scoped)
- Database cleanup fixture for test isolation (function-scoped)
"""

import asyncio
import sys
from typing import AsyncGenerator, Generator

import pytest

# Guard testcontainers import so non-integration tests don't fail
# when Docker is unavailable.
try:
    from testcontainers.postgres import PostgresContainer

    _HAS_TESTCONTAINERS = True
except ImportError:
    _HAS_TESTCONTAINERS = False

import asyncpg


# ---------------------------------------------------------------------------
# Event loop policy — MUST run before any async fixtures on Windows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _set_event_loop_policy() -> Generator[None, None, None]:
    """Use WindowsSelectorEventLoopPolicy on Windows for asyncpg compat."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    yield
    # Restore default policy after the session
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(None)


# ---------------------------------------------------------------------------
# TimescaleDB container (session-scoped — expensive to start)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def timescaledb_container() -> Generator:
    """Start a TimescaleDB container for the test session.

    Requires Docker to be running. Tests that use this fixture will be
    skipped automatically if testcontainers is not installed.
    """
    if not _HAS_TESTCONTAINERS:
        pytest.skip("testcontainers not installed or Docker unavailable")

    with PostgresContainer(
        image="timescale/timescaledb:latest-pg17",
        username="test",
        password="test",
        dbname="testdb",
    ) as container:
        yield container


# ---------------------------------------------------------------------------
# asyncpg pool (function-scoped for isolation)
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_pool(
    timescaledb_container,
) -> AsyncGenerator[asyncpg.Pool, None]:
    """Create a fresh asyncpg pool for each test, connected to the container.

    Enables the timescaledb extension on first connect and tears down the
    pool after the test completes.
    """
    host = timescaledb_container.get_container_host_ip()
    port = int(timescaledb_container.get_exposed_port(5432))

    pool = await asyncpg.create_pool(
        host=host,
        port=port,
        user="test",
        password="test",
        database="testdb",
        min_size=1,
        max_size=3,
    )

    # Ensure TimescaleDB extension is available
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    yield pool

    await pool.close()


# ---------------------------------------------------------------------------
# Database cleanup (function-scoped for isolation)
# ---------------------------------------------------------------------------

# Tables created by the application (expanded as schema evolves).
# schema_migrations is intentionally excluded to preserve migration state.
_APPLICATION_TABLES = [
    "price_snapshots",
    "orderbook_snapshots",
    "trades",
    "markets",
    "market_metadata",
]


@pytest.fixture
async def clean_db(db_pool: asyncpg.Pool) -> asyncpg.Pool:
    """Drop all known application tables for a clean slate.

    Returns the pool so tests can use it directly::

        async def test_something(clean_db):
            async with clean_db.acquire() as conn:
                ...
    """
    async with db_pool.acquire() as conn:
        for table in _APPLICATION_TABLES:
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

    return db_pool
