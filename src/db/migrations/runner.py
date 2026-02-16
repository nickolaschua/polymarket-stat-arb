"""Simple SQL migration runner for numbered .sql files.

Applies migrations in numeric order and tracks them in a
``schema_migrations`` table.  Each migration runs in its own transaction;
the tracking INSERT is executed outside the DDL transaction to avoid
issues with extension creation and other DDL that auto-commits.

Usage::

    applied = await run_migrations(pool, Path("src/db/migrations"))
"""

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)


async def run_migrations(
    pool: asyncpg.Pool,
    migrations_dir: Path,
) -> list[str]:
    """Apply pending SQL migrations in numeric-prefix order.

    Parameters
    ----------
    pool:
        An asyncpg connection pool.
    migrations_dir:
        Directory containing numbered ``.sql`` files (e.g.
        ``001_extensions.sql``).

    Returns
    -------
    list[str]
        Filenames of the migrations that were applied during this call.
        An empty list means everything was already up-to-date.
    """
    applied: list[str] = []

    async with pool.acquire() as conn:
        # Ensure the tracking table exists
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INT          PRIMARY KEY,
                filename    TEXT         NOT NULL,
                applied_at  TIMESTAMPTZ  DEFAULT NOW()
            )
            """
        )

        # Fetch the set of already-applied version numbers
        rows = await conn.fetch("SELECT version FROM schema_migrations")
        already_applied = {r["version"] for r in rows}

        # Collect and sort .sql files by numeric prefix
        sql_files = sorted(migrations_dir.glob("*.sql"))

        for sql_file in sql_files:
            version = int(sql_file.stem.split("_")[0])

            if version in already_applied:
                continue

            sql_text = sql_file.read_text()
            logger.info("Applying migration %s (version %d)", sql_file.name, version)

            # Run the DDL in its own transaction
            async with conn.transaction():
                await conn.execute(sql_text)

            # Record the migration OUTSIDE the DDL transaction
            await conn.execute(
                "INSERT INTO schema_migrations (version, filename) VALUES ($1, $2)",
                version,
                sql_file.name,
            )

            applied.append(sql_file.name)
            logger.info("Applied migration %s", sql_file.name)

    return applied
