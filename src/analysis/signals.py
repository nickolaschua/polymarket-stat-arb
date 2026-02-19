"""Trading signal generation from market features.

Aggregates feature queries and relationship detections into actionable
MarketSignal objects.  Signals are read-only analysis — no orders are
placed here.

Signal types:
- ``same_event``: YES prices don't sum to 1.0
- ``mean_reversion``: Price deviated > z_threshold std from rolling mean
- ``spread``: Bid-ask spread implies > min_edge_pct% edge
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg

from src.analysis.relationships import (
    MarketGroup,
    detect_mispricing,
    find_same_event_markets,
)

logger = logging.getLogger(__name__)


@dataclass
class MarketSignal:
    """A single actionable trading signal.

    Attributes
    ----------
    market_id:
        Condition ID of the relevant market.
    signal_type:
        One of ``'same_event'``, ``'mean_reversion'``, ``'spread'``.
    direction:
        ``'buy'`` or ``'sell'``.
    strength:
        Signal confidence in [0, 1].  Higher = stronger.
    edge_pct:
        Estimated edge as a percentage (e.g. 3.5 means 3.5% edge).
    token_id:
        The specific token to trade.
    timestamp:
        When the signal was generated.
    """

    market_id: str
    signal_type: str
    direction: str
    strength: float
    edge_pct: float
    token_id: str
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


async def generate_same_event_signals(
    pool: asyncpg.Pool,
) -> list[MarketSignal]:
    """Generate signals when same-event markets don't sum to 1.0.

    When the YES probabilities of a same-event group sum to less than 1.0,
    all outcomes are under-priced; we generate buy signals for each.
    When they sum to more than 1.0, all are over-priced; we generate sell
    signals.  Signal strength is proportional to the deviation magnitude.

    Parameters
    ----------
    pool:
        asyncpg connection pool.

    Returns
    -------
    list[MarketSignal]
        One signal per underpriced/overpriced token.  Empty on error.
    """
    signals: list[MarketSignal] = []
    try:
        groups = await find_same_event_markets(pool)
        for group in groups:
            mispricings = await detect_mispricing(pool, group)
            for mp in mispricings:
                abs_dev = abs(mp.deviation)
                # strength: scale deviation; cap at 1.0
                strength = min(abs_dev * 10.0, 1.0)
                edge_pct = abs_dev * 100.0

                token_ids_with_direction = []
                if mp.deviation < 0:
                    # Sum < 1 -> under-priced -> buy underpriced tokens
                    token_ids_with_direction = [
                        (t, "buy") for t in mp.underpriced_token_ids
                    ]
                else:
                    # Sum > 1 -> over-priced -> sell overpriced tokens
                    token_ids_with_direction = [
                        (t, "sell") for t in mp.overpriced_token_ids
                    ]

                for token_id, direction in token_ids_with_direction:
                    # Find the condition_id for this token
                    row = await pool.fetchrow(
                        """
                        SELECT condition_id
                        FROM markets
                        WHERE $1 = ANY(clob_token_ids)
                        LIMIT 1
                        """,
                        token_id,
                    )
                    market_id = row["condition_id"] if row else "unknown"
                    signals.append(
                        MarketSignal(
                            market_id=market_id,
                            signal_type="same_event",
                            direction=direction,
                            strength=strength,
                            edge_pct=edge_pct,
                            token_id=token_id,
                        )
                    )
    except Exception:
        logger.warning("generate_same_event_signals failed", exc_info=True)
    return signals


async def generate_mean_reversion_signals(
    pool: asyncpg.Pool,
    z_threshold: float = 2.0,
    lookback_hours: int = 24,
) -> list[MarketSignal]:
    """Generate signals when a price deviates far from its rolling mean.

    For each active market token with sufficient price history, compute
    the z-score of the most recent price relative to the lookback window.
    When |z| > z_threshold, signal a reversion trade.

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    z_threshold:
        Number of standard deviations required to trigger a signal
        (default 2.0).
    lookback_hours:
        Rolling window in hours (default 24).

    Returns
    -------
    list[MarketSignal]
        One signal per token with |z| > z_threshold.  Empty on error.
    """
    signals: list[MarketSignal] = []
    try:
        # Compute z-score for each token in the window in SQL.
        # Uses per-token MAX(ts) for lookback (not NOW()) so it works
        # on historical data and during backtesting.
        rows = await pool.fetch(
            """
            WITH per_token_latest AS (
                SELECT token_id, MAX(ts) AS max_ts
                FROM price_snapshots
                GROUP BY token_id
            ),
            stats AS (
                SELECT
                    ps.token_id,
                    avg(ps.price) AS mean_price,
                    stddev(ps.price) AS std_price,
                    last(ps.price, ps.ts) AS latest_price
                FROM price_snapshots ps
                JOIN per_token_latest ptl ON ps.token_id = ptl.token_id
                WHERE ps.ts >= ptl.max_ts - ($1 || ' hours')::interval
                GROUP BY ps.token_id
                HAVING count(*) >= 5
            )
            SELECT
                token_id,
                latest_price,
                mean_price,
                std_price,
                CASE
                    WHEN std_price > 0
                    THEN (latest_price - mean_price) / std_price
                    ELSE 0
                END AS z_score
            FROM stats
            """,
            str(lookback_hours),
        )

        for row in rows:
            z = float(row["z_score"] or 0)
            if abs(z) <= z_threshold:
                continue

            token_id = row["token_id"]
            # Revert to mean: if price is high, sell; if low, buy
            direction = "sell" if z > 0 else "buy"
            strength = min(abs(z) / (z_threshold * 2), 1.0)
            edge_pct = (abs(z) - z_threshold) * float(row["std_price"] or 0) * 100.0

            market_row = await pool.fetchrow(
                """
                SELECT condition_id
                FROM markets
                WHERE $1 = ANY(clob_token_ids)
                LIMIT 1
                """,
                token_id,
            )
            market_id = market_row["condition_id"] if market_row else "unknown"

            signals.append(
                MarketSignal(
                    market_id=market_id,
                    signal_type="mean_reversion",
                    direction=direction,
                    strength=strength,
                    edge_pct=edge_pct,
                    token_id=token_id,
                )
            )
    except Exception:
        logger.warning("generate_mean_reversion_signals failed", exc_info=True)
    return signals


async def generate_spread_signals(
    pool: asyncpg.Pool,
    min_edge_pct: float = 2.0,
) -> list[MarketSignal]:
    """Generate signals when the bid-ask spread implies significant edge.

    Looks at the most recent orderbook snapshot for each token.  When the
    spread (as a percentage of the midpoint) exceeds ``min_edge_pct``,
    emit a buy signal for the bid side (capturing the spread).

    Parameters
    ----------
    pool:
        asyncpg connection pool.
    min_edge_pct:
        Minimum spread as percentage of midpoint to generate a signal
        (default 2.0).

    Returns
    -------
    list[MarketSignal]
        One signal per token with spread > min_edge_pct%.  Empty on error.
    """
    signals: list[MarketSignal] = []
    try:
        rows = await pool.fetch(
            """
            SELECT DISTINCT ON (token_id)
                token_id, spread, midpoint
            FROM orderbook_snapshots
            WHERE spread IS NOT NULL
              AND midpoint IS NOT NULL
              AND midpoint > 0
            ORDER BY token_id, ts DESC
            """
        )

        for row in rows:
            spread = float(row["spread"])
            midpoint = float(row["midpoint"])
            edge_pct = (spread / midpoint) * 100.0

            if edge_pct < min_edge_pct:
                continue

            token_id = row["token_id"]
            strength = min((edge_pct - min_edge_pct) / min_edge_pct, 1.0)

            market_row = await pool.fetchrow(
                """
                SELECT condition_id
                FROM markets
                WHERE $1 = ANY(clob_token_ids)
                LIMIT 1
                """,
                token_id,
            )
            market_id = market_row["condition_id"] if market_row else "unknown"

            signals.append(
                MarketSignal(
                    market_id=market_id,
                    signal_type="spread",
                    direction="buy",
                    strength=strength,
                    edge_pct=edge_pct,
                    token_id=token_id,
                )
            )
    except Exception:
        logger.warning("generate_spread_signals failed", exc_info=True)
    return signals


async def get_all_signals(pool: asyncpg.Pool) -> list[MarketSignal]:
    """Collect, deduplicate, and rank all trading signals.

    Runs all signal generators, deduplicates by (token_id, signal_type),
    keeping the highest-strength signal per unique key, then sorts by
    strength descending.

    Parameters
    ----------
    pool:
        asyncpg connection pool.

    Returns
    -------
    list[MarketSignal]
        All unique signals ranked by strength (strongest first).
    """
    raw: list[MarketSignal] = []
    try:
        same_event = await generate_same_event_signals(pool)
        mean_rev = await generate_mean_reversion_signals(pool)
        spread = await generate_spread_signals(pool)
        raw = same_event + mean_rev + spread
    except Exception:
        logger.warning("get_all_signals failed during generation", exc_info=True)
        return []

    # Deduplicate: keep highest-strength per (token_id, signal_type)
    best: dict[tuple[str, str], MarketSignal] = {}
    for sig in raw:
        key = (sig.token_id, sig.signal_type)
        if key not in best or sig.strength > best[key].strength:
            best[key] = sig

    return sorted(best.values(), key=lambda s: s.strength, reverse=True)
