"""asyncpg connection pool singleton for TimescaleDB.

Provides a module-level pool singleton following the same pattern as
``get_config()`` in ``src.config``.  The pool is created lazily on first
access and can be explicitly torn down with ``close_pool()``.

Usage::

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT 1")
"""

import logging
from typing import Optional

import asyncpg

from src.config import get_config

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None
_pool_closed: bool = True


async def get_pool() -> asyncpg.Pool:
    """Return the module-level asyncpg connection pool, creating it if needed.

    Reads DSN and pool tuning parameters from ``get_config().database``.
    The pool is created once and reused for the lifetime of the process
    (or until ``close_pool()`` is called).
    """
    global _pool, _pool_closed

    if _pool is not None and not _pool_closed:
        return _pool

    db = get_config().database

    logger.info("Creating asyncpg connection pool (min=%d, max=%d)", db.min_pool_size, db.max_pool_size)

    _pool = await asyncpg.create_pool(
        dsn=db.url,
        min_size=db.min_pool_size,
        max_size=db.max_pool_size,
        max_inactive_connection_lifetime=db.max_inactive_connection_lifetime,
        command_timeout=db.command_timeout,
    )
    _pool_closed = False

    logger.info("asyncpg connection pool created successfully")
    return _pool


async def close_pool() -> None:
    """Close the module-level connection pool and release all connections.

    Safe to call when the pool is already closed or was never created.
    """
    global _pool, _pool_closed

    if _pool is not None and not _pool_closed:
        logger.info("Closing asyncpg connection pool")
        try:
            await _pool.close()
        except Exception:
            logger.warning("Error closing asyncpg pool", exc_info=True)
        _pool_closed = True

    _pool = None


async def init_pool() -> asyncpg.Pool:
    """Explicitly initialise the connection pool.

    This is a convenience wrapper around ``get_pool()`` intended for use in
    application startup sequences where you want to fail-fast if the database
    is unreachable.
    """
    return await get_pool()
