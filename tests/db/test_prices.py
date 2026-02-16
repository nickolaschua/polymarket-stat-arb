"""Integration tests for price snapshot query functions.

Tests cover:
1. insert_price_snapshots with 10 records -> get_price_count returns 10
2. insert_price_snapshots with 1000 records -> all inserted (bulk performance)
3. get_latest_prices for 3 token_ids with multiple snapshots each -> returns only most recent
4. get_latest_prices with non-existent token_ids -> returns empty list
5. get_price_history with time range -> returns only snapshots within range
6. get_price_history respects limit parameter
7. insert_price_snapshots with empty list -> no error, returns 0
8. Verify data lands in hypertable (timescaledb_information.hypertables)
"""

from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from src.db.queries.prices import (
    get_latest_prices,
    get_price_count,
    get_price_history,
    insert_price_snapshots,
)


def make_price_tuple(
    token_id: str,
    price: float,
    ts: datetime | None = None,
    volume_24h: float | None = None,
) -> tuple:
    """Create a properly-typed tuple for insert_price_snapshots.

    Column order matches the COPY columns: (ts, token_id, price, volume_24h).
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    return (ts, token_id, price, volume_24h)


class TestInsertPriceSnapshots:
    """Test COPY-based bulk insert behavior."""

    async def test_insert_10_records(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_price_snapshots with 10 records -> get_price_count returns 10."""
        base_ts = datetime.now(timezone.utc)
        snapshots = [
            make_price_tuple(
                f"token_{i}",
                0.50 + i * 0.01,
                ts=base_ts + timedelta(seconds=i),
                volume_24h=1000.0 + i,
            )
            for i in range(10)
        ]

        count = await insert_price_snapshots(migrated_pool, snapshots)
        assert count == 10

        total = await get_price_count(migrated_pool)
        assert total == 10

    async def test_insert_1000_records_bulk(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_price_snapshots with 1000 records -> all inserted (bulk performance)."""
        base_ts = datetime.now(timezone.utc)
        snapshots = [
            make_price_tuple(
                f"token_{i % 50}",
                0.50 + (i % 100) * 0.001,
                ts=base_ts + timedelta(seconds=i),
                volume_24h=5000.0,
            )
            for i in range(1000)
        ]

        count = await insert_price_snapshots(migrated_pool, snapshots)
        assert count == 1000

        total = await get_price_count(migrated_pool)
        assert total == 1000

    async def test_insert_empty_list_returns_zero(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_price_snapshots with empty list -> no error, returns 0."""
        count = await insert_price_snapshots(migrated_pool, [])
        assert count == 0

        total = await get_price_count(migrated_pool)
        assert total == 0


class TestGetLatestPrices:
    """Test latest-price-per-token retrieval."""

    async def test_returns_most_recent_per_token(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_latest_prices for 3 token_ids with multiple snapshots each -> only most recent."""
        base_ts = datetime.now(timezone.utc)
        token_ids = ["tok_a", "tok_b", "tok_c"]
        snapshots = []

        # 5 snapshots per token, each 10 seconds apart
        for token_id in token_ids:
            for j in range(5):
                snapshots.append(
                    make_price_tuple(
                        token_id,
                        0.40 + j * 0.05,
                        ts=base_ts + timedelta(seconds=j * 10),
                        volume_24h=100.0,
                    )
                )

        await insert_price_snapshots(migrated_pool, snapshots)

        results = await get_latest_prices(migrated_pool, token_ids)
        assert len(results) == 3

        result_map = {r.token_id: r for r in results}
        for token_id in token_ids:
            assert token_id in result_map
            # Most recent snapshot has price 0.40 + 4*0.05 = 0.60
            assert abs(result_map[token_id].price - 0.60) < 1e-9
            # Most recent timestamp is base_ts + 40s
            expected_ts = base_ts + timedelta(seconds=40)
            assert result_map[token_id].ts == expected_ts

    async def test_nonexistent_token_ids_returns_empty(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_latest_prices with non-existent token_ids -> returns empty list."""
        results = await get_latest_prices(
            migrated_pool, ["nonexistent_1", "nonexistent_2"]
        )
        assert results == []


class TestGetPriceHistory:
    """Test time-range price history queries."""

    async def test_returns_only_within_time_range(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_price_history with time range -> returns only snapshots within range."""
        base_ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        token_id = "tok_history"
        snapshots = []

        # 20 snapshots, 1 hour apart
        for i in range(20):
            snapshots.append(
                make_price_tuple(
                    token_id,
                    0.50 + i * 0.01,
                    ts=base_ts + timedelta(hours=i),
                )
            )

        await insert_price_snapshots(migrated_pool, snapshots)

        # Query hours 5 through 14 (inclusive) -> should get 10 snapshots
        start = base_ts + timedelta(hours=5)
        end = base_ts + timedelta(hours=14)
        results = await get_price_history(migrated_pool, token_id, start, end)

        assert len(results) == 10
        # Results should be ordered by ts DESC
        for k in range(len(results) - 1):
            assert results[k].ts > results[k + 1].ts
        # Verify range boundaries
        assert results[0].ts == end  # most recent first
        assert results[-1].ts == start  # oldest last

    async def test_respects_limit_parameter(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_price_history respects limit parameter."""
        base_ts = datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        token_id = "tok_limited"
        snapshots = []

        # 50 snapshots, 1 minute apart
        for i in range(50):
            snapshots.append(
                make_price_tuple(
                    token_id,
                    0.55,
                    ts=base_ts + timedelta(minutes=i),
                )
            )

        await insert_price_snapshots(migrated_pool, snapshots)

        start = base_ts
        end = base_ts + timedelta(minutes=49)
        results = await get_price_history(
            migrated_pool, token_id, start, end, limit=10
        )

        assert len(results) == 10
        # Should return the 10 most recent (ts DESC)
        assert results[0].ts == base_ts + timedelta(minutes=49)


class TestHypertableVerification:
    """Verify price_snapshots is registered as a TimescaleDB hypertable."""

    async def test_price_snapshots_is_hypertable(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Verify data lands in hypertable (query timescaledb_information.hypertables)."""
        row = await migrated_pool.fetchrow(
            """
            SELECT hypertable_name
            FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'price_snapshots'
            """
        )
        assert row is not None
        assert row["hypertable_name"] == "price_snapshots"
