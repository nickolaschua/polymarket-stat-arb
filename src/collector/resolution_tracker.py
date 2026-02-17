"""Resolution tracking collector and winner inference.

Provides:
- ``infer_winner()`` to detect resolved prediction markets by examining
  outcomePrices for a price of exactly 1.0.
- ``ResolutionTracker`` collector class that polls the Gamma API for
  closed events, detects resolutions via ``infer_winner()``, and
  upserts to the ``resolutions`` table.

Usage::

    tracker = ResolutionTracker(pool, config)
    count = await tracker.collect_once()
    await tracker.close()
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx

from src.config import CollectorConfig, get_config
from src.db.queries.resolutions import upsert_resolution
from src.utils.retry import gamma_limiter

logger = logging.getLogger(__name__)


def _parse_json_field(value) -> list:
    """Parse a stringified JSON array, or return the value if already a list.

    Returns an empty list on any parsing error (JSONDecodeError, TypeError,
    non-list result, etc.).
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def infer_winner(raw_market: dict) -> Optional[dict]:
    """Infer the resolution winner from a raw Gamma API market dict.

    Examines ``outcomePrices`` for a float value of exactly 1.0.
    The corresponding index in ``outcomes`` and ``clobTokenIds``
    identifies the winning outcome and token.

    Parameters
    ----------
    raw_market:
        A raw market dict from the Gamma API.  Fields like
        ``outcomePrices``, ``outcomes``, and ``clobTokenIds`` may be
        stringified JSON arrays or native Python lists.

    Returns
    -------
    dict or None
        A resolution_data dict with keys matching ``upsert_resolution()``
        expectations, or ``None`` if the market is not resolved or data
        is malformed.

    Notes
    -----
    This function **never raises**.  Any unexpected error returns ``None``
    so that one malformed market cannot crash the collection loop.
    """
    try:
        # condition_id — try both camelCase and snake_case defensively
        condition_id = (
            raw_market.get("conditionId")
            or raw_market.get("condition_id")
            or ""
        )

        # Parse the three JSON array fields
        outcome_prices = _parse_json_field(raw_market.get("outcomePrices"))
        outcomes = _parse_json_field(raw_market.get("outcomes"))
        clob_token_ids = _parse_json_field(raw_market.get("clobTokenIds"))

        if not outcome_prices:
            return None

        # Find the winning index: first price that is exactly 1.0
        winner_idx: Optional[int] = None
        for idx, price_str in enumerate(outcome_prices):
            try:
                if float(price_str) == 1.0:
                    winner_idx = idx
                    break
            except (ValueError, TypeError):
                continue

        if winner_idx is None:
            return None

        # Look up outcome name and token ID by index (may be absent)
        outcome = (
            outcomes[winner_idx] if winner_idx < len(outcomes) else None
        )
        winner_token_id = (
            clob_token_ids[winner_idx]
            if winner_idx < len(clob_token_ids)
            else None
        )

        return {
            "condition_id": condition_id,
            "outcome": outcome,
            "winner_token_id": winner_token_id,
            "payout_price": 1.0,
            "detection_method": "gamma_api_polling",
            "resolved_at": datetime.now(timezone.utc),
        }

    except Exception:
        logger.debug(
            "infer_winner failed for market %s",
            raw_market.get("conditionId", "<unknown>"),
            exc_info=True,
        )
        return None


class ResolutionTracker:
    """Polls Gamma API for closed markets and detects resolutions.

    Follows the collector pattern: ``collect_once()`` returns an int
    count of new resolutions detected and **never raises**.

    Parameters
    ----------
    pool:
        asyncpg connection pool for database reads and writes.
    config:
        Collector configuration (intervals, limits, etc.).
    """

    _MAX_PAGES = 3
    _PAGE_LIMIT = 100

    def __init__(
        self,
        pool: asyncpg.Pool,
        config: CollectorConfig,
    ) -> None:
        self.pool = pool
        self.config = config
        self._gamma_host = get_config().polymarket.gamma_host
        self._http = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "polymarket-stat-arb/1.0"},
        )

    async def close(self) -> None:
        """Close the internal HTTP client."""
        await self._http.aclose()

    def _extract_raw_markets_from_events(
        self, events: list[dict],
    ) -> list[dict]:
        """Flatten events into raw market dicts (unmodified from Gamma API).

        Each event contains a ``"markets"`` list.  Markets missing a
        condition_id are silently skipped.
        """
        raw_markets: list[dict] = []
        for event in events:
            for raw_market in event.get("markets", []):
                condition_id = (
                    raw_market.get("conditionId")
                    or raw_market.get("condition_id")
                    or ""
                )
                if condition_id:
                    raw_markets.append(raw_market)
        return raw_markets

    async def collect_once(self) -> int:
        """Run one resolution-detection cycle.

        1. Paginate Gamma API ``GET /events?closed=true`` (max 3 pages).
        2. Flatten events into raw market dicts.
        3. Batch-check DB for already-resolved condition_ids.
        4. Call ``infer_winner()`` on unresolved markets.
        5. Upsert any new resolutions.
        6. Sync ``markets.closed = true`` for all condition_ids seen.

        Returns the number of new resolutions upserted, or 0 on error.
        Never raises.
        """
        try:
            # Step 1: Paginate Gamma API for closed events
            all_events: list[dict] = []
            for page in range(self._MAX_PAGES):
                await gamma_limiter.acquire()
                offset = page * self._PAGE_LIMIT
                response = await self._http.get(
                    f"{self._gamma_host}/events",
                    params={
                        "closed": "true",
                        "limit": self._PAGE_LIMIT,
                        "offset": offset,
                    },
                )
                response.raise_for_status()
                events = response.json()
                if isinstance(events, dict):
                    events = events.get("data", [])
                if not events:
                    break
                all_events.extend(events)
                if len(events) < self._PAGE_LIMIT:
                    break

            if not all_events:
                logger.info("No closed events found")
                return 0

            # Step 2: Flatten events -> raw market dicts
            raw_markets = self._extract_raw_markets_from_events(all_events)
            if not raw_markets:
                return 0

            # Collect all condition_ids
            all_condition_ids = []
            for m in raw_markets:
                cid = m.get("conditionId") or m.get("condition_id") or ""
                if cid:
                    all_condition_ids.append(cid)

            # Step 3: Batch-check for existing resolutions
            rows = await self.pool.fetch(
                "SELECT condition_id FROM resolutions"
                " WHERE condition_id = ANY($1::text[])",
                all_condition_ids,
            )
            already_resolved = {row["condition_id"] for row in rows}

            # Step 4-5: Infer winners and upsert new resolutions
            new_count = 0
            for raw_market in raw_markets:
                cid = (
                    raw_market.get("conditionId")
                    or raw_market.get("condition_id")
                    or ""
                )
                if cid in already_resolved:
                    continue

                result = infer_winner(raw_market)
                if result is not None:
                    await upsert_resolution(self.pool, result)
                    new_count += 1

            # Step 6: Sync markets.closed = true for all seen condition_ids
            if all_condition_ids:
                await self.pool.execute(
                    "UPDATE markets SET closed = true, updated_at = NOW()"
                    " WHERE condition_id = ANY($1::text[])"
                    " AND closed = false",
                    all_condition_ids,
                )

            logger.info(
                "Detected %d new resolutions from %d closed markets",
                new_count,
                len(raw_markets),
            )
            return new_count

        except Exception:
            logger.error(
                "Resolution tracking failed", exc_info=True,
            )
            return 0
