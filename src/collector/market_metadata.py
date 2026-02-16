"""Market metadata collector.

Paginates Gamma API events and upserts market data to the markets table.
This is the first collector and establishes the pattern for all subsequent
collectors in the pipeline.

Usage::

    collector = MarketMetadataCollector(pool, client, config)
    count = await collector.collect_once()
"""

import json
import logging
from typing import Optional

import asyncpg

from src.config import CollectorConfig
from src.db.queries.markets import upsert_markets
from src.utils.client import PolymarketClient
from src.utils.retry import gamma_limiter

logger = logging.getLogger(__name__)


class MarketMetadataCollector:
    """Collects market metadata from the Gamma API and upserts to the DB.

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

    def _extract_market_data(self, raw_market: dict) -> Optional[dict]:
        """Transform a single Gamma API market object into upsert format.

        Returns a dict with the keys expected by ``upsert_market()``, or
        ``None`` if the market lacks a condition ID.
        """
        # condition_id — try both camelCase and snake_case defensively
        condition_id = (
            raw_market.get("conditionId")
            or raw_market.get("condition_id")
            or ""
        )
        if not condition_id:
            return None

        # clob_token_ids — stringified JSON array from Gamma API
        raw_clob = raw_market.get("clobTokenIds", "")
        if isinstance(raw_clob, list):
            clob_token_ids = raw_clob
        else:
            try:
                parsed = json.loads(raw_clob)
                clob_token_ids = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                clob_token_ids = []

        # outcomes — may be stringified JSON or native list
        raw_outcomes = raw_market.get("outcomes", "")
        if isinstance(raw_outcomes, list):
            outcomes = raw_outcomes
        else:
            try:
                parsed = json.loads(raw_outcomes)
                outcomes = parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                outcomes = []

        # end_date_iso — try both camelCase and snake_case
        end_date_iso = (
            raw_market.get("endDateIso")
            or raw_market.get("end_date_iso")
        )

        # market_type — try both camelCase and snake_case
        market_type = (
            raw_market.get("marketType")
            or raw_market.get("market_type")
        )

        return {
            "condition_id": condition_id,
            "question": raw_market.get("question", ""),
            "slug": raw_market.get("slug"),
            "market_type": market_type,
            "outcomes": outcomes,
            "clob_token_ids": clob_token_ids,
            "active": raw_market.get("active", True),
            "closed": raw_market.get("closed", False),
            "end_date_iso": end_date_iso,
        }

    def _extract_markets_from_events(self, events: list[dict]) -> list[dict]:
        """Flatten events into a list of market dicts ready for upsert.

        Each event contains a ``"markets"`` list.  Markets that fail
        extraction (missing condition_id, etc.) are silently skipped.
        """
        market_dicts: list[dict] = []
        for event in events:
            for raw_market in event.get("markets", []):
                extracted = self._extract_market_data(raw_market)
                if extracted is not None:
                    market_dicts.append(extracted)
        return market_dicts

    async def collect_once(self) -> int:
        """Run one collection cycle.

        Acquires the Gamma rate limiter, fetches all active events via
        pagination, extracts market metadata, and upserts to the DB.

        Returns the number of markets upserted, or 0 on error.
        Never raises — errors are logged so the daemon loop continues.
        """
        try:
            await gamma_limiter.acquire()
            events = await self.client.get_all_active_markets()
            market_dicts = self._extract_markets_from_events(events)
            await upsert_markets(self.pool, market_dicts)
            logger.info(
                "Upserted %d markets from %d events",
                len(market_dicts),
                len(events),
            )
            return len(market_dicts)
        except Exception:
            logger.error("Market metadata collection failed", exc_info=True)
            return 0
