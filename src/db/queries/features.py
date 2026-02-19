"""Feature query functions for statistical analysis.

Computes market features directly in SQL using TimescaleDB window functions
and aggregations.  All functions return None or empty containers on error
rather than raising, so callers can safely aggregate results.
"""

import logging
import re
from datetime import datetime, timedelta

import asyncpg

logger = logging.getLogger(__name__)


_INTERVAL_RE = re.compile(r"^(\d+)\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)$", re.I)
_INTERVAL_UNITS: dict[str, str] = {
    "m": "minutes", "min": "minutes", "minute": "minutes", "minutes": "minutes",
    "h": "hours", "hr": "hours", "hour": "hours", "hours": "hours",
    "d": "days", "day": "days", "days": "days",
}


def _parse_interval(interval_str: str) -> timedelta:
    """Convert a short interval string like ``'1h'`` or ``'15m'`` to timedelta.

    Parameters
    ----------
    interval_str:
        Human-readable interval (e.g. ``'1h'``, ``'15m'``, ``'1d'``).

    Returns
    -------
    timedelta
        Equivalent timedelta.

    Raises
    ------
    ValueError
        If the string cannot be parsed.
    """
    m = _INTERVAL_RE.match(interval_str.strip())
    if not m:
        raise ValueError(f"Cannot parse interval string: {interval_str!r}")
    value = int(m.group(1))
    unit = _INTERVAL_UNITS[m.group(2).lower()]
    return timedelta(**{unit: value})


async def get_price_returns(
    pool: asyncpg.Pool,
    token_id: str,
    interval: str = "1h",
    lookback_hours: int = 24,
) -> list[tuple[datetime, float]]:
    """Compute percentage price returns using LAG() over price_snapshots.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to compute returns for.
    interval:
        Time bucket size for resampling (e.g. ``'1h'``, ``'15m'``).
        Passed directly to ``time_bucket``.
    lookback_hours:
        How many hours of history to include.

    Returns
    -------
    list[tuple[datetime, float]]
        List of ``(bucket_ts, return_pct)`` tuples ordered oldest-first.
        Returns empty list on error or no data.
    """
    bucket_td = _parse_interval(interval)
    try:
        rows = await pool.fetch(
            """
            WITH latest AS (
                SELECT MAX(ts) AS max_ts FROM price_snapshots WHERE token_id = $2
            ),
            bucketed AS (
                SELECT
                    time_bucket($1, ts) AS bucket,
                    last(price, ts) AS price
                FROM price_snapshots, latest
                WHERE token_id = $2
                  AND ts >= latest.max_ts - ($3 || ' hours')::interval
                GROUP BY bucket
                ORDER BY bucket
            )
            SELECT
                bucket,
                (price - LAG(price) OVER (ORDER BY bucket))
                    / NULLIF(LAG(price) OVER (ORDER BY bucket), 0) * 100.0
                    AS return_pct
            FROM bucketed
            """,
            bucket_td,
            token_id,
            str(lookback_hours),
        )
        return [
            (row["bucket"], row["return_pct"])
            for row in rows
            if row["return_pct"] is not None
        ]
    except Exception:
        logger.warning("get_price_returns failed for token_id=%s", token_id, exc_info=True)
        return []


async def get_rolling_volatility(
    pool: asyncpg.Pool,
    token_id: str,
    window_hours: int = 24,
) -> float | None:
    """Compute annualised-style rolling volatility of 1-minute returns.

    Standard deviation of per-minute price returns over the window.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to compute volatility for.
    window_hours:
        Look-back window in hours.

    Returns
    -------
    float or None
        Standard deviation of 1-minute returns as a percentage, or None
        if there is insufficient data or an error occurs.
    """
    try:
        row = await pool.fetchrow(
            """
            WITH latest AS (
                SELECT MAX(ts) AS max_ts
                FROM price_snapshots
                WHERE token_id = $1
            ),
            minute_prices AS (
                SELECT
                    time_bucket('1 minute', ts) AS bucket,
                    last(price, ts) AS price
                FROM price_snapshots, latest
                WHERE token_id = $1
                  AND ts >= latest.max_ts - ($2 || ' hours')::interval
                GROUP BY bucket
                ORDER BY bucket
            ),
            returns AS (
                SELECT
                    (price - LAG(price) OVER (ORDER BY bucket))
                        / NULLIF(LAG(price) OVER (ORDER BY bucket), 0) * 100.0
                        AS return_pct
                FROM minute_prices
            )
            SELECT stddev(return_pct) AS volatility
            FROM returns
            WHERE return_pct IS NOT NULL
            """,
            token_id,
            str(window_hours),
        )
        if row is None:
            return None
        return row["volatility"]
    except Exception:
        logger.warning("get_rolling_volatility failed for token_id=%s", token_id, exc_info=True)
        return None


