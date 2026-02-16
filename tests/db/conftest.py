"""Shared fixtures for database integration tests.

Provides a ``migrated_pool`` fixture that runs all SQL migrations
against the test container before each test, ensuring the full schema
is available.
"""

from pathlib import Path

import asyncpg
import pytest

from src.db.migrations.runner import run_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "src" / "db" / "migrations"


@pytest.fixture
async def migrated_pool(db_pool: asyncpg.Pool) -> asyncpg.Pool:
    """Run all migrations and return the pool with full schema.

    Drops all application objects first to ensure a clean slate, then
    applies every migration from 001 through 008.  Data tables are
    truncated so each test starts with an empty dataset.
    """
    async with db_pool.acquire() as conn:
        # Clean slate: drop everything in reverse dependency order
        await conn.execute("DROP TABLE IF EXISTS schema_migrations CASCADE;")

        # Drop continuous aggregates first (they depend on hypertables)
        await conn.execute(
            "DROP MATERIALIZED VIEW IF EXISTS price_candles_1h CASCADE;"
        )
        await conn.execute(
            "DROP MATERIALIZED VIEW IF EXISTS trade_volume_1h CASCADE;"
        )

        # Drop tables
        for table in [
            "price_snapshots",
            "orderbook_snapshots",
            "trades",
            "markets",
            "resolutions",
        ]:
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")

    applied = await run_migrations(db_pool, MIGRATIONS_DIR)
    assert len(applied) == 8, f"Expected 8 migrations, got {len(applied)}: {applied}"

    return db_pool
