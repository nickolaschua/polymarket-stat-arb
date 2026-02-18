#!/usr/bin/env python3
"""Run database migrations standalone.

Used by deploy.sh to apply migrations after TimescaleDB is ready.
Initializes the asyncpg pool, runs all pending migrations, then closes.

Usage:
    python deploy/run-migrations.py
    # or from the project root with venv:
    venv/bin/python deploy/run-migrations.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path so `src` imports work
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.db.pool import get_pool, close_pool
from src.db.migrations.runner import run_migrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialize pool, run migrations, close pool."""
    logger.info("Connecting to database...")
    pool = await get_pool()

    migrations_dir = project_root / "src" / "db" / "migrations"
    logger.info("Running migrations from %s", migrations_dir)
    applied = await run_migrations(pool, migrations_dir)

    if applied:
        logger.info("Applied %d migration(s): %s", len(applied), applied)
    else:
        logger.info("No new migrations to apply")

    await close_pool()
    logger.info("Done")


if __name__ == "__main__":
    asyncio.run(main())
