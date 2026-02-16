"""Tests for PriceSnapshotCollector.

Unit tests verify price tuple extraction logic without DB or HTTP.
Integration tests use respx to mock the Gamma API and migrated_pool
for real database writes via the COPY protocol.
"""

from datetime import datetime, timezone

import httpx
import pytest
import respx

from src.collector.price_snapshots import PriceSnapshotCollector
from src.config import CollectorConfig
from src.db.queries.prices import get_latest_prices, get_price_count
from src.utils.client import PolymarketClient

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_market(
    condition_id: str = "0xabc123",
    clob_token_ids: str = '["tok_yes","tok_no"]',
    outcome_prices: str = '["0.65","0.35"]',
    volume24hr: object = 5000,
) -> dict:
    """Build a sample Gamma API market dict with price fields."""
    market = {
        "conditionId": condition_id,
        "question": "Will X happen?",
        "slug": "will-x-happen",
        "clobTokenIds": clob_token_ids,
        "outcomePrices": outcome_prices,
        "outcomes": '["Yes","No"]',
        "active": True,
        "closed": False,
        "endDateIso": "2026-03-01T00:00:00Z",
        "marketType": "binary",
    }
    if volume24hr is not None:
        market["volume24hr"] = volume24hr
    return market


def _make_event(markets: list[dict], event_id: str = "evt_1") -> dict:
    """Wrap market dicts in an event structure."""
    return {"id": event_id, "markets": markets}


def _collector(pool=None, client=None) -> PriceSnapshotCollector:
    """Create a collector with optional pool/client overrides."""
    return PriceSnapshotCollector(
        pool=pool,
        client=client or PolymarketClient(),
        config=CollectorConfig(),
    )


# =========================================================================
# Unit tests — no DB, no respx needed
# =========================================================================


class TestExtractPriceTuples:
    """Test _extract_price_tuples transformation logic."""

    def test_extract_price_tuples_basic(self) -> None:
        """1 event with 2 markets, each having 2 tokens (YES/NO), yields 4 tuples."""
        collector = _collector()
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        events = [
            _make_event([
                _make_market(
                    condition_id="0x01",
                    clob_token_ids='["tok_a","tok_b"]',
                    outcome_prices='["0.65","0.35"]',
                    volume24hr=5000,
                ),
                _make_market(
                    condition_id="0x02",
                    clob_token_ids='["tok_c","tok_d"]',
                    outcome_prices='["0.80","0.20"]',
                    volume24hr=12000,
                ),
            ]),
        ]

        result = collector._extract_price_tuples(events, ts)

        assert len(result) == 4

        # Verify each tuple: (ts, token_id, price, volume_24h)
        by_token = {t[1]: t for t in result}

        assert by_token["tok_a"] == (ts, "tok_a", 0.65, 5000.0)
        assert by_token["tok_b"] == (ts, "tok_b", 0.35, 5000.0)
        assert by_token["tok_c"] == (ts, "tok_c", 0.80, 12000.0)
        assert by_token["tok_d"] == (ts, "tok_d", 0.20, 12000.0)

    def test_extract_price_tuples_malformed_prices(self) -> None:
        """Market with malformed outcomePrices is skipped; others still processed."""
        collector = _collector()
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        events = [
            _make_event([
                _make_market(
                    condition_id="0x_bad",
                    clob_token_ids='["tok_x","tok_y"]',
                    outcome_prices="not valid json",
                    volume24hr=100,
                ),
                _make_market(
                    condition_id="0x_good",
                    clob_token_ids='["tok_ok1","tok_ok2"]',
                    outcome_prices='["0.55","0.45"]',
                    volume24hr=200,
                ),
            ]),
        ]

        result = collector._extract_price_tuples(events, ts)

        # Only the good market produces tuples
        assert len(result) == 2
        token_ids = {t[1] for t in result}
        assert token_ids == {"tok_ok1", "tok_ok2"}

    def test_extract_price_tuples_empty_token_id(self) -> None:
        """Empty string token_id entries are skipped; truthy ones kept."""
        collector = _collector()
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        events = [
            _make_event([
                _make_market(
                    condition_id="0x_mixed",
                    clob_token_ids='["tok_a",""]',
                    outcome_prices='["0.70","0.30"]',
                    volume24hr=300,
                ),
            ]),
        ]

        result = collector._extract_price_tuples(events, ts)

        assert len(result) == 1
        assert result[0][1] == "tok_a"
        assert result[0][2] == 0.70

    def test_extract_price_tuples_missing_volume(self) -> None:
        """Market with no volume24hr field defaults volume to 0.0."""
        collector = _collector()
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        events = [
            _make_event([
                _make_market(
                    condition_id="0x_novol",
                    clob_token_ids='["tok_v1","tok_v2"]',
                    outcome_prices='["0.60","0.40"]',
                    volume24hr=None,  # triggers omission from the dict
                ),
            ]),
        ]

        result = collector._extract_price_tuples(events, ts)

        assert len(result) == 2
        for tup in result:
            assert tup[3] == 0.0


