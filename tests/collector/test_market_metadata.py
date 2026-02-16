"""Tests for MarketMetadataCollector.

Unit tests verify field extraction logic without DB or HTTP.
Integration tests use respx to mock the Gamma API and migrated_pool
for real database writes.
"""

import httpx
import pytest
import respx

from src.collector.market_metadata import MarketMetadataCollector
from src.config import CollectorConfig
from src.db.queries.markets import get_market
from src.utils.client import PolymarketClient

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_market(
    condition_id: str = "0xabc123",
    question: str = "Will X happen?",
    slug: str = "will-x-happen",
    clob_token_ids: str = '["token_yes","token_no"]',
    outcomes: str = '["Yes","No"]',
    active: bool = True,
    closed: bool = False,
    end_date_iso: str = "2026-03-01T00:00:00Z",
    market_type: str = "binary",
) -> dict:
    """Build a sample Gamma API market dict."""
    return {
        "conditionId": condition_id,
        "question": question,
        "slug": slug,
        "clobTokenIds": clob_token_ids,
        "outcomePrices": '["0.55","0.45"]',
        "outcomes": outcomes,
        "active": active,
        "closed": closed,
        "endDateIso": end_date_iso,
        "marketType": market_type,
    }


def _make_event(markets: list[dict], event_id: str = "evt_1") -> dict:
    """Wrap market dicts in an event structure."""
    return {"id": event_id, "markets": markets}


def _collector(pool=None, client=None) -> MarketMetadataCollector:
    """Create a collector with optional pool/client overrides."""
    return MarketMetadataCollector(
        pool=pool,
        client=client or PolymarketClient(),
        config=CollectorConfig(),
    )


# =========================================================================
# Unit tests — no DB, no respx needed
# =========================================================================


class TestExtractMarketData:
    """Test _extract_market_data field mapping."""

    def test_extract_market_data_basic(self) -> None:
        """Standard Gamma API market dict is correctly transformed."""
        collector = _collector()
        raw = _make_raw_market()

        result = collector._extract_market_data(raw)

        assert result is not None
        assert result["condition_id"] == "0xabc123"
        assert result["question"] == "Will X happen?"
        assert result["slug"] == "will-x-happen"
        assert result["market_type"] == "binary"
        assert result["outcomes"] == ["Yes", "No"]
        assert result["clob_token_ids"] == ["token_yes", "token_no"]
        assert result["active"] is True
        assert result["closed"] is False
        assert result["end_date_iso"] == "2026-03-01T00:00:00Z"

    def test_extract_market_data_missing_condition_id(self) -> None:
        """Market without conditionId or condition_id returns None."""
        collector = _collector()
        raw = {
            "question": "No condition ID here",
            "slug": "no-cid",
            "clobTokenIds": '["a","b"]',
            "outcomes": '["Yes","No"]',
        }

        result = collector._extract_market_data(raw)

        assert result is None

    def test_extract_market_data_native_list_outcomes(self) -> None:
        """outcomes as native Python list (not stringified) works."""
        collector = _collector()
        raw = _make_raw_market(outcomes=["Yes", "No"])

        result = collector._extract_market_data(raw)

        assert result is not None
        assert result["outcomes"] == ["Yes", "No"]

    def test_extract_market_data_native_list_clob_token_ids(self) -> None:
        """clobTokenIds as native Python list works."""
        collector = _collector()
        raw = _make_raw_market(clob_token_ids=["tok_a", "tok_b"])

        result = collector._extract_market_data(raw)

        assert result is not None
        assert result["clob_token_ids"] == ["tok_a", "tok_b"]

    def test_extract_market_data_snake_case_keys(self) -> None:
        """snake_case keys (condition_id, market_type, end_date_iso) work."""
        collector = _collector()
        raw = {
            "condition_id": "0xsnake",
            "question": "Snake case?",
            "slug": "snake",
            "market_type": "categorical",
            "clobTokenIds": '["x","y"]',
            "outcomes": '["A","B"]',
            "end_date_iso": "2026-06-01T00:00:00Z",
        }

        result = collector._extract_market_data(raw)

        assert result is not None
        assert result["condition_id"] == "0xsnake"
        assert result["market_type"] == "categorical"
        assert result["end_date_iso"] == "2026-06-01T00:00:00Z"

    def test_extract_market_data_empty_condition_id_returns_none(self) -> None:
        """Empty string conditionId is treated as missing."""
        collector = _collector()
        raw = _make_raw_market(condition_id="")

        result = collector._extract_market_data(raw)

        assert result is None


