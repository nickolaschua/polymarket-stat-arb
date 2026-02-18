"""Integration tests for feature query functions.

Tests cover all functions in src/db/queries/features.py using a
TimescaleDB testcontainer with synthetic data inserts.

Test cases:
1. get_price_returns - basic return computation, empty table
2. get_rolling_volatility - stddev of returns, insufficient data
3. get_spread_history - time-filtered spread records
4. get_orderbook_imbalance - bid/ask volume ratio, zero-volume edge case
5. get_trade_volume_profile - buy/sell split and count
6. get_market_features - combined features for a market's tokens
"""

import json
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from src.db.queries.features import (
    get_market_features,
    get_orderbook_imbalance,
    get_price_returns,
    get_rolling_volatility,
    get_spread_history,
    get_trade_volume_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


BASE_TS = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
TOKEN_A = "token_a_0001"
TOKEN_B = "token_b_0002"
CONDITION_ID = "cond_test_0001"


async def _insert_prices(
    pool: asyncpg.Pool,
    token_id: str,
    prices: list[float],
    start: datetime = BASE_TS,
    interval_minutes: int = 1,
) -> None:
    """Insert synthetic price snapshots."""
    records = [
        (start + timedelta(minutes=i * interval_minutes), token_id, price, None)
        for i, price in enumerate(prices)
    ]
    await pool.copy_records_to_table(
        "price_snapshots",
        records=records,
        columns=["ts", "token_id", "price", "volume_24h"],
    )


async def _insert_orderbook(
    pool: asyncpg.Pool,
    token_id: str,
    bids: list,
    asks: list,
    spread: float | None = None,
    midpoint: float | None = None,
    ts: datetime | None = None,
) -> None:
    """Insert a single synthetic orderbook snapshot."""
    ts = ts or BASE_TS
    await pool.execute(
        """
        INSERT INTO orderbook_snapshots (ts, token_id, bids, asks, spread, midpoint)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
        """,
        ts,
        token_id,
        json.dumps(bids),
        json.dumps(asks),
        spread,
        midpoint,
    )


async def _insert_trades(
    pool: asyncpg.Pool,
    token_id: str,
    trades: list[tuple[str, float, float]],
    start: datetime = BASE_TS,
) -> None:
    """Insert synthetic trades.  Each tuple is (side, price, size)."""
    records = []
    for i, (side, price, size) in enumerate(trades):
        records.append(
            (
                start + timedelta(minutes=i),
                token_id,
                side,
                price,
                size,
                f"trade_{i:04d}",
            )
        )
    await pool.executemany(
        """
        INSERT INTO trades (ts, token_id, side, price, size, trade_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        records,
    )


async def _insert_market(
    pool: asyncpg.Pool,
    condition_id: str,
    token_ids: list[str],
) -> None:
    """Insert a minimal market row."""
    await pool.execute(
        """
        INSERT INTO markets (
            condition_id, question, slug, market_type,
            outcomes, clob_token_ids, active, closed, end_date_iso
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (condition_id) DO NOTHING
        """,
        condition_id,
        "Test market question?",
        "test-market",
        "binary",
        ["YES", "NO"],
        token_ids,
        True,
        False,
        None,
    )


# ---------------------------------------------------------------------------
# Phase 1.1 — get_price_returns
# ---------------------------------------------------------------------------


class TestGetPriceReturns:
    """Test percentage return computation via LAG() window function."""

    async def test_returns_computed_correctly(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Returns between known price steps should match manual calculation."""
        # Prices: 0.50, 0.55, 0.60, 0.50  -> returns 10%, 9.09%, -16.67%
        prices = [0.50, 0.55, 0.60, 0.50]
        await _insert_prices(migrated_pool, TOKEN_A, prices, interval_minutes=60)

        results = await get_price_returns(
            migrated_pool, TOKEN_A, interval="1h", lookback_hours=48
        )

        assert len(results) == 3
        ts_vals, return_vals = zip(*results)
        # 0.50 -> 0.55: +10%
        assert abs(return_vals[0] - 10.0) < 1e-6
        # 0.55 -> 0.60: ~+9.09%
        assert abs(return_vals[1] - (5 / 55 * 100)) < 1e-6
        # 0.60 -> 0.50: ~-16.67%
        assert abs(return_vals[2] - (-10 / 60 * 100)) < 1e-6

    async def test_empty_table_returns_empty_list(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """No data for token_id returns empty list (not an error)."""
        results = await get_price_returns(
            migrated_pool, "nonexistent_token", lookback_hours=24
        )
        assert results == []

    async def test_single_row_no_returns(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """A single price point yields no returns (LAG produces NULL)."""
        await _insert_prices(migrated_pool, TOKEN_A, [0.60], interval_minutes=60)
        results = await get_price_returns(
            migrated_pool, TOKEN_A, interval="1h", lookback_hours=24
        )
        assert results == []


# ---------------------------------------------------------------------------
# Phase 1.2 — get_rolling_volatility
# ---------------------------------------------------------------------------


class TestGetRollingVolatility:
    """Test standard deviation of 1-minute returns."""

    async def test_constant_price_zero_volatility(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Constant price yields zero standard deviation."""
        prices = [0.50] * 30
        await _insert_prices(migrated_pool, TOKEN_A, prices)

        vol = await get_rolling_volatility(migrated_pool, TOKEN_A, window_hours=2)
        # stddev of all-zero returns is 0 (or None if DB returns 0)
        assert vol == 0.0 or vol is None

    async def test_volatile_prices_nonzero(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Varying prices produce non-zero volatility."""
        import math

        prices = [0.50 + 0.05 * math.sin(i * 0.5) for i in range(60)]
        await _insert_prices(migrated_pool, TOKEN_A, prices)

        vol = await get_rolling_volatility(migrated_pool, TOKEN_A, window_hours=2)
        assert vol is not None
        assert vol > 0.0

    async def test_no_data_returns_none(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Token with no data returns None."""
        vol = await get_rolling_volatility(
            migrated_pool, "nonexistent_token", window_hours=24
        )
        assert vol is None


# ---------------------------------------------------------------------------
# Phase 1.3 — get_spread_history
# ---------------------------------------------------------------------------


class TestGetSpreadHistory:
    """Test spread and midpoint history retrieval."""

    async def test_returns_within_lookback(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Only snapshots within the lookback window are returned."""
        now = datetime.now(timezone.utc)
        # Insert one recent and one old snapshot
        await _insert_orderbook(
            migrated_pool, TOKEN_A, [], [], spread=0.02, midpoint=0.50,
            ts=now - timedelta(hours=1),
        )
        await _insert_orderbook(
            migrated_pool, TOKEN_A, [], [], spread=0.05, midpoint=0.40,
            ts=now - timedelta(hours=48),
        )

        results = await get_spread_history(
            migrated_pool, TOKEN_A, lookback_hours=24
        )
        assert len(results) == 1
        ts, spread, midpoint = results[0]
        assert abs(spread - 0.02) < 1e-9
        assert abs(midpoint - 0.50) < 1e-9

    async def test_ordered_ascending(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Results are ordered oldest-first."""
        now = datetime.now(timezone.utc)
        for i in range(3):
            await _insert_orderbook(
                migrated_pool, TOKEN_A, [], [],
                spread=float(i) * 0.01,
                ts=now - timedelta(hours=3 - i),
            )

        results = await get_spread_history(
            migrated_pool, TOKEN_A, lookback_hours=24
        )
        assert len(results) == 3
        timestamps = [r[0] for r in results]
        assert timestamps == sorted(timestamps)

    async def test_empty_returns_empty_list(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """No data returns empty list."""
        results = await get_spread_history(
            migrated_pool, "nonexistent_token", lookback_hours=24
        )
        assert results == []


# ---------------------------------------------------------------------------
# Phase 1.4 — get_orderbook_imbalance
# ---------------------------------------------------------------------------


class TestGetOrderbookImbalance:
    """Test order-book imbalance from latest snapshot."""

    async def test_bid_heavy_positive_imbalance(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """More bid volume than ask volume produces positive imbalance."""
        bids = [[0.49, 100.0], [0.48, 200.0]]  # bid_vol = 300
        asks = [[0.51, 50.0]]                   # ask_vol = 50
        await _insert_orderbook(migrated_pool, TOKEN_A, bids, asks)

        imb = await get_orderbook_imbalance(migrated_pool, TOKEN_A)
        assert imb is not None
        # (300 - 50) / (300 + 50) = 250/350 ≈ 0.714
        expected = (300 - 50) / (300 + 50)
        assert abs(imb - expected) < 1e-6

    async def test_ask_heavy_negative_imbalance(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """More ask volume than bid volume produces negative imbalance."""
        bids = [[0.49, 10.0]]
        asks = [[0.51, 90.0]]
        await _insert_orderbook(migrated_pool, TOKEN_A, bids, asks)

        imb = await get_orderbook_imbalance(migrated_pool, TOKEN_A)
        assert imb is not None
        expected = (10 - 90) / (10 + 90)
        assert abs(imb - expected) < 1e-6

    async def test_no_data_returns_none(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Token with no snapshot returns None."""
        imb = await get_orderbook_imbalance(migrated_pool, "nonexistent_token")
        assert imb is None

    async def test_zero_volume_returns_none(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Empty bid/ask lists (zero total volume) returns None."""
        await _insert_orderbook(migrated_pool, TOKEN_A, [], [])
        imb = await get_orderbook_imbalance(migrated_pool, TOKEN_A)
        assert imb is None


# ---------------------------------------------------------------------------
# Phase 1.5 — get_trade_volume_profile
# ---------------------------------------------------------------------------


class TestGetTradeVolumeProfile:
    """Test buy/sell volume profile aggregation."""

    async def test_buy_sell_split(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Buy and sell volumes are correctly separated."""
        trades = [
            ("BUY", 0.50, 100.0),
            ("BUY", 0.51, 50.0),
            ("SELL", 0.49, 75.0),
            ("SELL", 0.48, 25.0),
        ]
        await _insert_trades(migrated_pool, TOKEN_A, trades)

        profile = await get_trade_volume_profile(
            migrated_pool, TOKEN_A, lookback_hours=24
        )

        assert abs(profile["buy_volume"] - 150.0) < 1e-6
        assert abs(profile["sell_volume"] - 100.0) < 1e-6
        assert profile["trade_count"] == 4

    async def test_no_data_returns_zeros(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Token with no trades returns zero-filled dict."""
        profile = await get_trade_volume_profile(
            migrated_pool, "nonexistent_token", lookback_hours=24
        )
        assert profile["buy_volume"] == 0.0
        assert profile["sell_volume"] == 0.0
        assert profile["trade_count"] == 0

    async def test_respects_lookback_window(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Trades outside the lookback window are excluded."""
        recent_trades = [("BUY", 0.50, 10.0)]
        old_start = datetime.now(timezone.utc) - timedelta(hours=48)
        recent_start = datetime.now(timezone.utc) - timedelta(hours=1)

        await _insert_trades(migrated_pool, TOKEN_A, [("SELL", 0.49, 999.0)], start=old_start)
        await _insert_trades(migrated_pool, TOKEN_A, recent_trades, start=recent_start)

        profile = await get_trade_volume_profile(
            migrated_pool, TOKEN_A, lookback_hours=24
        )
        assert abs(profile["buy_volume"] - 10.0) < 1e-6
        assert profile["sell_volume"] == 0.0
        assert profile["trade_count"] == 1


# ---------------------------------------------------------------------------
# Phase 1.6 — get_market_features
# ---------------------------------------------------------------------------


class TestGetMarketFeatures:
    """Test combined feature aggregation per market."""

    async def test_returns_features_for_each_token(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Feature dict contains an entry for every clob_token_id in the market."""
        await _insert_market(migrated_pool, CONDITION_ID, [TOKEN_A, TOKEN_B])

        await _insert_prices(migrated_pool, TOKEN_A, [0.60, 0.62, 0.61])
        await _insert_prices(migrated_pool, TOKEN_B, [0.38, 0.36, 0.37])

        features = await get_market_features(migrated_pool, CONDITION_ID)

        assert TOKEN_A in features
        assert TOKEN_B in features
        for token_id in [TOKEN_A, TOKEN_B]:
            f = features[token_id]
            assert "price_returns" in f
            assert "volatility" in f
            assert "spread_history" in f
            assert "orderbook_imbalance" in f
            assert "volume_profile" in f

    async def test_unknown_condition_id_returns_empty(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """A condition_id not in the DB returns empty dict."""
        features = await get_market_features(migrated_pool, "nonexistent_cond")
        assert features == {}