# =========================================================================
# Integration tests — respx + migrated_pool
# =========================================================================


class TestCollectOnce:
    """Integration tests for the full collect_once flow."""

    @respx.mock
    async def test_collect_once_success(
        self, migrated_pool, mock_client
    ) -> None:
        """collect_once fetches events, extracts prices, and inserts to DB."""
        events = [
            _make_event([
                _make_market(
                    condition_id="0xp1",
                    clob_token_ids='["tok_1a","tok_1b"]',
                    outcome_prices='["0.60","0.40"]',
                    volume24hr=1000,
                ),
                _make_market(
                    condition_id="0xp2",
                    clob_token_ids='["tok_2a","tok_2b"]',
                    outcome_prices='["0.75","0.25"]',
                    volume24hr=2000,
                ),
            ]),
            _make_event([
                _make_market(
                    condition_id="0xp3",
                    clob_token_ids='["tok_3a","tok_3b"]',
                    outcome_prices='["0.90","0.10"]',
                    volume24hr=3000,
                ),
            ]),
        ]

        # Mock: single page with < 100 events -> no pagination
        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(200, json=events)
        )

        collector = PriceSnapshotCollector(
            pool=migrated_pool,
            client=mock_client,
            config=CollectorConfig(),
        )
        count = await collector.collect_once()

        # 3 markets x 2 tokens each = 6 snapshots
        assert count == 6

        # Verify data persisted in DB
        row_count = await get_price_count(migrated_pool)
        assert row_count == 6

    @respx.mock
    async def test_collect_once_bulk_insert_many(
        self, migrated_pool, mock_client
    ) -> None:
        """20 markets x 2 tokens = 40 tuples all bulk-inserted via COPY."""
        markets = [
            _make_market(
                condition_id=f"0xbulk_{i}",
                clob_token_ids=f'["tok_{i}_yes","tok_{i}_no"]',
                outcome_prices=f'["{0.50 + i * 0.02:.2f}","{0.50 - i * 0.02:.2f}"]',
                volume24hr=1000 + i * 100,
            )
            for i in range(20)
        ]
        events = [_make_event(markets, event_id="evt_bulk")]

        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(200, json=events)
        )

        collector = PriceSnapshotCollector(
            pool=migrated_pool,
            client=mock_client,
            config=CollectorConfig(),
        )
        count = await collector.collect_once()

        assert count == 40

        # Spot-check a few tokens via get_latest_prices
        prices = await get_latest_prices(
            migrated_pool, ["tok_0_yes", "tok_5_no", "tok_19_yes"]
        )
        by_token = {p.token_id: p for p in prices}

        assert "tok_0_yes" in by_token
        assert by_token["tok_0_yes"].price == pytest.approx(0.50, abs=0.001)

        assert "tok_5_no" in by_token
        assert by_token["tok_5_no"].price == pytest.approx(0.40, abs=0.001)

        assert "tok_19_yes" in by_token
        assert by_token["tok_19_yes"].price == pytest.approx(0.88, abs=0.001)

    @respx.mock
    async def test_collect_once_api_error(
        self, mock_client
    ) -> None:
        """collect_once returns 0 and does not raise on API error."""
        respx.get(GAMMA_EVENTS_URL).mock(
            return_value=httpx.Response(500)
        )

        # pool=None is fine — we should never reach DB code on error
        collector = PriceSnapshotCollector(
            pool=None,
            client=mock_client,
            config=CollectorConfig(),
        )
        count = await collector.collect_once()

        assert count == 0
