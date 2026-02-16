"""Resolution tracking query functions.

Provides UPSERT and read operations for the ``resolutions`` table,
plus a join query to find markets without resolutions.
All functions take an asyncpg pool as the first argument and return
Pydantic model instances.
"""

from typing import Optional

import asyncpg

from src.db.models import ResolutionRecord, record_to_model


async def upsert_resolution(pool: asyncpg.Pool, resolution_data: dict) -> None:
    """Insert a new resolution or update an existing one.

    Uses INSERT ... ON CONFLICT (condition_id) DO UPDATE to ensure
    idempotent ingestion.
    """
    await pool.execute(
        """
        INSERT INTO resolutions (
            condition_id, outcome, winner_token_id,
            resolved_at, payout_price, detection_method
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (condition_id) DO UPDATE SET
            outcome = EXCLUDED.outcome,
            winner_token_id = EXCLUDED.winner_token_id,
            resolved_at = EXCLUDED.resolved_at,
            payout_price = EXCLUDED.payout_price,
            detection_method = EXCLUDED.detection_method
        """,
        resolution_data["condition_id"],
        resolution_data.get("outcome"),
        resolution_data.get("winner_token_id"),
        resolution_data.get("resolved_at"),
        resolution_data.get("payout_price"),
        resolution_data.get("detection_method"),
    )


async def get_resolution(
    pool: asyncpg.Pool, condition_id: str
) -> Optional[ResolutionRecord]:
    """Fetch a single resolution by condition_id.

    Returns None if no resolution with the given condition_id exists.
    """
    row = await pool.fetchrow(
        "SELECT * FROM resolutions WHERE condition_id = $1",
        condition_id,
    )
    if row is None:
        return None
    return record_to_model(row, ResolutionRecord)


async def get_unresolved_markets(pool: asyncpg.Pool) -> list[str]:
    """Return condition_ids of closed markets that have no resolution record.

    Uses LEFT JOIN markets/resolutions WHERE r.condition_id IS NULL
    AND m.closed = true.
    """
    rows = await pool.fetch(
        """
        SELECT m.condition_id
        FROM markets m
        LEFT JOIN resolutions r ON m.condition_id = r.condition_id
        WHERE r.condition_id IS NULL
          AND m.closed = true
        """
    )
    return [row["condition_id"] for row in rows]
