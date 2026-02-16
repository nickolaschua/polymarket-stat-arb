"""Integration tests for resolution query functions.

Tests cover:
1. upsert_resolution with new data inserts and is retrievable
2. upsert_resolution with updated outcome updates the existing row
3. get_unresolved_markets returns condition_ids of closed markets with no resolution
"""

from datetime import datetime, timezone

import asyncpg
import pytest

from src.db.queries.markets import upsert_market
from src.db.queries.resolutions import (
    get_resolution,
    get_unresolved_markets,
    upsert_resolution,
)


class TestUpsertResolution:
    """Test upsert_resolution insert and update behavior."""

    async def test_upsert_new_resolution_inserts(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """upsert_resolution with new data inserts the row and get_resolution returns it."""
        # Must have a market row first (foreign key or logical requirement)
        await upsert_market(migrated_pool, {
            "condition_id": "0x_resolved_001",
            "question": "Will it resolve?",
            "slug": "resolve-test",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_y", "tok_n"],
            "active": False,
            "closed": True,
            "end_date_iso": None,
        })

        resolution_data = {
            "condition_id": "0x_resolved_001",
            "outcome": "Yes",
            "winner_token_id": "tok_y",
            "resolved_at": datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc),
            "payout_price": 1.0,
            "detection_method": "gamma_api",
        }

        await upsert_resolution(migrated_pool, resolution_data)

        result = await get_resolution(migrated_pool, "0x_resolved_001")
        assert result is not None
        assert result.condition_id == "0x_resolved_001"
        assert result.outcome == "Yes"
        assert result.winner_token_id == "tok_y"
        assert result.payout_price == 1.0
        assert result.detection_method == "gamma_api"

    async def test_upsert_resolution_updates_existing(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """upsert_resolution with same condition_id but different outcome updates the row."""
        await upsert_market(migrated_pool, {
            "condition_id": "0x_resolved_update",
            "question": "Will it update?",
            "slug": "update-test",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_y", "tok_n"],
            "active": False,
            "closed": True,
            "end_date_iso": None,
        })

        # Initial resolution
        await upsert_resolution(migrated_pool, {
            "condition_id": "0x_resolved_update",
            "outcome": "Yes",
            "winner_token_id": "tok_y",
            "resolved_at": datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc),
            "payout_price": 1.0,
            "detection_method": "final_price",
        })

        # Update resolution with different outcome
        await upsert_resolution(migrated_pool, {
            "condition_id": "0x_resolved_update",
            "outcome": "No",
            "winner_token_id": "tok_n",
            "resolved_at": datetime(2026, 2, 16, 8, 0, 0, tzinfo=timezone.utc),
            "payout_price": 0.0,
            "detection_method": "gamma_api",
        })

        result = await get_resolution(migrated_pool, "0x_resolved_update")
        assert result is not None
        assert result.outcome == "No"
        assert result.winner_token_id == "tok_n"
        assert result.payout_price == 0.0
        assert result.detection_method == "gamma_api"


class TestGetUnresolvedMarkets:
    """Test get_unresolved_markets join query."""

    async def test_get_unresolved_returns_closed_without_resolution(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_unresolved_markets returns condition_ids of closed markets with no resolution."""
        # Insert a closed market WITH a resolution
        await upsert_market(migrated_pool, {
            "condition_id": "0x_has_resolution",
            "question": "Resolved market?",
            "slug": "resolved",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_y", "tok_n"],
            "active": False,
            "closed": True,
            "end_date_iso": None,
        })
        await upsert_resolution(migrated_pool, {
            "condition_id": "0x_has_resolution",
            "outcome": "Yes",
            "winner_token_id": "tok_y",
            "resolved_at": datetime(2026, 2, 15, 12, 0, 0, tzinfo=timezone.utc),
            "payout_price": 1.0,
            "detection_method": "gamma_api",
        })

        # Insert a closed market WITHOUT a resolution
        await upsert_market(migrated_pool, {
            "condition_id": "0x_no_resolution",
            "question": "Unresolved closed market?",
            "slug": "unresolved",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_y2", "tok_n2"],
            "active": False,
            "closed": True,
            "end_date_iso": None,
        })

        # Insert an active market (should NOT appear in unresolved)
        await upsert_market(migrated_pool, {
            "condition_id": "0x_still_active",
            "question": "Still active market?",
            "slug": "active",
            "market_type": "binary",
            "outcomes": ["Yes", "No"],
            "clob_token_ids": ["tok_y3", "tok_n3"],
            "active": True,
            "closed": False,
            "end_date_iso": None,
        })

        unresolved = await get_unresolved_markets(migrated_pool)

        assert "0x_no_resolution" in unresolved
        assert "0x_has_resolution" not in unresolved
        assert "0x_still_active" not in unresolved
