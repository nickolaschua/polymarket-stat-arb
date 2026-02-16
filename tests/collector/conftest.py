"""Shared fixtures for collector integration tests.

Provides:
- ``mock_client``: PolymarketClient with default config (respx intercepts HTTP).
- ``migrated_pool``: asyncpg pool with full schema applied (re-used from db tests).
"""

import asyncio
from pathlib import Path

import asyncpg
import pytest

from src.db.migrations.runner import run_migrations
from src.utils.client import PolymarketClient

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "src" / "db" / "migrations"


async def _drop_with_retry(
    conn: asyncpg.Connection, sql: str, max_retries: int = 3, delay: float = 0.5
) -> None:
    """Execute a DROP statement with retries for TimescaleDB deadlocks."""
    for attempt in range(max_retries):
        try:
            await conn.execute(sql)
            return
        except asyncpg.DeadlockDetectedError:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(delay * (attempt + 1))


@pytest.fixture
async def migrated_pool(db_pool: asyncpg.Pool) -> asyncpg.Pool:
    """Run all migrations and return the pool with full schema.

    Mirrors the fixture in tests/db/conftest.py so that collector
    integration tests have access to the same migrated database.
    """
    async with db_pool.acquire() as conn:
        await _drop_with_retry(
            conn, "DROP TABLE IF EXISTS schema_migrations CASCADE;"
        )
        await _drop_with_retry(
            conn,
            "DROP MATERIALIZED VIEW IF EXISTS price_candles_1h CASCADE;",
        )
        await _drop_with_retry(
            conn,
            "DROP MATERIALIZED VIEW IF EXISTS trade_volume_1h CASCADE;",
        )
        for table in [
            "price_snapshots",
            "orderbook_snapshots",
            "trades",
            "markets",
            "resolutions",
        ]:
            await _drop_with_retry(
                conn, f"DROP TABLE IF EXISTS {table} CASCADE;"
            )

    applied = await run_migrations(db_pool, MIGRATIONS_DIR)
    assert len(applied) == 8, f"Expected 8 migrations, got {len(applied)}: {applied}"

    return db_pool


@pytest.fixture
def mock_client() -> PolymarketClient:
    """Create a PolymarketClient with default config for testing.

    Tests that need to mock HTTP responses should use ``@respx.mock``
    or ``respx.mock()`` context manager — respx intercepts the
    underlying ``httpx.AsyncClient`` used by the client.
    """
    return PolymarketClient()