async def get_spread_history(
    pool: asyncpg.Pool,
    token_id: str,
    lookback_hours: int = 24,
) -> list[tuple[datetime, float | None, float | None]]:
    """Return spread and midpoint history from orderbook_snapshots.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to query.
    lookback_hours:
        How many hours of history to include.

    Returns
    -------
    list[tuple[datetime, float | None, float | None]]
        List of ``(ts, spread, midpoint)`` tuples ordered oldest-first.
        Returns empty list on error or no data.
    """
    try:
        rows = await pool.fetch(
            """
            WITH latest AS (
                SELECT MAX(ts) AS max_ts
                FROM orderbook_snapshots
                WHERE token_id = $1
            )
            SELECT os.ts, os.spread, os.midpoint
            FROM orderbook_snapshots os, latest
            WHERE os.token_id = $1
              AND os.ts >= latest.max_ts - ($2 || ' hours')::interval
            ORDER BY os.ts ASC
            """,
            token_id,
            str(lookback_hours),
        )
        return [(row["ts"], row["spread"], row["midpoint"]) for row in rows]
    except Exception:
        logger.warning("get_spread_history failed for token_id=%s", token_id, exc_info=True)
        return []


async def get_orderbook_imbalance(
    pool: asyncpg.Pool,
    token_id: str,
) -> float | None:
    """Compute order-book imbalance from the most recent snapshot.

    Imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume).
    Positive values indicate more buying pressure; negative indicate selling.

    Bids and asks are stored as JSONB arrays of ``[price, size]`` pairs.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to query.

    Returns
    -------
    float or None
        Imbalance in [-1, 1], or None if no data or total volume is zero.
    """
    try:
        import json

        async with pool.acquire() as conn:
            await conn.set_type_codec(
                "jsonb",
                encoder=json.dumps,
                decoder=json.loads,
                schema="pg_catalog",
            )
            row = await conn.fetchrow(
                """
                SELECT bids, asks
                FROM orderbook_snapshots
                WHERE token_id = $1
                ORDER BY ts DESC
                LIMIT 1
                """,
                token_id,
            )

        if row is None:
            return None

        bids = row["bids"] or []
        asks = row["asks"] or []

        bid_vol = sum(float(entry[1]) for entry in bids if len(entry) >= 2)
        ask_vol = sum(float(entry[1]) for entry in asks if len(entry) >= 2)
        total = bid_vol + ask_vol
        if total == 0:
            return None
        return (bid_vol - ask_vol) / total
    except Exception:
        logger.warning("get_orderbook_imbalance failed for token_id=%s", token_id, exc_info=True)
        return None


async def get_trade_volume_profile(
    pool: asyncpg.Pool,
    token_id: str,
    lookback_hours: int = 24,
) -> dict:
    """Compute buy/sell volume and trade count over a lookback window.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id:
        The token to query.
    lookback_hours:
        How many hours of history to include.

    Returns
    -------
    dict
        Keys: ``buy_volume`` (float), ``sell_volume`` (float),
        ``trade_count`` (int).  All default to 0 on error or no data.
    """
    default = {"buy_volume": 0.0, "sell_volume": 0.0, "trade_count": 0}
    try:
        row = await pool.fetchrow(
            """
            WITH latest AS (
                SELECT MAX(ts) AS max_ts FROM trades WHERE token_id = $1
            )
            SELECT
                COALESCE(SUM(CASE WHEN side = 'BUY'  THEN size ELSE 0 END), 0) AS buy_volume,
                COALESCE(SUM(CASE WHEN side = 'SELL' THEN size ELSE 0 END), 0) AS sell_volume,
                COUNT(*) AS trade_count
            FROM trades, latest
            WHERE token_id = $1
              AND ts >= latest.max_ts - ($2 || ' hours')::interval
            """,
            token_id,
            str(lookback_hours),
        )
        if row is None:
            return default
        return {
            "buy_volume": float(row["buy_volume"]),
            "sell_volume": float(row["sell_volume"]),
            "trade_count": int(row["trade_count"]),
        }
    except Exception:
        logger.warning("get_trade_volume_profile failed for token_id=%s", token_id, exc_info=True)
        return default


async def get_market_features(
    pool: asyncpg.Pool,
    condition_id: str,
) -> dict:
    """Fetch all computed features for a market (all token outcomes).

    Combines price returns, volatility, spread history, order-book
    imbalance, and trade volume profile for each token in the market.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    condition_id:
        The market's condition ID.

    Returns
    -------
    dict
        Keys are ``token_id`` strings; values are feature dicts with keys:
        ``price_returns``, ``volatility``, ``spread_history``,
        ``orderbook_imbalance``, ``volume_profile``.
        Returns empty dict if the market is not found or an error occurs.
    """
    try:
        row = await pool.fetchrow(
            "SELECT clob_token_ids FROM markets WHERE condition_id = $1",
            condition_id,
        )
        if row is None:
            return {}

        token_ids: list[str] = row["clob_token_ids"] or []
        result: dict = {}
        for token_id in token_ids:
            result[token_id] = {
                "price_returns": await get_price_returns(pool, token_id),
                "volatility": await get_rolling_volatility(pool, token_id),
                "spread_history": await get_spread_history(pool, token_id),
                "orderbook_imbalance": await get_orderbook_imbalance(pool, token_id),
                "volume_profile": await get_trade_volume_profile(pool, token_id),
            }
        return result
    except Exception:
        logger.warning("get_market_features failed for condition_id=%s", condition_id, exc_info=True)
        return {}
