"""Orderbook snapshot query functions.

Provides bulk insert and read operations for the ``orderbook_snapshots``
hypertable.  All functions take an asyncpg pool as the first argument.

Orderbook bids/asks are stored as JSONB columns.  asyncpg does not
natively encode Python dicts as JSONB for the COPY protocol, so we use
``executemany`` for inserts instead.  Orderbook volume is much lower
than price snapshots (~8K tokens every 5 min vs 60s), so the
performance trade-off is acceptable.

For reads, we set a JSONB type codec on the connection so that asyncpg
automatically decodes JSONB strings to Python dicts.
"""

import json
from datetime import datetime
from typing import Optional

import asyncpg

from src.db.models import OrderbookSnapshot, record_to_model


async def _set_jsonb_codec(conn: asyncpg.Connection) -> None:
    """Register a JSONB codec on a connection for automatic dict decoding."""
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def insert_orderbook_snapshots(
    pool: asyncpg.Pool, snapshots: list[tuple]
) -> int:
    """Batch-insert orderbook snapshots.

    Uses ``executemany`` with explicit JSONB casting because asyncpg's
    COPY protocol does not natively handle Python dict -> JSONB encoding.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    snapshots:
        List of tuples, each ``(ts, token_id, bids, asks, spread, midpoint)``.
        ``bids`` and ``asks`` should be Python dicts (or None) — they are
        serialised to JSON strings for the JSONB cast.

    Returns
    -------
    int
        Number of records inserted.
    """
    if not snapshots:
        return 0

    # Convert dicts to JSON strings for the JSONB cast
    prepared = [
        (ts, token_id, json.dumps(bids) if bids is not None else None,
         json.dumps(asks) if asks is not None else None, spread, midpoint)
        for ts, token_id, bids, asks, spread, midpoint in snapshots
    ]

    await pool.executemany(
        """
        INSERT INTO orderbook_snapshots (ts, token_id, bids, asks, spread, midpoint)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
        """,
        prepared,
    )
    return len(snapshots)


async def get_latest_orderbook(
    pool: asyncpg.Pool, token_id: str
) -> Optional[OrderbookSnapshot]:
    """Return the most recent orderbook snapshot for a token.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to query.

    Returns
    -------
    OrderbookSnapshot or None
        The latest snapshot, or None if no data exists for the token.
    """
    async with pool.acquire() as conn:
        await _set_jsonb_codec(conn)
        row = await conn.fetchrow(
            """
            SELECT ts, token_id, bids, asks, spread, midpoint
            FROM orderbook_snapshots
            WHERE token_id = $1
            ORDER BY ts DESC
            LIMIT 1
            """,
            token_id,
        )
    if row is None:
        return None
    return record_to_model(row, OrderbookSnapshot)


async def get_orderbook_history(
    pool: asyncpg.Pool,
    token_id: str,
    start: datetime,
    end: datetime,
    limit: int = 100,
) -> list[OrderbookSnapshot]:
    """Return orderbook snapshots for a token within a time range.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to query.
    start:
        Inclusive lower bound (timezone-aware datetime).
    end:
        Inclusive upper bound (timezone-aware datetime).
    limit:
        Maximum number of rows to return (default 100).

    Returns
    -------
    list[OrderbookSnapshot]
        Snapshots ordered by ``ts DESC`` (most recent first).
    """
    async with pool.acquire() as conn:
        await _set_jsonb_codec(conn)
        rows = await conn.fetch(
            """
            SELECT ts, token_id, bids, asks, spread, midpoint
            FROM orderbook_snapshots
            WHERE token_id = $1
              AND ts >= $2
              AND ts <= $3
            ORDER BY ts DESC
            LIMIT $4
            """,
            token_id,
            start,
            end,
            limit,
        )
    return [record_to_model(row, OrderbookSnapshot) for row in rows]
