"""Resolution tracking query functions.

Provides UPSERT and read operations for the ``resolutions`` table,
plus a join query to find markets without resolutions.
All functions take an asyncpg pool as the first argument and return
Pydantic model instances.
"""

from typing import Optional

import asyncpg

from src.db.models import ResolutionRecord


async def upsert_resolution(pool: asyncpg.Pool, resolution_data: dict) -> None:
    """Insert a new resolution or update an existing one.

    Uses INSERT ... ON CONFLICT (condition_id) DO UPDATE to ensure
    idempotent ingestion.
    """
    raise NotImplementedError


async def get_resolution(
    pool: asyncpg.Pool, condition_id: str
) -> Optional[ResolutionRecord]:
    """Fetch a single resolution by condition_id.

    Returns None if no resolution with the given condition_id exists.
    """
    raise NotImplementedError


async def get_unresolved_markets(pool: asyncpg.Pool) -> list[str]:
    """Return condition_ids of closed markets that have no resolution record.

    Uses LEFT JOIN markets/resolutions WHERE r.condition_id IS NULL
    AND m.closed = true.
    """
    raise NotImplementedError
