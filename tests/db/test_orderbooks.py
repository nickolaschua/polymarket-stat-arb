"""Integration tests for orderbook snapshot query functions.

Tests cover:
1. insert_orderbook_snapshots with JSONB dicts -> inserted, queryable
2. get_latest_orderbook -> returns most recent snapshot with correct bids/asks dicts
3. get_orderbook_history with time range -> correct filtering
4. JSONB round-trip: inserted dict == queried dict (no data loss)
5. Empty bids/asks (None) -> stored and returned as None
"""

from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from src.db.queries.orderbooks import (
    get_latest_orderbook,
    get_orderbook_history,
    insert_orderbook_snapshots,
)


def make_orderbook_tuple(
    token_id: str,
    bids: dict | list | None = None,
    asks: dict | list | None = None,
    spread: float | None = 0.02,
    midpoint: float | None = 0.50,
    ts: datetime | None = None,
) -> tuple:
    """Create a properly-typed tuple for insert_orderbook_snapshots.

    Column order matches: (ts, token_id, bids, asks, spread, midpoint).
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    return (ts, token_id, bids, asks, spread, midpoint)


class TestInsertOrderbookSnapshots:
    """Test COPY/batch insert behavior for orderbook snapshots."""

    async def test_insert_and_query(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_orderbook_snapshots with JSONB dicts -> inserted, queryable."""
        base_ts = datetime.now(timezone.utc)
        bids = {"levels": [[0.48, 100], [0.47, 200]]}
        asks = {"levels": [[0.52, 150], [0.53, 250]]}

        snapshots = [
            make_orderbook_tuple(
                "tok_ob_1",
                bids=bids,
                asks=asks,
                spread=0.04,
                midpoint=0.50,
                ts=base_ts,
            ),
            make_orderbook_tuple(
                "tok_ob_2",
                bids={"levels": [[0.30, 50]]},
                asks={"levels": [[0.70, 50]]},
                spread=0.40,
                midpoint=0.50,
                ts=base_ts + timedelta(seconds=1),
            ),
        ]

        count = await insert_orderbook_snapshots(migrated_pool, snapshots)
        assert count == 2

        # Verify data is queryable
        row = await migrated_pool.fetchrow(
            "SELECT count(*) AS cnt FROM orderbook_snapshots"
        )
        assert row["cnt"] == 2

    async def test_insert_empty_list_returns_zero(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """insert_orderbook_snapshots with empty list -> no error, returns 0."""
        count = await insert_orderbook_snapshots(migrated_pool, [])
        assert count == 0


class TestGetLatestOrderbook:
    """Test latest orderbook retrieval."""

    async def test_returns_most_recent_snapshot(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_latest_orderbook -> returns most recent snapshot with correct bids/asks dicts."""
        base_ts = datetime.now(timezone.utc)
        token_id = "tok_latest_ob"

        # Insert 3 snapshots at different times
        snapshots = [
            make_orderbook_tuple(
                token_id,
                bids={"levels": [[0.48, 100]]},
                asks={"levels": [[0.52, 100]]},
                spread=0.04,
                midpoint=0.50,
                ts=base_ts,
            ),
            make_orderbook_tuple(
                token_id,
                bids={"levels": [[0.49, 200]]},
                asks={"levels": [[0.51, 200]]},
                spread=0.02,
                midpoint=0.50,
                ts=base_ts + timedelta(seconds=10),
            ),
            make_orderbook_tuple(
                token_id,
                bids={"levels": [[0.495, 300]]},
                asks={"levels": [[0.505, 300]]},
                spread=0.01,
                midpoint=0.50,
                ts=base_ts + timedelta(seconds=20),
            ),
        ]

        await insert_orderbook_snapshots(migrated_pool, snapshots)

        result = await get_latest_orderbook(migrated_pool, token_id)
        assert result is not None
        assert result.token_id == token_id
        assert result.ts == base_ts + timedelta(seconds=20)
        assert result.bids == {"levels": [[0.495, 300]]}
        assert result.asks == {"levels": [[0.505, 300]]}
        assert abs(result.spread - 0.01) < 1e-9
        assert abs(result.midpoint - 0.50) < 1e-9

    async def test_returns_none_for_nonexistent(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_latest_orderbook for nonexistent token_id -> None."""
        result = await get_latest_orderbook(migrated_pool, "tok_nonexistent")
        assert result is None


class TestGetOrderbookHistory:
    """Test time-range orderbook history queries."""

    async def test_filters_by_time_range(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_orderbook_history with time range -> correct filtering."""
        base_ts = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        token_id = "tok_ob_history"

        # Insert 10 snapshots, 1 hour apart
        snapshots = [
            make_orderbook_tuple(
                token_id,
                bids={"levels": [[0.48, 100 + i]]},
                asks={"levels": [[0.52, 100 + i]]},
                spread=0.04,
                midpoint=0.50,
                ts=base_ts + timedelta(hours=i),
            )
            for i in range(10)
        ]

        await insert_orderbook_snapshots(migrated_pool, snapshots)

        # Query hours 3 through 7 (inclusive) -> 5 snapshots
        start = base_ts + timedelta(hours=3)
        end = base_ts + timedelta(hours=7)
        results = await get_orderbook_history(
            migrated_pool, token_id, start, end
        )

        assert len(results) == 5
        # Results should be ordered by ts DESC
        for k in range(len(results) - 1):
            assert results[k].ts > results[k + 1].ts
        assert results[0].ts == end
        assert results[-1].ts == start

    async def test_respects_limit(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """get_orderbook_history respects limit parameter."""
        base_ts = datetime(2026, 2, 5, 0, 0, 0, tzinfo=timezone.utc)
        token_id = "tok_ob_limited"

        snapshots = [
            make_orderbook_tuple(
                token_id,
                bids={"levels": [[0.48, 100]]},
                asks={"levels": [[0.52, 100]]},
                spread=0.04,
                midpoint=0.50,
                ts=base_ts + timedelta(minutes=i),
            )
            for i in range(20)
        ]

        await insert_orderbook_snapshots(migrated_pool, snapshots)

        start = base_ts
        end = base_ts + timedelta(minutes=19)
        results = await get_orderbook_history(
            migrated_pool, token_id, start, end, limit=5
        )

        assert len(results) == 5
        # Most recent first
        assert results[0].ts == base_ts + timedelta(minutes=19)


class TestJsonbRoundTrip:
    """Test JSONB data integrity through insert and query cycle."""

    async def test_complex_dict_round_trip(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """JSONB round-trip: inserted dict == queried dict (no data loss)."""
        base_ts = datetime.now(timezone.utc)
        token_id = "tok_jsonb_rt"

        complex_bids = {
            "levels": [
                [0.495, 1500.25],
                [0.490, 3000.50],
                [0.485, 5000.75],
            ],
            "total_size": 9501.50,
        }
        complex_asks = {
            "levels": [
                [0.505, 1200.00],
                [0.510, 2400.00],
                [0.515, 4800.00],
            ],
            "total_size": 8400.00,
        }

        snapshots = [
            make_orderbook_tuple(
                token_id,
                bids=complex_bids,
                asks=complex_asks,
                spread=0.01,
                midpoint=0.50,
                ts=base_ts,
            )
        ]

        await insert_orderbook_snapshots(migrated_pool, snapshots)

        result = await get_latest_orderbook(migrated_pool, token_id)
        assert result is not None
        assert result.bids == complex_bids
        assert result.asks == complex_asks

    async def test_none_bids_asks_round_trip(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Empty bids/asks (None) -> stored and returned as None."""
        base_ts = datetime.now(timezone.utc)
        token_id = "tok_none_ob"

        snapshots = [
            make_orderbook_tuple(
                token_id,
                bids=None,
                asks=None,
                spread=None,
                midpoint=None,
                ts=base_ts,
            )
        ]

        await insert_orderbook_snapshots(migrated_pool, snapshots)

        result = await get_latest_orderbook(migrated_pool, token_id)
        assert result is not None
        assert result.bids is None
        assert result.asks is None
        assert result.spread is None
        assert result.midpoint is None
