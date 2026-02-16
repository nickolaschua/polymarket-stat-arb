"""Tests for the SQL migration runner.

TDD test cases for src.db.migrations.runner.run_migrations().
Tests use a real TimescaleDB container via testcontainers (see conftest.py).
"""

from pathlib import Path
from textwrap import dedent

import asyncpg
import pytest

from src.db.migrations.runner import run_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def fresh_pool(db_pool: asyncpg.Pool) -> asyncpg.Pool:
    """Yield a pool with schema_migrations dropped for a clean migration test.

    The db_pool fixture from conftest.py already enables the timescaledb
    extension.  We drop schema_migrations so each test starts from scratch
    regarding migration tracking.
    """
    async with db_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS schema_migrations CASCADE;")
    return db_pool


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    """Create a temporary migrations directory with 001_extensions.sql."""
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "001_extensions.sql").write_text(
        "CREATE EXTENSION IF NOT EXISTS timescaledb;\n"
    )
    return d


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestRunMigrations:
    """Test suite for run_migrations()."""

    async def test_empty_database_applies_first_migration(
        self, fresh_pool: asyncpg.Pool, migrations_dir: Path
    ) -> None:
        """1. Empty database -> creates schema_migrations + applies 001 -> returns ['001_extensions.sql']."""
        applied = await run_migrations(fresh_pool, migrations_dir)

        assert applied == ["001_extensions.sql"]

        # schema_migrations table should exist and contain one row
        async with fresh_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT version, filename FROM schema_migrations WHERE version = 1"
            )
            assert row is not None
            assert row["version"] == 1
            assert row["filename"] == "001_extensions.sql"

    async def test_idempotent_no_new_migrations(
        self, fresh_pool: asyncpg.Pool, migrations_dir: Path
    ) -> None:
        """2. Run again with same files -> returns [] (no new migrations)."""
        await run_migrations(fresh_pool, migrations_dir)
        applied = await run_migrations(fresh_pool, migrations_dir)

        assert applied == []

    async def test_incremental_applies_only_new(
        self, fresh_pool: asyncpg.Pool, migrations_dir: Path
    ) -> None:
        """3. Add 002_test.sql -> only applies 002, not 001 -> returns ['002_test.sql']."""
        # First run: apply 001
        await run_migrations(fresh_pool, migrations_dir)

        # Add a second migration file
        (migrations_dir / "002_test.sql").write_text(
            dedent("""\
                CREATE TABLE IF NOT EXISTS _migration_test (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL
                );
            """)
        )

        applied = await run_migrations(fresh_pool, migrations_dir)

        assert applied == ["002_test.sql"]

        # Verify the table was actually created
        async with fresh_pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '_migration_test')"
            )
            assert exists is True

    async def test_schema_migrations_records_all_applied(
        self, fresh_pool: asyncpg.Pool, migrations_dir: Path
    ) -> None:
        """4. Verify schema_migrations has correct version/filename for all applied."""
        # Add a second migration
        (migrations_dir / "002_test.sql").write_text(
            dedent("""\
                CREATE TABLE IF NOT EXISTS _migration_test (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL
                );
            """)
        )

        await run_migrations(fresh_pool, migrations_dir)

        async with fresh_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT version, filename FROM schema_migrations ORDER BY version"
            )
            assert len(rows) == 2
            assert rows[0]["version"] == 1
            assert rows[0]["filename"] == "001_extensions.sql"
            assert rows[1]["version"] == 2
            assert rows[1]["filename"] == "002_test.sql"

            # applied_at should be set (not null)
            ts_row = await conn.fetchrow(
                "SELECT applied_at FROM schema_migrations WHERE version = 1"
            )
            assert ts_row["applied_at"] is not None

    async def test_timescaledb_extension_active_after_001(
        self, fresh_pool: asyncpg.Pool, migrations_dir: Path
    ) -> None:
        """5. Verify TimescaleDB extension is active after 001 runs."""
        await run_migrations(fresh_pool, migrations_dir)

        async with fresh_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT extname FROM pg_extension WHERE extname = 'timescaledb'"
            )
            assert row is not None
            assert row["extname"] == "timescaledb"

    async def test_syntax_error_rolls_back_and_raises(
        self, fresh_pool: asyncpg.Pool, migrations_dir: Path
    ) -> None:
        """6. Migration with syntax error -> rolls back, NOT recorded, raises exception."""
        # Apply 001 successfully first
        await run_migrations(fresh_pool, migrations_dir)

        # Add a broken migration
        (migrations_dir / "002_broken.sql").write_text(
            "THIS IS NOT VALID SQL AT ALL;\n"
        )

        with pytest.raises(Exception):
            await run_migrations(fresh_pool, migrations_dir)

        # Verify the broken migration was NOT recorded
        async with fresh_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT version FROM schema_migrations WHERE version = 2"
            )
            assert row is None

            # Only migration 001 should exist
            count = await conn.fetchval(
                "SELECT count(*) FROM schema_migrations"
            )
            assert count == 1
