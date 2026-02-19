"""Market relationship detection functions.

Identifies groups of related markets (same-event), computes price
correlations, and detects mispricings in same-event market groups.

All functions return empty containers on error rather than raising,
so callers can safely aggregate results.
"""

import logging
from dataclasses import dataclass, field

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class MarketGroup:
    """A group of markets sharing the same Polymarket event slug prefix.

    Attributes
    ----------
    slug_prefix:
        The common slug prefix shared by all markets in the group.
    condition_ids:
        Condition IDs of the markets in this group.
    token_ids:
        All token IDs (outcomes) across the markets.
    """

    slug_prefix: str
    condition_ids: list[str] = field(default_factory=list)
    token_ids: list[str] = field(default_factory=list)


@dataclass
class Mispricing:
    """A detected mispricing in a same-event market group.

    Attributes
    ----------
    condition_ids:
        The markets involved in the mispricing.
    yes_sum:
        Sum of YES-outcome prices (probabilities) across the group.
    deviation:
        How far the sum deviates from 1.0 (positive = over-priced collective,
        negative = under-priced collective).
    underpriced_token_ids:
        Token IDs where the price is below fair value (to buy).
    overpriced_token_ids:
        Token IDs where the price is above fair value (to sell).
    """

    condition_ids: list[str]
    yes_sum: float
    deviation: float
    underpriced_token_ids: list[str] = field(default_factory=list)
    overpriced_token_ids: list[str] = field(default_factory=list)


async def find_same_event_markets(
    pool: asyncpg.Pool,
) -> list[MarketGroup]:
    """Find groups of active markets that share the same event.

    Markets belonging to the same Polymarket event share a common slug
    prefix (the event slug appears before a trailing ``-n`` numeric suffix
    on individual market slugs, or markets are directly grouped by
    ``event_slug`` if stored).

    This implementation groups markets whose slugs share the same prefix
    up to the last hyphen-number segment.  Groups with only one market are
    excluded — they can't exhibit a sum-to-one constraint.

    Parameters
    ----------
    pool:
        asyncpg connection pool.

    Returns
    -------
    list[MarketGroup]
        One MarketGroup per event, each containing 2+ markets.
        Returns empty list on error or no data.
    """
    try:
        rows = await pool.fetch(
            """
            SELECT condition_id, slug, clob_token_ids
            FROM markets
            WHERE active = true
              AND closed = false
              AND slug IS NOT NULL
              AND array_length(clob_token_ids, 1) > 0
            ORDER BY slug
            """
        )
        if not rows:
            return []

        # Group by slug prefix: strip trailing "-<digits>" suffix
        groups: dict[str, MarketGroup] = {}
        for row in rows:
            slug: str = row["slug"]
            condition_id: str = row["condition_id"]
            token_ids: list[str] = list(row["clob_token_ids"] or [])

            prefix = _slug_prefix(slug)
            if prefix not in groups:
                groups[prefix] = MarketGroup(slug_prefix=prefix)
            groups[prefix].condition_ids.append(condition_id)
            groups[prefix].token_ids.extend(token_ids)

        # Return only groups with 2+ markets
        return [g for g in groups.values() if len(g.condition_ids) >= 2]
    except Exception:
        logger.warning("find_same_event_markets failed", exc_info=True)
        return []


def _slug_prefix(slug: str) -> str:
    """Extract the event prefix from a market slug.

    Strips trailing ``-<digits>`` suffix.  For example:
    ``"us-election-2024-winner-2"``  ->  ``"us-election-2024-winner"``
    ``"bitcoin-price-jan-2025"``     ->  ``"bitcoin-price-jan-2025"``
    """
    parts = slug.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return slug


async def compute_price_correlation(
    pool: asyncpg.Pool,
    token_id_a: str,
    token_id_b: str,
    lookback_hours: int = 168,
) -> float | None:
    """Compute Pearson correlation between two token price time series.

    Aligns the two series on 1-hour buckets and computes the Pearson
    correlation over the overlapping window.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    token_id_a:
        First token ID.
    token_id_b:
        Second token ID.
    lookback_hours:
        Look-back window in hours (default 168 = 7 days).

    Returns
    -------
    float or None
        Pearson correlation in [-1, 1], or None if there are fewer than
        2 aligned data points or an error occurs.
    """
    try:
        row = await pool.fetchrow(
            """
            WITH ref AS (
                SELECT GREATEST(
                    (SELECT MAX(ts) FROM price_snapshots WHERE token_id = $1),
                    (SELECT MAX(ts) FROM price_snapshots WHERE token_id = $2)
                ) AS max_ts
            ),
            a AS (
                SELECT
                    time_bucket('1 hour', ts) AS bucket,
                    last(price, ts) AS price
                FROM price_snapshots, ref
                WHERE token_id = $1
                  AND ts >= ref.max_ts - ($3 || ' hours')::interval
                GROUP BY bucket
            ),
            b AS (
                SELECT
                    time_bucket('1 hour', ts) AS bucket,
                    last(price, ts) AS price
                FROM price_snapshots, ref
                WHERE token_id = $2
                  AND ts >= ref.max_ts - ($3 || ' hours')::interval
                GROUP BY bucket
            ),
            aligned AS (
                SELECT a.price AS pa, b.price AS pb
                FROM a
                JOIN b ON a.bucket = b.bucket
            )
            SELECT corr(pa, pb) AS correlation
            FROM aligned
            """,
            token_id_a,
            token_id_b,
            str(lookback_hours),
        )
        if row is None:
            return None
        return row["correlation"]
    except Exception:
        logger.warning(
            "compute_price_correlation failed for (%s, %s)",
            token_id_a,
            token_id_b,
            exc_info=True,
        )
        return None


