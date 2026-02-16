"""Integration tests for trade query functions.

Tests cover:
1. insert_trades with 5 records -> all inserted
2. insert_trades with 500 records -> bulk insert works
3. get_recent_trades with limit -> respects limit, ordered by ts DESC
4. get_trade_count with no filter -> total count
5. get_trade_count with token_id filter -> filtered count
6. Duplicate trade_id handling
"""

from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from src.db.queries.trades import (
    get_recent_trades,
    get_trade_count,
    insert_trades,
)


def make_trade_tuple(
    token_id: str,
    side: str = "BUY",
    price: float = 0.55,
    size: float = 10.0,
    trade_id: str | None = None,
    ts: datetime | None = None,
) -> tuple:
    """Create a properly-typed tuple for insert_trades.

    Column order matches: (ts, token_id, side, price, size, trade_id).
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    return (ts, token_id, side, price, size, trade_id)


class TestInsertTrades:
    """Test COPY-based bulk insert behavior for trades."""

    async def test_insert_5_records(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_trades with 5 records -> all inserted."""
        base_ts = datetime.now(timezone.utc)
        trades = [
            make_trade_tuple(
                f"tok_trade_{i}",
                side="BUY" if i % 2 == 0 else "SELL",
                price=0.50 + i * 0.01,
                size=10.0 + i,
                trade_id=f"trade_5_{i}",
                ts=base_ts + timedelta(seconds=i),
            )
            for i in range(5)
        ]

        count = await insert_trades(migrated_pool, trades)
        assert count == 5

        total = await get_trade_count(migrated_pool)
        assert total == 5

    async def test_insert_500_records_bulk(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_trades with 500 records -> bulk insert works."""
        base_ts = datetime.now(timezone.utc)
        trades = [
            make_trade_tuple(
                f"tok_bulk_{i % 10}",
                side="BUY" if i % 2 == 0 else "SELL",
                price=0.50 + (i % 50) * 0.001,
                size=5.0 + (i % 20),
                trade_id=f"trade_500_{i}",
                ts=base_ts + timedelta(milliseconds=i),
            )
            for i in range(500)
        ]

        count = await insert_trades(migrated_pool, trades)
        assert count == 500

        total = await get_trade_count(migrated_pool)
        assert total == 500

    async def test_insert_empty_list_returns_zero(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_trades with empty list -> no error, returns 0."""
        count = await insert_trades(migrated_pool, [])
        assert count == 0

        total = await get_trade_count(migrated_pool)
        assert total == 0


class TestGetRecentTrades:
    """Test recent trades retrieval with ordering and limits."""

    async def test_respects_limit_and_order(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_recent_trades with limit -> respects limit, ordered by ts DESC."""
        base_ts = datetime.now(timezone.utc)
        token_id = "tok_recent"

        # Insert 20 trades
        trades = [
            make_trade_tuple(
                token_id,
                side="BUY",
                price=0.50 + i * 0.01,
                size=10.0,
                trade_id=f"trade_recent_{i}",
                ts=base_ts + timedelta(seconds=i),
            )
            for i in range(20)
        ]

        await insert_trades(migrated_pool, trades)

        # Request only 5 most recent
        results = await get_recent_trades(migrated_pool, token_id, limit=5)

        assert len(results) == 5
        # Most recent first (ts DESC)
        for k in range(len(results) - 1):
            assert results[k].ts > results[k + 1].ts
        # The most recent trade has the highest price
        assert abs(results[0].price - (0.50 + 19 * 0.01)) < 1e-9

    async def test_returns_empty_for_nonexistent_token(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_recent_trades for nonexistent token_id -> empty list."""
        results = await get_recent_trades(migrated_pool, "tok_nonexistent")
        assert results == []


class TestGetTradeCount:
    """Test trade count with optional filtering."""

    async def test_count_no_filter(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_trade_count with no filter -> total count."""
        base_ts = datetime.now(timezone.utc)
        trades = [
            make_trade_tuple(
                f"tok_count_{i % 3}",
                side="BUY",
                price=0.55,
                size=10.0,
                trade_id=f"trade_count_{i}",
                ts=base_ts + timedelta(seconds=i),
            )
            for i in range(9)
        ]

        await insert_trades(migrated_pool, trades)

        total = await get_trade_count(migrated_pool)
        assert total == 9

    async def test_count_with_token_id_filter(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_trade_count with token_id filter -> filtered count."""
        base_ts = datetime.now(timezone.utc)
        trades = [
            make_trade_tuple(
                f"tok_filter_{i % 3}",
                side="BUY",
                price=0.55,
                size=10.0,
                trade_id=f"trade_filter_{i}",
                ts=base_ts + timedelta(seconds=i),
            )
            for i in range(9)
        ]

        await insert_trades(migrated_pool, trades)

        # Each token_id should have 3 trades (9 trades / 3 token_ids)
        count_0 = await get_trade_count(migrated_pool, token_id="tok_filter_0")
        assert count_0 == 3

        count_1 = await get_trade_count(migrated_pool, token_id="tok_filter_1")
        assert count_1 == 3


class TestDuplicateTradeId:
    """Test duplicate trade_id handling."""

    async def test_duplicate_trade_id_handled_gracefully(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Duplicate trade_id: second insert with same trade_ids doesn't raise, count unchanged."""
        base_ts = datetime.now(timezone.utc)
        trades = [
            make_trade_tuple(
                "tok_dup",
                side="BUY",
                price=0.55,
                size=10.0,
                trade_id="dup_trade_001",
                ts=base_ts,
            ),
            make_trade_tuple(
                "tok_dup",
                side="SELL",
                price=0.56,
                size=20.0,
                trade_id="dup_trade_002",
                ts=base_ts + timedelta(seconds=1),
            ),
        ]

        count1 = await insert_trades(migrated_pool, trades)
        assert count1 == 2

        # Insert same trades again — should handle duplicates gracefully
        count2 = await insert_trades(migrated_pool, trades)
        # The function should not raise; duplicates are skipped

        # Total should still be 2 (not 4)
        total = await get_trade_count(migrated_pool)
        assert total == 2
