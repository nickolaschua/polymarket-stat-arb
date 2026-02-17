"""Resolution winner inference from Gamma API market data.

Provides ``infer_winner()`` to detect resolved prediction markets by
examining outcomePrices for a price of exactly 1.0, and mapping that
index to the winning outcome and token ID.

Usage::

    result = infer_winner(raw_market)
    if result is not None:
        await upsert_resolution(pool, result)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

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
