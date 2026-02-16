"""Tests for OrderbookSnapshotCollector.

Unit tests verify orderbook tuple extraction logic without DB or CLOB.
Integration tests use migrated_pool for real database writes and mock
the _fetch_orderbooks method to avoid needing a live CLOB API.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.collector.orderbook_snapshots import OrderbookSnapshotCollector
from src.config import CollectorConfig
from src.db.queries.markets import upsert_market
from src.db.queries.orderbooks import get_latest_orderbook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collector(pool=None, client=None) -> OrderbookSnapshotCollector:
    """Create a collector with optional pool/client overrides."""
    return OrderbookSnapshotCollector(
        pool=pool,
        client=client,
        config=CollectorConfig(),
    )


def _make_book(
    bids: list[tuple[str, str]] | None = None,
    asks: list[tuple[str, str]] | None = None,
) -> dict:
    """Build a CLOB orderbook dict.

    Parameters
    ----------
    bids:
        List of (price, size) string pairs, or None for empty.
    asks:
        List of (price, size) string pairs, or None for empty.
    """
    return {
        "bids": [{"price": p, "size": s} for p, s in (bids or [])],
        "asks": [{"price": p, "size": s} for p, s in (asks or [])],
    }


async def _insert_active_market(
    pool, condition_id: str, token_ids: list[str]
) -> None:
    """Insert an active market with the given token IDs."""
    await upsert_market(
        pool,
        {
            "condition_id": condition_id,
            "question": f"Market {condition_id}?",
            "slug": f"market-{condition_id}",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": token_ids,
            "active": True,
            "closed": False,
            "end_date_iso": "2026-06-01T00:00:00Z",
        },
    )


# =========================================================================
# Unit tests -- no DB, no CLOB needed
# =========================================================================


class TestExtractOrderbookTuple:
    """Test _extract_orderbook_tuple transformation logic."""

    def test_extract_orderbook_tuple_basic(self) -> None:
        """CLOB book with 3 bids and 3 asks produces correct tuple."""
        collector = _collector()
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        book = _make_book(
            bids=[("0.55", "100"), ("0.54", "200"), ("0.53", "150")],
            asks=[("0.56", "100"), ("0.57", "200"), ("0.58", "300")],
        )

        result = collector._extract_orderbook_tuple("tok_abc", book, ts)

        assert result[0] == ts
        assert result[1] == "tok_abc"

        # Bids dict
        bids_dict = result[2]
        assert bids_dict == {
            "levels": [[0.55, 100.0], [0.54, 200.0], [0.53, 150.0]]
        }

        # Asks dict
        asks_dict = result[3]
        assert asks_dict == {
            "levels": [[0.56, 100.0], [0.57, 200.0], [0.58, 300.0]]
        }

        # Spread: 0.56 - 0.55 = 0.01
        assert result[4] == pytest.approx(0.01, abs=1e-9)

        # Midpoint: (0.55 + 0.56) / 2 = 0.555
        assert result[5] == pytest.approx(0.555, abs=1e-9)

    def test_extract_orderbook_tuple_empty_book(self) -> None:
        """Empty bids and asks produce empty levels and None spread/midpoint."""
        collector = _collector()
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        book = _make_book(bids=[], asks=[])

        result = collector._extract_orderbook_tuple("tok_empty", book, ts)

        assert result[0] == ts
        assert result[1] == "tok_empty"
        assert result[2] == {"levels": []}
        assert result[3] == {"levels": []}
        assert result[4] is None  # spread
        assert result[5] is None  # midpoint

    def test_extract_orderbook_tuple_one_sided(self) -> None:
        """Book with bids but no asks has None spread/midpoint, bids extracted."""
        collector = _collector()
        ts = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

        book = _make_book(
            bids=[("0.50", "500"), ("0.49", "300")],
            asks=[],
        )

        result = collector._extract_orderbook_tuple("tok_onesided", book, ts)

        assert result[0] == ts
        assert result[1] == "tok_onesided"
        assert result[2] == {"levels": [[0.50, 500.0], [0.49, 300.0]]}
        assert result[3] == {"levels": []}
        assert result[4] is None  # spread
        assert result[5] is None  # midpoint


# =========================================================================
# Integration tests -- migrated_pool + mocked CLOB
# =========================================================================


class TestCollectOnce:
    """Integration tests for the full collect_once flow."""

    async def test_collect_once_success(self, migrated_pool) -> None:
        """Pre-insert 2 active markets (4 tokens), verify 4 snapshots inserted."""
        # Insert 2 active markets with 2 tokens each
        await _insert_active_market(
            migrated_pool, "0xob_m1", ["tok_m1_yes", "tok_m1_no"]
        )
        await _insert_active_market(
            migrated_pool, "0xob_m2", ["tok_m2_yes", "tok_m2_no"]
        )

        collector = _collector(pool=migrated_pool)

        # Mock _fetch_orderbooks to return realistic books
        async def mock_fetch(token_ids):
            return [
                _make_book(
                    bids=[("0.55", "100"), ("0.54", "200")],
                    asks=[("0.56", "100"), ("0.57", "200")],
                )
                for _ in token_ids
            ]

        with patch.object(collector, "_fetch_orderbooks", side_effect=mock_fetch):
            count = await collector.collect_once()

        assert count == 4

        # Verify data persisted in DB
        ob = await get_latest_orderbook(migrated_pool, "tok_m1_yes")
        assert ob is not None
        assert ob.token_id == "tok_m1_yes"
        assert ob.spread == pytest.approx(0.01, abs=1e-9)
        assert ob.midpoint == pytest.approx(0.555, abs=1e-9)

    async def test_collect_once_no_active_markets(self, migrated_pool) -> None:
        """No active markets in DB returns 0."""
        collector = _collector(pool=migrated_pool)
        count = await collector.collect_once()

        assert count == 0

    async def test_collect_once_clob_error(self, migrated_pool) -> None:
        """CLOB error in _fetch_orderbooks returns 0 and does not crash."""
        # Insert a market so we have tokens to fetch
        await _insert_active_market(
            migrated_pool, "0xob_err", ["tok_err_yes", "tok_err_no"]
        )

        collector = _collector(pool=migrated_pool)

        # Mock _fetch_orderbooks to raise an exception
        with patch.object(
            collector,
            "_fetch_orderbooks",
            new_callable=AsyncMock,
            side_effect=Exception("CLOB timeout"),
        ):
            count = await collector.collect_once()

        assert count == 0

    async def test_chunking_behavior(self, migrated_pool) -> None:
        """50 tokens are chunked into 3 batches (20, 20, 10)."""
        # Create markets with 50 total token IDs
        # 25 markets with 2 tokens each = 50 tokens
        for i in range(25):
            await _insert_active_market(
                migrated_pool,
                f"0xob_chunk_{i}",
                [f"tok_chunk_{i}_yes", f"tok_chunk_{i}_no"],
            )

        collector = _collector(pool=migrated_pool)

        mock_fetch = AsyncMock()

        def fetch_side_effect(token_ids):
            return [
                _make_book(
                    bids=[("0.50", "100")],
                    asks=[("0.51", "100")],
                )
                for _ in token_ids
            ]

        mock_fetch.side_effect = fetch_side_effect

        with patch.object(collector, "_fetch_orderbooks", mock_fetch):
            count = await collector.collect_once()

        # 50 tokens / 20 per chunk = 3 calls (20, 20, 10)
        assert mock_fetch.call_count == 3

        # Verify chunk sizes
        call_args = [call.args[0] for call in mock_fetch.call_args_list]
        chunk_sizes = [len(args) for args in call_args]
        assert chunk_sizes == [20, 20, 10]

        # All 50 tokens should be inserted
        assert count == 50
