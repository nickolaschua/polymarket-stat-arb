"""Market metadata query functions.

Provides UPSERT and read operations for the ``markets`` table.
All functions take an asyncpg pool as the first argument and return
Pydantic model instances.
"""

from typing import Optional

import asyncpg

from src.db.models import MarketRecord


async def upsert_market(pool: asyncpg.Pool, market_data: dict) -> None:
    """Insert a new market or update an existing one.

    Uses INSERT ... ON CONFLICT (condition_id) DO UPDATE to ensure
    idempotent ingestion.
    """
    raise NotImplementedError


async def upsert_markets(pool: asyncpg.Pool, markets: list[dict]) -> None:
    """Batch upsert multiple markets.

    Loops over the list calling upsert_market for each entry.
    """
    raise NotImplementedError


async def get_market(
    pool: asyncpg.Pool, condition_id: str
) -> Optional[MarketRecord]:
    """Fetch a single market by condition_id.

    Returns None if no market with the given condition_id exists.
    """
    raise NotImplementedError


async def get_active_markets(pool: asyncpg.Pool) -> list[MarketRecord]:
    """Fetch all markets where active = true, ordered by created_at DESC."""
    raise NotImplementedError


async def get_markets_by_ids(
    pool: asyncpg.Pool, condition_ids: list[str]
) -> list[MarketRecord]:
    """Fetch markets matching any of the given condition_ids.

    Uses ANY($1::text[]) for the array parameter.
    """
    raise NotImplementedError