async def find_correlated_pairs(
    pool: asyncpg.Pool,
    min_correlation: float = 0.7,
    lookback_hours: int = 168,
    max_tokens: int = 50,
) -> list[tuple[str, str, float]]:
    """Scan active markets for highly correlated token pairs.

    Computes pairwise Pearson correlation for active market tokens
    that have price data in the lookback window.  Only pairs meeting the
    ``min_correlation`` threshold are returned.

    Performance: Pairwise correlation is O(n^2) in SQL queries.
    ``max_tokens`` caps the token count to keep this tractable
    (50 tokens = 1,225 pairs; 100 = 4,950).  Tokens are selected by
    highest data density (most price snapshots in the window).

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    min_correlation:
        Minimum |correlation| to include in results (default 0.7).
    lookback_hours:
        Look-back window in hours (default 168 = 7 days).
    max_tokens:
        Maximum number of tokens to scan (default 50).  Tokens with the
        most price data in the window are selected first.

    Returns
    -------
    list[tuple[str, str, float]]
        List of ``(token_id_a, token_id_b, correlation)`` triples,
        ordered by |correlation| descending.  Returns empty list on error.
    """
    try:
        # Select tokens with the most data points in the window,
        # capped at max_tokens to keep O(n^2) tractable.
        rows = await pool.fetch(
            """
            WITH per_token AS (
                SELECT token_id, MAX(ts) AS max_ts
                FROM price_snapshots
                GROUP BY token_id
            )
            SELECT ps.token_id, COUNT(*) AS n
            FROM price_snapshots ps
            JOIN per_token pt ON ps.token_id = pt.token_id
            WHERE ps.ts >= pt.max_ts - ($1 || ' hours')::interval
            GROUP BY ps.token_id
            HAVING COUNT(*) >= 5
            ORDER BY n DESC
            LIMIT $2
            """,
            str(lookback_hours),
            max_tokens,
        )
        token_ids = [row["token_id"] for row in rows]

        if len(token_ids) < 2:
            return []

        results: list[tuple[str, str, float]] = []
        for i, tok_a in enumerate(token_ids):
            for tok_b in token_ids[i + 1 :]:
                corr = await compute_price_correlation(
                    pool, tok_a, tok_b, lookback_hours
                )
                if corr is not None and abs(corr) >= min_correlation:
                    results.append((tok_a, tok_b, corr))

        results.sort(key=lambda x: abs(x[2]), reverse=True)
        return results
    except Exception:
        logger.warning("find_correlated_pairs failed", exc_info=True)
        return []


async def detect_mispricing(
    pool: asyncpg.Pool,
    event_markets: MarketGroup,
    tolerance: float = 0.02,
) -> list[Mispricing]:
    """Detect mispricings in a same-event market group.

    For binary markets, the YES token prices should sum to 1.0.
    If the sum deviates by more than ``tolerance``, a mispricing exists.

    This function looks at the first token in each market's
    ``clob_token_ids`` as the YES token (index 0 by convention).

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    event_markets:
        A MarketGroup identified by find_same_event_markets.
    tolerance:
        Maximum allowed deviation from 1.0 before flagging a mispricing
        (default 0.02 = 2%).

    Returns
    -------
    list[Mispricing]
        One Mispricing if detected; empty list if prices sum correctly
        or data is unavailable.
    """
    try:
        rows = await pool.fetch(
            """
            SELECT condition_id, clob_token_ids
            FROM markets
            WHERE condition_id = ANY($1::text[])
            """,
            event_markets.condition_ids,
        )
        if not rows:
            return []

        # Gather latest YES-token prices
        yes_token_prices: dict[str, float] = {}
        for row in rows:
            token_ids = list(row["clob_token_ids"] or [])
            if not token_ids:
                continue
            yes_token = token_ids[0]
            price_row = await pool.fetchrow(
                """
                SELECT price
                FROM price_snapshots
                WHERE token_id = $1
                ORDER BY ts DESC
                LIMIT 1
                """,
                yes_token,
            )
            if price_row is not None:
                yes_token_prices[yes_token] = price_row["price"]

        if not yes_token_prices:
            return []

        yes_sum = sum(yes_token_prices.values())
        deviation = yes_sum - 1.0

        if abs(deviation) <= tolerance:
            return []

        # For same-event arbitrage: when yes_sum < 1.0 all outcomes are
        # collectively underpriced (buy all = guaranteed profit);
        # when yes_sum > 1.0 all are overpriced (sell all = guaranteed profit).
        all_tokens = list(yes_token_prices.keys())
        if deviation < 0:
            underpriced = all_tokens
            overpriced = []
        else:
            underpriced = []
            overpriced = all_tokens

        return [
            Mispricing(
                condition_ids=event_markets.condition_ids,
                yes_sum=yes_sum,
                deviation=deviation,
                underpriced_token_ids=underpriced,
                overpriced_token_ids=overpriced,
            )
        ]
    except Exception:
        logger.warning(
            "detect_mispricing failed for group %s",
            event_markets.slug_prefix,
            exc_info=True,
        )
        return []
