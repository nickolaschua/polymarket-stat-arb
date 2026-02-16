"""Price snapshot query functions.

Provides bulk insert via COPY protocol and read operations for the
``price_snapshots`` hypertable.  All functions take an asyncpg pool as
the first argument.

The COPY protocol is used for inserts because price_snapshots is the
highest-volume table (~8,000 rows every 60 seconds).  COPY is 10-100x
faster than executemany for bulk inserts.
"""

from datetime import datetime

import asyncpg

from src.db.models import PriceSnapshot, record_to_model


async def insert_price_snapshots(
    pool: asyncpg.Pool, snapshots: list[tuple]
) -> int:
    """Bulk-insert price snapshots using the COPY protocol.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    snapshots:
        List of tuples, each ``(ts, token_id, price, volume_24h)``.
        ``ts`` must be a timezone-aware datetime.

    Returns
    -------
    int
        Number of records inserted.
    """
    if not snapshots:
        return 0

    await pool.copy_records_to_table(
        "price_snapshots",
        records=snapshots,
        columns=["ts", "token_id", "price", "volume_24h"],
    )
    return len(snapshots)


async def get_latest_prices(
    pool: asyncpg.Pool, token_ids: list[str]
) -> list[PriceSnapshot]:
    """Return the most recent price snapshot for each requested token_id.

    Uses ``DISTINCT ON (token_id) ORDER BY token_id, ts DESC`` to
    efficiently select only the latest row per token.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_ids:
        List of token IDs to look up.

    Returns
    -------
    list[PriceSnapshot]
        One PriceSnapshot per token_id found (may be fewer than requested
        if some token_ids have no data).
    """
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (token_id)
            ts, token_id, price, volume_24h
        FROM price_snapshots
        WHERE token_id = ANY($1::text[])
        ORDER BY token_id, ts DESC
        """,
        token_ids,
    )
    return [record_to_model(row, PriceSnapshot) for row in rows]


async def get_price_history(
    pool: asyncpg.Pool,
    token_id: str,
    start: datetime,
    end: datetime,
    limit: int = 1000,
) -> list[PriceSnapshot]:
    """Return price snapshots for a token within a time range.

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
        Maximum number of rows to return (default 1000).

    Returns
    -------
    list[PriceSnapshot]
        Snapshots ordered by ``ts DESC`` (most recent first).
    """
    rows = await pool.fetch(
        """
        SELECT ts, token_id, price, volume_24h
        FROM price_snapshots
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
    return [record_to_model(row, PriceSnapshot) for row in rows]


async def get_price_count(pool: asyncpg.Pool) -> int:
    """Return the total number of rows in price_snapshots.

    Useful for monitoring and health checks.
    """
    row = await pool.fetchrow("SELECT count(*) AS cnt FROM price_snapshots")
    return row["cnt"]
