"""Integration tests for market query functions.

Tests cover:
1. upsert_market with new data inserts and is retrievable
2. upsert_market with same condition_id but updated question updates the row
3. upsert_markets with 3 markets inserts all 3
4. get_active_markets returns only active markets
5. get_markets_by_ids returns matching markets using ANY($1::text[])
"""

import asyncio

import asyncpg
import pytest

from src.db.queries.markets import (
    get_active_markets,
    get_market,
    get_markets_by_ids,
    upsert_market,
    upsert_markets,
)


class TestUpsertMarket:
    """Test upsert_market insert and update behavior."""

    async def test_upsert_new_market_inserts(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """upsert_market with new data inserts the row and get_market returns it."""
        market_data = {
            "condition_id": "0x_test_condition_001",
            "question": "Will BTC hit $100k by end of 2026?",
            "slug": "btc-100k-2026",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["token_yes_001", "token_no_001"],
            "active": True,
            "closed": False,
            "end_date_iso": "2026-12-31T00:00:00Z",
        }

        await upsert_market(migrated_pool, market_data)

        result = await get_market(migrated_pool, "0x_test_condition_001")
        assert result is not None
        assert result.condition_id == "0x_test_condition_001"
        assert result.question == "Will BTC hit $100k by end of 2026?"
        assert result.slug == "btc-100k-2026"
        assert result.market_type == "binary"
        assert result.outcomes == ["Yes", "No"]
        assert result.clob_token_ids == ["token_yes_001", "token_no_001"]
        assert result.active is True
        assert result.closed is False

    async def test_upsert_existing_market_updates(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """upsert_market with same condition_id but different question updates the row."""
        market_data = {
            "condition_id": "0x_test_condition_update",
            "question": "Original question?",
            "slug": "original-slug",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_a", "tok_b"],
            "active": True,
            "closed": False,
            "end_date_iso": None,
        }

        await upsert_market(migrated_pool, market_data)
        original = await get_market(migrated_pool, "0x_test_condition_update")
        assert original is not None
        original_updated_at = original.updated_at

        # Small delay to ensure updated_at changes
        await asyncio.sleep(0.05)

        # Upsert again with updated question
        market_data["question"] = "Updated question?"
        market_data["slug"] = "updated-slug"
        await upsert_market(migrated_pool, market_data)

        updated = await get_market(migrated_pool, "0x_test_condition_update")
        assert updated is not None
        assert updated.question == "Updated question?"
        assert updated.slug == "updated-slug"
        assert updated.updated_at > original_updated_at


class TestUpsertMarkets:
    """Test batch upsert behavior."""

    async def test_upsert_multiple_markets(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """upsert_markets with 3 markets inserts all 3."""
        markets = [
            {
                "condition_id": f"0x_batch_{i}",
                "question": f"Batch question {i}?",
                "slug": f"batch-{i}",
                "market_type": "binary",
                "outcomes": ["Yes", "No"],
                "clob_token_ids": [f"tok_y_{i}", f"tok_n_{i}"],
                "active": True,
                "closed": False,
                "end_date_iso": None,
            }
            for i in range(3)
        ]

        await upsert_markets(migrated_pool, markets)

        for i in range(3):
            result = await get_market(migrated_pool, f"0x_batch_{i}")
            assert result is not None, f"Market 0x_batch_{i} not found"
            assert result.question == f"Batch question {i}?"


class TestGetActiveMarkets:
    """Test active market filtering."""

    async def test_get_active_markets_filters_inactive(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_active_markets returns only markets where active=True."""
        # Insert one active and one inactive market
        active_market = {
            "condition_id": "0x_active_market",
            "question": "Active market?",
            "slug": "active",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_y", "tok_n"],
            "active": True,
            "closed": False,
            "end_date_iso": None,
        }
        inactive_market = {
            "condition_id": "0x_inactive_market",
            "question": "Inactive market?",
            "slug": "inactive",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_y2", "tok_n2"],
            "active": False,
            "closed": True,
            "end_date_iso": None,
        }

        await upsert_market(migrated_pool, active_market)
        await upsert_market(migrated_pool, inactive_market)

        active_results = await get_active_markets(migrated_pool)
        condition_ids = [m.condition_id for m in active_results]

        assert "0x_active_market" in condition_ids
        assert "0x_inactive_market" not in condition_ids


class TestGetMarketsByIds:
    """Test fetching markets by a list of condition_ids."""

    async def test_get_markets_by_ids_returns_matching(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_markets_by_ids returns only the requested markets."""
        # Insert 3 markets
        for i in range(3):
            await upsert_market(migrated_pool, {
                "condition_id": f"0x_byid_{i}",
                "question": f"By ID question {i}?",
                "slug": f"byid-{i}",
                "market_type": "binary",
                "outcomes": ["Yes", "No"],
                "clob_token_ids": [f"tok_{i}_y", f"tok_{i}_n"],
                "active": True,
                "closed": False,
                "end_date_iso": None,
            })

        # Request only 2 of the 3
        results = await get_markets_by_ids(
            migrated_pool, ["0x_byid_0", "0x_byid_2"]
        )
        result_ids = {m.condition_id for m in results}

        assert result_ids == {"0x_byid_0", "0x_byid_2"}
        assert "0x_byid_1" not in result_ids
