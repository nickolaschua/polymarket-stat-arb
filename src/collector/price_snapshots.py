"""Price snapshot collector.

Paginates Gamma API events and bulk-inserts per-token price tuples to the
``price_snapshots`` hypertable using the COPY protocol.  This is the
highest-volume collector (~8,000 rows per cycle) and runs every 60 seconds.

Usage::

    collector = PriceSnapshotCollector(pool, client, config)
    count = await collector.collect_once()
"""

import json
import logging
from datetime import datetime, timezone

import asyncpg

from src.config import CollectorConfig
from src.db.queries.prices import insert_price_snapshots
from src.utils.client import PolymarketClient
from src.utils.retry import gamma_limiter

logger = logging.getLogger(__name__)


class PriceSnapshotCollector:
    """Collects per-token price snapshots from the Gamma API and bulk-inserts to the DB.

    Parameters
    ----------
    pool:
        asyncpg connection pool for database writes.
    client:
        PolymarketClient instance (provides ``get_all_active_markets``).
    config:
        Collector configuration (intervals, limits, etc.).
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        client: PolymarketClient,
        config: CollectorConfig,
    ) -> None:
        self.pool = pool
        self.client = client
        self.config = config

    def _extract_price_tuples(
        self, events: list[dict], ts: datetime
    ) -> list[tuple]:
        """Transform Gamma API events into price snapshot tuples.

        Iterates events and their nested markets, parsing stringified JSON
        fields ``clobTokenIds`` and ``outcomePrices`` to produce one tuple
        per token.

        Parameters
        ----------
        events:
            Raw event dicts from the Gamma API.
        ts:
            Timezone-aware timestamp to attach to every snapshot.

        Returns
        -------
        list[tuple]
            Each tuple is ``(ts, token_id, price, volume_24h)``.
        """
        tuples: list[tuple] = []

        for event in events:
            for market in event.get("markets", []):
                # Parse clobTokenIds (stringified JSON array)
                raw_token_ids = market.get("clobTokenIds", "")
                try:
                    token_ids = json.loads(raw_token_ids)
                    if not isinstance(token_ids, list):
                        continue
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Skipping market — malformed clobTokenIds: %.80s",
                        raw_token_ids,
                    )
                    continue

                # Parse outcomePrices (stringified JSON array)
                raw_prices = market.get("outcomePrices", "")
                try:
                    prices = json.loads(raw_prices)
                    if not isinstance(prices, list):
                        continue
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "Skipping market — malformed outcomePrices: %.80s",
                        raw_prices,
                    )
                    continue

                # volume_24h — handle None, missing, and empty string
                volume_24h = float(market.get("volume24hr", 0) or 0)

                # Zip tokens and prices, skipping empty token_ids
                for token_id, price_str in zip(token_ids, prices):
                    if not token_id:
                        continue
                    tuples.append(
                        (ts, str(token_id), float(price_str), volume_24h)
                    )

        return tuples

    async def collect_once(self) -> int:
        """Run one collection cycle.

        Acquires the Gamma rate limiter, fetches all active events via
        pagination, extracts per-token price tuples, and bulk-inserts
        to the ``price_snapshots`` hypertable using the COPY protocol.

        Returns the number of price snapshots inserted, or 0 on error.
        Never raises -- errors are logged so the daemon loop continues.
        """
        try:
            ts = datetime.now(timezone.utc)
            await gamma_limiter.acquire()
            events = await self.client.get_all_active_markets(
                max_events=self.config.max_markets,
            )
            tuples = self._extract_price_tuples(events, ts)

            if not tuples:
                logger.info("No price tuples extracted from %d events", len(events))
                return 0

            count = await insert_price_snapshots(self.pool, tuples)
            logger.info(
                "Inserted %d price snapshots from %d events",
                count,
                len(events),
            )
            return count
        except Exception:
            logger.error("Price snapshot collection failed", exc_info=True)
            return 0
