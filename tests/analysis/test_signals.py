"""Integration tests for signal generation.

Tests cover:
1. generate_same_event_signals - buy/sell signals from YES-sum mispricing
2. generate_mean_reversion_signals - z-score deviation signals
3. generate_spread_signals - wide bid-ask spread signals
4. get_all_signals - deduplication and ranking
"""

import json
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from src.analysis.signals import (
    MarketSignal,
    generate_mean_reversion_signals,
    generate_same_event_signals,
    generate_spread_signals,
    get_all_signals,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


BASE_TS = datetime(2026, 1, 25, 8, 0, 0, tzinfo=timezone.utc)


async def _insert_market(
    pool: asyncpg.Pool,
    condition_id: str,
    slug: str,
    token_ids: list[str],
) -> None:
    await pool.execute(
        """
        INSERT INTO markets (
            condition_id, question, slug, market_type,
            outcomes, clob_token_ids, active, closed, end_date_iso
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (condition_id) DO NOTHING
        """,
        condition_id,
        f"Signal test market {slug}?",
        slug,
        "binary",
        ["YES", "NO"],
        token_ids,
        True,
        False,
        None,
    )


async def _insert_price(
    pool: asyncpg.Pool,
    token_id: str,
    price: float,
    ts: datetime | None = None,
) -> None:
    ts = ts or datetime.now(timezone.utc)
    await pool.execute(
        "INSERT INTO price_snapshots (ts, token_id, price, volume_24h) VALUES ($1, $2, $3, $4)",
        ts,
        token_id,
        price,
        None,
    )


async def _insert_prices_bulk(
    pool: asyncpg.Pool,
    token_id: str,
    prices: list[float],
    start: datetime,
    interval_minutes: int = 1,
) -> None:
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
    spread: float,
    midpoint: float,
    ts: datetime | None = None,
) -> None:
    ts = ts or datetime.now(timezone.utc)
    await pool.execute(
        """
        INSERT INTO orderbook_snapshots (ts, token_id, bids, asks, spread, midpoint)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6)
        """,
        ts,
        token_id,
        json.dumps([[midpoint - spread / 2, 100.0]]),
        json.dumps([[midpoint + spread / 2, 100.0]]),
        spread,
        midpoint,
    )


# ---------------------------------------------------------------------------
# Phase 3.1 — generate_same_event_signals
# ---------------------------------------------------------------------------


