"""Market metadata query functions.

Provides UPSERT and read operations for the ``markets`` table.
All functions take an asyncpg pool as the first argument and return
Pydantic model instances.
"""

from typing import Optional

import asyncpg

from src.db.models import MarketRecord, record_to_model


async def upsert_market(pool: asyncpg.Pool, market_data: dict) -> None:
    """Insert a new market or update an existing one.

    Uses INSERT ... ON CONFLICT (condition_id) DO UPDATE to ensure
    idempotent ingestion.
    """
    await pool.execute(
        """
        INSERT INTO markets (
            condition_id, question, slug, market_type,
            outcomes, clob_token_ids, active, closed, end_date_iso
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (condition_id) DO UPDATE SET
            question = EXCLUDED.question,
            slug = EXCLUDED.slug,
            market_type = EXCLUDED.market_type,
            outcomes = EXCLUDED.outcomes,
            clob_token_ids = EXCLUDED.clob_token_ids,
            active = EXCLUDED.active,
            closed = EXCLUDED.closed,
            end_date_iso = EXCLUDED.end_date_iso,
            updated_at = NOW()
        """,
        market_data["condition_id"],
        market_data["question"],
        market_data.get("slug"),
        market_data.get("market_type"),
        market_data.get("outcomes", []),
        market_data.get("clob_token_ids", []),
        market_data.get("active", True),
        market_data.get("closed", False),
        market_data.get("end_date_iso"),
    )


async def upsert_markets(pool: asyncpg.Pool, markets: list[dict]) -> None:
    """Batch upsert multiple markets.

    Loops over the list calling upsert_market for each entry.
    Not performance-critical at 5-minute intervals for ~8K markets.
    """
    for market_data in markets:
        await upsert_market(pool, market_data)


async def get_market(
    pool: asyncpg.Pool, condition_id: str
) -> Optional[MarketRecord]:
    """Fetch a single market by condition_id.

    Returns None if no market with the given condition_id exists.
    """
    row = await pool.fetchrow(
        "SELECT * FROM markets WHERE condition_id = $1",
        condition_id,
    )
    if row is None:
        return None
    return record_to_model(row, MarketRecord)


async def get_active_markets(pool: asyncpg.Pool) -> list[MarketRecord]:
    """Fetch all markets where active = true, ordered by created_at DESC."""
    rows = await pool.fetch(
        "SELECT * FROM markets WHERE active = true ORDER BY created_at DESC"
    )
    return [record_to_model(row, MarketRecord) for row in rows]


async def get_markets_by_ids(
    pool: asyncpg.Pool, condition_ids: list[str]
) -> list[MarketRecord]:
    """Fetch markets matching any of the given condition_ids.

    Uses ANY($1::text[]) for the array parameter.
    """
    rows = await pool.fetch(
        "SELECT * FROM markets WHERE condition_id = ANY($1::text[])",
        condition_ids,
    )
    return [record_to_model(row, MarketRecord) for row in rows]
