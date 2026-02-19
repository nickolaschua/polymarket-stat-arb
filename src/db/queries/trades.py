"""Trade event query functions.

Provides bulk insert via COPY protocol and read operations for the
``trades`` hypertable.  All functions take an asyncpg pool as the first
argument.

Trades are high-volume events from the WebSocket feed.  COPY protocol
is used for batch inserts (trade_buffer_size=1000 from CollectorConfig).
If a batch contains duplicate trade_ids that already exist in the table,
the COPY will fail due to the unique index; in that case, we fall back
to INSERT ... ON CONFLICT DO NOTHING.
"""

from typing import Optional

import asyncpg

from src.db.models import TradeRecord, record_to_model


async def insert_trades(pool: asyncpg.Pool, trades: list[tuple]) -> int:
    """Bulk-insert trade records using the COPY protocol with duplicate fallback.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    trades:
        List of tuples, each ``(ts, token_id, side, price, size, trade_id)``.
        ``ts`` must be a timezone-aware datetime.

    Returns
    -------
    int
        Number of records inserted (may be less than len(trades) if
        duplicates were skipped via the fallback path).
    """
    if not trades:
        return 0

    try:
        await pool.copy_records_to_table(
            "trades",
            records=trades,
            columns=["ts", "token_id", "side", "price", "size", "trade_id"],
        )
        return len(trades)
    except asyncpg.UniqueViolationError:
        # COPY failed due to duplicate trade_id — fall back to
        # individual inserts with ON CONFLICT DO NOTHING.
        await pool.executemany(
            """
            INSERT INTO trades (ts, token_id, side, price, size, trade_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (trade_id, ts) WHERE trade_id IS NOT NULL
            DO NOTHING
            """,
            trades,
        )
        # Return batch length — the caller cares about "records processed".
        # (Previous code counted the entire table, which is wrong.)
        return len(trades)


async def get_recent_trades(
    pool: asyncpg.Pool, token_id: str, limit: int = 100
) -> list[TradeRecord]:
    """Return the most recent trades for a token, ordered by ts DESC.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to query.
    limit:
        Maximum number of trades to return (default 100).

    Returns
    -------
    list[TradeRecord]
        Trades ordered by ``ts DESC`` (most recent first).
    """
    rows = await pool.fetch(
        """
        SELECT ts, token_id, side, price, size, trade_id
        FROM trades
        WHERE token_id = $1
        ORDER BY ts DESC
        LIMIT $2
        """,
        token_id,
        limit,
    )
    return [record_to_model(row, TradeRecord) for row in rows]


async def get_trade_count(
    pool: asyncpg.Pool, token_id: Optional[str] = None
) -> int:
    """Return the number of trades, optionally filtered by token_id.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        If provided, count only trades for this token.
        If None, count all trades.

    Returns
    -------
    int
        Number of matching trade records.
    """
    if token_id is None:
        row = await pool.fetchrow("SELECT count(*) AS cnt FROM trades")
    else:
        row = await pool.fetchrow(
            "SELECT count(*) AS cnt FROM trades WHERE token_id = $1",
            token_id,
        )
    return row["cnt"]