class TestExtractMarketsFromEvents:
    """Test _extract_markets_from_events flattening logic."""

    def test_extract_markets_from_events(self) -> None:
        """Two events with 2 markets each yields flat list of 4."""
        collector = _collector()
        events = [
            _make_event([
                _make_raw_market(condition_id="0x01"),
                _make_raw_market(condition_id="0x02"),
            ]),
            _make_event([
                _make_raw_market(condition_id="0x03"),
                _make_raw_market(condition_id="0x04"),
            ]),
        ]

        result = collector._extract_markets_from_events(events)

        assert len(result) == 4
        ids = {m["condition_id"] for m in result}
        assert ids == {"0x01", "0x02", "0x03", "0x04"}

    def test_extract_markets_from_events_empty_markets(self) -> None:
        """Event with empty markets list contributes nothing."""
        collector = _collector()
        events = [
            _make_event([_make_raw_market(condition_id="0x10")]),
            _make_event([]),  # empty
            {"id": "evt_no_key"},  # no "markets" key at all
        ]

        result = collector._extract_markets_from_events(events)

        assert len(result) == 1
        assert result[0]["condition_id"] == "0x10"

    def test_extract_markets_from_events_filters_invalid(self) -> None:
        """Markets missing condition_id are filtered out."""
        collector = _collector()
        events = [
            _make_event([
                _make_raw_market(condition_id="0xvalid"),
                _make_raw_market(condition_id=""),  # invalid
            ]),
        ]

        result = collector._extract_markets_from_events(events)

        assert len(result) == 1
        assert result[0]["condition_id"] == "0xvalid"


# =========================================================================
# Integration tests — respx + migrated_pool
# =========================================================================


class TestCollectOnce:
    """Integration tests for the full collect_once flow."""

    @respx.mock
    async def test_collect_once_success(
        self, migrated_pool, mock_client
    ) -> None:
        """collect_once fetches events, extracts markets, and upserts to DB."""
        events = [
            _make_event([
                _make_raw_market(condition_id="0xcollect_1", question="Q1?"),
                _make_raw_market(condition_id="0xcollect_2", question="Q2?"),
            ]),
            _make_event([
                _make_raw_market(condition_id="0xcollect_3", question="Q3?"),
            ]),
        ]

        # Mock: single page with < 100 events → no pagination
        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(200, json=events)
        )

        collector = MarketMetadataCollector(
            pool=migrated_pool,
            client=mock_client,
            config=CollectorConfig(),
        )
        count = await collector.collect_once()

        assert count == 3

        # Verify data persisted in DB
        m1 = await get_market(migrated_pool, "0xcollect_1")
        assert m1 is not None
        assert m1.question == "Q1?"

        m3 = await get_market(migrated_pool, "0xcollect_3")
        assert m3 is not None
        assert m3.question == "Q3?"

    @respx.mock
    async def test_collect_once_pagination(
        self, migrated_pool, mock_client
    ) -> None:
        """collect_once handles multi-page pagination correctly."""
        # Page 1: exactly 100 events (triggers pagination), each with 1 market
        page_1_events = [
            _make_event(
                [_make_raw_market(condition_id=f"0xp1_{i}", question=f"P1 Q{i}?")],
                event_id=f"evt_p1_{i}",
            )
            for i in range(100)
        ]

        # Page 2: 20 events (< 100, stops pagination)
        page_2_events = [
            _make_event(
                [_make_raw_market(condition_id=f"0xp2_{i}", question=f"P2 Q{i}?")],
                event_id=f"evt_p2_{i}",
            )
            for i in range(20)
        ]

        def gamma_side_effect(request):
            offset = int(request.url.params.get("offset", 0))
            if offset == 0:
                return httpx.Response(200, json=page_1_events)
            elif offset == 100:
                return httpx.Response(200, json=page_2_events)
            else:
                return httpx.Response(200, json=[])

        respx.get(GAMMA_EVENTS_URL).mock(side_effect=gamma_side_effect)

        collector = MarketMetadataCollector(
            pool=migrated_pool,
            client=mock_client,
            config=CollectorConfig(),
        )
        count = await collector.collect_once()

        # 100 + 20 = 120 markets (1 per event)
        assert count == 120

        # Spot-check a market from each page
        m_p1 = await get_market(migrated_pool, "0xp1_50")
        assert m_p1 is not None
        assert m_p1.question == "P1 Q50?"

        m_p2 = await get_market(migrated_pool, "0xp2_10")
        assert m_p2 is not None
        assert m_p2.question == "P2 Q10?"

    @respx.mock
    async def test_collect_once_api_error(
        self, mock_client
    ) -> None:
        """collect_once returns 0 and does not raise on API error."""
        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(500)
        )

        # pool=None is fine — we should never reach DB code on error
        collector = MarketMetadataCollector(
            pool=None,
            client=mock_client,
            config=CollectorConfig(),
        )
        count = await collector.collect_once()

        assert count == 0