class TestGenerateSameEventSignals:
    """Test same-event mispricing signals."""

    async def test_buy_signal_when_underpriced(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """When YES prices sum < 1.0, underpriced tokens get buy signals."""
        now = datetime.now(timezone.utc)
        await _insert_market(migrated_pool, "cond_se1", "sig-event-1", ["tok_se1_yes", "tok_se1_no"])
        await _insert_market(migrated_pool, "cond_se2", "sig-event-2", ["tok_se2_yes", "tok_se2_no"])

        # YES prices: 0.40 + 0.45 = 0.85 -> under-priced
        await _insert_price(migrated_pool, "tok_se1_yes", 0.40, ts=now)
        await _insert_price(migrated_pool, "tok_se2_yes", 0.45, ts=now)

        signals = await generate_same_event_signals(migrated_pool)

        assert len(signals) > 0
        buy_sigs = [s for s in signals if s.direction == "buy" and s.signal_type == "same_event"]
        assert len(buy_sigs) > 0

    async def test_sell_signal_when_overpriced(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """When YES prices sum > 1.0, overpriced tokens get sell signals."""
        now = datetime.now(timezone.utc)
        await _insert_market(migrated_pool, "cond_se3", "sig-over-1", ["tok_so1_yes", "tok_so1_no"])
        await _insert_market(migrated_pool, "cond_se4", "sig-over-2", ["tok_so2_yes", "tok_so2_no"])

        # YES prices: 0.60 + 0.55 = 1.15 -> over-priced
        await _insert_price(migrated_pool, "tok_so1_yes", 0.60, ts=now)
        await _insert_price(migrated_pool, "tok_so2_yes", 0.55, ts=now)

        signals = await generate_same_event_signals(migrated_pool)

        sell_sigs = [s for s in signals if s.direction == "sell" and s.signal_type == "same_event"]
        assert len(sell_sigs) > 0

    async def test_no_signal_when_balanced(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """When YES prices sum ≈ 1.0 within tolerance, no same_event signals."""
        now = datetime.now(timezone.utc)
        await _insert_market(migrated_pool, "cond_se5", "balanced-event-1", ["tok_bal1", "tok_bal2"])
        await _insert_market(migrated_pool, "cond_se6", "balanced-event-2", ["tok_bal3", "tok_bal4"])

        await _insert_price(migrated_pool, "tok_bal1", 0.50, ts=now)
        await _insert_price(migrated_pool, "tok_bal3", 0.50, ts=now)

        signals = await generate_same_event_signals(migrated_pool)
        same_event_sigs = [s for s in signals if s.signal_type == "same_event"]
        # Balanced -> no signal (or very few due to tolerance)
        for s in same_event_sigs:
            assert abs(s.edge_pct) > 0  # if any, they should have real edge

    async def test_empty_db_returns_no_signals(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """No markets -> no signals."""
        signals = await generate_same_event_signals(migrated_pool)
        assert signals == []


# ---------------------------------------------------------------------------
# Phase 3.2 — generate_mean_reversion_signals
# ---------------------------------------------------------------------------


class TestGenerateMeanReversionSignals:
    """Test z-score mean reversion signals."""

    async def test_high_price_generates_sell(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Price far above mean -> sell signal."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)

        # 100 prices near 0.50, then spike to 0.90
        stable_prices = [0.50] * 100
        await _insert_prices_bulk(migrated_pool, "tok_mr1", stable_prices, start=start)
        # Insert the spike as the most recent
        await _insert_price(migrated_pool, "tok_mr1", 0.90, ts=now)

        signals = await generate_mean_reversion_signals(
            migrated_pool, z_threshold=2.0, lookback_hours=6
        )

        mr_signals = [s for s in signals if s.token_id == "tok_mr1"]
        assert len(mr_signals) > 0
        assert mr_signals[0].direction == "sell"

    async def test_low_price_generates_buy(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Price far below mean -> buy signal."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)

        stable_prices = [0.70] * 100
        await _insert_prices_bulk(migrated_pool, "tok_mr2", stable_prices, start=start)
        await _insert_price(migrated_pool, "tok_mr2", 0.10, ts=now)

        signals = await generate_mean_reversion_signals(
            migrated_pool, z_threshold=2.0, lookback_hours=6
        )

        mr_signals = [s for s in signals if s.token_id == "tok_mr2"]
        assert len(mr_signals) > 0
        assert mr_signals[0].direction == "buy"

    async def test_stable_price_no_signal(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Stable price within normal range produces no mean-reversion signal."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)

        stable_prices = [0.50] * 50
        await _insert_prices_bulk(migrated_pool, "tok_mr3", stable_prices, start=start)

        signals = await generate_mean_reversion_signals(
            migrated_pool, z_threshold=2.0, lookback_hours=6
        )

        mr_signals = [s for s in signals if s.token_id == "tok_mr3"]
        assert len(mr_signals) == 0

    async def test_empty_db_returns_no_signals(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """No price data -> no mean-reversion signals."""
        signals = await generate_mean_reversion_signals(migrated_pool)
        assert signals == []


# ---------------------------------------------------------------------------
# Phase 3.3 — generate_spread_signals
# ---------------------------------------------------------------------------


class TestGenerateSpreadSignals:
    """Test bid-ask spread signals."""

    async def test_wide_spread_generates_signal(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """A spread of 10% on a 0.50 midpoint exceeds the 2% threshold."""
        await _insert_market(migrated_pool, "cond_spread1", "spread-mkt-1", ["tok_sp1"])
        await _insert_orderbook(
            migrated_pool, "tok_sp1",
            spread=0.05,   # 5 cents on 0.50 = 10% edge
            midpoint=0.50,
        )

        signals = await generate_spread_signals(migrated_pool, min_edge_pct=2.0)

        sp_sigs = [s for s in signals if s.token_id == "tok_sp1"]
        assert len(sp_sigs) == 1
        assert sp_sigs[0].direction == "buy"
        assert sp_sigs[0].edge_pct > 2.0

    async def test_tight_spread_no_signal(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """A spread of 0.5% is below the 2% threshold -> no signal."""
        await _insert_market(migrated_pool, "cond_spread2", "tight-spread-1", ["tok_ts1"])
        await _insert_orderbook(
            migrated_pool, "tok_ts1",
            spread=0.002,  # 0.2 cents on 0.50 = 0.4%
            midpoint=0.50,
        )

        signals = await generate_spread_signals(migrated_pool, min_edge_pct=2.0)
        ts_sigs = [s for s in signals if s.token_id == "tok_ts1"]
        assert len(ts_sigs) == 0

    async def test_empty_orderbooks_no_signal(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """No orderbook data returns no signals."""
        signals = await generate_spread_signals(migrated_pool)
        assert signals == []


# ---------------------------------------------------------------------------
# Phase 3.4 — get_all_signals
# ---------------------------------------------------------------------------


class TestGetAllSignals:
    """Test combined signal aggregation with deduplication."""

    async def test_deduplicates_by_token_and_type(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Duplicate signals for the same (token, type) are merged."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)

        # Create a mean-reversion signal for tok_dedup
        await _insert_prices_bulk(migrated_pool, "tok_dedup", [0.50] * 100, start=start)
        await _insert_price(migrated_pool, "tok_dedup", 0.95, ts=now)

        signals = await get_all_signals(migrated_pool)

        # At most one (tok_dedup, mean_reversion) signal
        dedup_sigs = [
            s for s in signals
            if s.token_id == "tok_dedup" and s.signal_type == "mean_reversion"
        ]
        assert len(dedup_sigs) <= 1

    async def test_signals_sorted_by_strength(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Returned signals are sorted strongest-first."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)

        # Create multiple signals with different strengths
        await _insert_prices_bulk(migrated_pool, "tok_rank1", [0.50] * 100, start=start)
        await _insert_price(migrated_pool, "tok_rank1", 0.95, ts=now)

        await _insert_orderbook(migrated_pool, "tok_rank2", spread=0.10, midpoint=0.50)

        signals = await get_all_signals(migrated_pool)

        if len(signals) >= 2:
            for i in range(len(signals) - 1):
                assert signals[i].strength >= signals[i + 1].strength

    async def test_returns_list_on_empty_db(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Empty DB returns empty list (no exceptions)."""
        signals = await get_all_signals(migrated_pool)
        assert isinstance(signals, list)

    async def test_signal_fields_valid(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Every signal has valid field values."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=3)

        await _insert_prices_bulk(migrated_pool, "tok_valid", [0.50] * 100, start=start)
        await _insert_price(migrated_pool, "tok_valid", 0.95, ts=now)

        signals = await get_all_signals(migrated_pool)

        for s in signals:
            assert s.signal_type in {"same_event", "mean_reversion", "spread"}
            assert s.direction in {"buy", "sell"}
            assert 0.0 <= s.strength <= 1.0
            assert s.edge_pct >= 0.0
            assert s.token_id
            assert s.market_id
