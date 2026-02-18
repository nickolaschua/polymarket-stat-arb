"""Orderbook snapshot collector.

Queries active markets from the database, batch-fetches orderbooks from the
CLOB API (sync-to-async wrapping via ``run_in_executor``), and inserts JSONB
orderbook snapshots with spread/midpoint computation.

Orderbook depth data captures market microstructure -- bid/ask spreads,
liquidity depth, and order flow patterns needed for execution optimization
and market quality assessment.

Usage::

    collector = OrderbookSnapshotCollector(pool, client, config)
    count = await collector.collect_once()
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg

from src.config import CollectorConfig
from src.db.queries.markets import get_active_markets
from src.db.queries.orderbooks import insert_orderbook_snapshots
from src.utils.client import PolymarketClient
from src.utils.retry import clob_read_limiter

logger = logging.getLogger(__name__)

# Maximum number of token IDs per CLOB API batch request.
# Prevents overwhelming the CLOB API and avoids excessively large single requests.
_CHUNK_SIZE = 20


class OrderbookSnapshotCollector:
    """Collects orderbook snapshots from the CLOB API and inserts to the DB.

    Parameters
    ----------
    pool:
        asyncpg connection pool for database writes.
    client:
        PolymarketClient instance (provides ``get_orderbooks``).
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

    def _extract_orderbook_tuple(
        self, token_id: str, book: dict, ts: datetime
    ) -> tuple:
        """Transform a single CLOB orderbook response into a DB-ready tuple.

        Parameters
        ----------
        token_id:
            The token this orderbook belongs to.
        book:
            CLOB orderbook dict with ``"bids"`` and ``"asks"`` lists.
            Each entry has ``"price"`` and ``"size"`` string fields.
        ts:
            Timezone-aware timestamp to attach to the snapshot.

        Returns
        -------
        tuple
            ``(ts, token_id, bids_dict, asks_dict, spread, midpoint)``
        """
        raw_bids = book.bids if hasattr(book, "bids") else book.get("bids", [])
        raw_asks = book.asks if hasattr(book, "asks") else book.get("asks", [])
        bids = [
            [float(level.price if hasattr(level, "price") else level["price"]),
             float(level.size if hasattr(level, "size") else level["size"])]
            for level in (raw_bids or [])
        ]
        asks = [
            [float(level.price if hasattr(level, "price") else level["price"]),
             float(level.size if hasattr(level, "size") else level["size"])]
            for level in (raw_asks or [])
        ]

        bids_dict = {"levels": bids}
        asks_dict = {"levels": asks}

        best_bid: Optional[float] = bids[0][0] if bids else None
        best_ask: Optional[float] = asks[0][0] if asks else None

        spread: Optional[float] = None
        midpoint: Optional[float] = None
        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            midpoint = (best_ask + best_bid) / 2

        return (ts, token_id, bids_dict, asks_dict, spread, midpoint)

    async def _fetch_orderbooks(
        self, token_ids: list[str]
    ) -> list[dict]:
        """Fetch orderbooks for a batch of token IDs from the CLOB API.

        The py-clob-client is synchronous, so we wrap the call in
        ``run_in_executor`` to avoid blocking the event loop.

        Parameters
        ----------
        token_ids:
            List of token IDs to fetch orderbooks for.

        Returns
        -------
        list[dict]
            List of orderbook dicts, or empty list on error.
        """
        try:
            await clob_read_limiter.acquire()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self.client.get_orderbooks, token_ids
            )
            return result
        except Exception:
            logger.warning(
                "Failed to fetch orderbooks for %d tokens",
                len(token_ids),
                exc_info=True,
            )
            return []

    async def collect_once(self) -> int:
        """Run one collection cycle.

        Queries active markets from the DB, extracts all token IDs,
        fetches orderbooks from the CLOB in batches, computes
        spread/midpoint, and inserts snapshots to the DB.

        Returns the number of orderbook snapshots inserted, or 0 on error.
        Never raises -- errors are logged so the daemon loop continues.
        """
        try:
            markets = await get_active_markets(self.pool)

            # Flatten all token IDs from active markets
            all_token_ids: list[str] = []
            for market in markets:
                all_token_ids.extend(market.clob_token_ids)

            if not all_token_ids:
                logger.info(
                    "No active markets found, skipping orderbook collection"
                )
                return 0

            ts = datetime.now(timezone.utc)

            # Chunk token_ids into batches to avoid overwhelming the CLOB API
            chunks = [
                all_token_ids[i : i + _CHUNK_SIZE]
                for i in range(0, len(all_token_ids), _CHUNK_SIZE)
            ]

            all_tuples: list[tuple] = []
            for chunk in chunks:
                books = await self._fetch_orderbooks(chunk)
                for token_id, book in zip(chunk, books):
                    row = self._extract_orderbook_tuple(token_id, book, ts)
                    all_tuples.append(row)

            count = await insert_orderbook_snapshots(self.pool, all_tuples)
            logger.info(
                "Inserted %d orderbook snapshots for %d tokens",
                count,
                len(all_token_ids),
            )
            return count
        except Exception:
            logger.error("Orderbook snapshot collection failed", exc_info=True)
            return 0
