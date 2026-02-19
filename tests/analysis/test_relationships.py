"""Integration tests for market relationship detection.

Tests cover:
1. find_same_event_markets - groups markets by slug prefix
2. compute_price_correlation - Pearson correlation on aligned hourly buckets
3. find_correlated_pairs - scans tokens and filters by threshold
4. detect_mispricing - flags deviations from YES-sum = 1.0
"""

import json
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from src.analysis.relationships import (
    MarketGroup,
    compute_price_correlation,
    detect_mispricing,
    find_correlated_pairs,
    find_same_event_markets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


BASE_TS = datetime(2026, 1, 20, 10, 0, 0, tzinfo=timezone.utc)


async def _insert_market(
    pool: asyncpg.Pool,
    condition_id: str,
    slug: str,
    token_ids: list[str],
    active: bool = True,
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
        f"Question for {slug}?",
        slug,
        "binary",
        ["YES", "NO"],
        token_ids,
        active,
        False,
        None,
    )


async def _insert_hourly_prices(
    pool: asyncpg.Pool,
    token_id: str,
    prices: list[float],
    start: datetime = BASE_TS,
) -> None:
    """Insert one price snapshot per hour."""
    records = [
        (start + timedelta(hours=i), token_id, price, None)
        for i, price in enumerate(prices)
    ]
    await pool.copy_records_to_table(
        "price_snapshots",
        records=records,
        columns=["ts", "token_id", "price", "volume_24h"],
    )


# ---------------------------------------------------------------------------
# Phase 2.1 — find_same_event_markets
# ---------------------------------------------------------------------------


class TestFindSameEventMarkets:
    """Test grouping of active markets by slug prefix."""

    async def test_groups_markets_with_numeric_suffix(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Markets with slug 'event-name-1', 'event-name-2' form one group."""
        await _insert_market(migrated_pool, "cond_a1", "us-election-winner-1", ["tok_a1", "tok_a2"])
        await _insert_market(migrated_pool, "cond_a2", "us-election-winner-2", ["tok_a3", "tok_a4"])
        # Different event — should be a separate group or excluded if only 1
        await _insert_market(migrated_pool, "cond_b1", "bitcoin-price-jan", ["tok_b1", "tok_b2"])

        groups = await find_same_event_markets(migrated_pool)

        prefixes = {g.slug_prefix for g in groups}
        assert "us-election-winner" in prefixes

        election_group = next(
            g for g in groups if g.slug_prefix == "us-election-winner"
        )
        assert set(election_group.condition_ids) == {"cond_a1", "cond_a2"}

    async def test_single_market_slug_excluded(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """A slug prefix with only 1 market is not returned (no pairing)."""
        await _insert_market(migrated_pool, "cond_solo", "solo-event", ["tok_s1"])

        groups = await find_same_event_markets(migrated_pool)
        prefixes = {g.slug_prefix for g in groups}
        # 'solo-event' has no numeric suffix -> prefix = 'solo-event', only 1 market
        assert "solo-event" not in prefixes

    async def test_empty_db_returns_empty_list(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """No active markets returns empty list."""
        groups = await find_same_event_markets(migrated_pool)
        assert groups == []

    async def test_inactive_markets_excluded(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Inactive markets are not included in any group."""
        await _insert_market(migrated_pool, "cond_i1", "inactive-event-1", ["tok_i1"], active=False)
        await _insert_market(migrated_pool, "cond_i2", "inactive-event-2", ["tok_i2"], active=False)

        groups = await find_same_event_markets(migrated_pool)
        prefixes = {g.slug_prefix for g in groups}
        assert "inactive-event" not in prefixes


# ---------------------------------------------------------------------------
# Phase 2.2 — compute_price_correlation
# ---------------------------------------------------------------------------


class TestComputePriceCorrelation:
    """Test Pearson correlation of aligned price time series."""

    async def test_perfectly_correlated(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Identical price series -> correlation = 1.0."""
        prices = [0.50 + i * 0.01 for i in range(20)]
        await _insert_hourly_prices(migrated_pool, "tok_corr_a", prices)
        await _insert_hourly_prices(migrated_pool, "tok_corr_b", prices)

        corr = await compute_price_correlation(
            migrated_pool, "tok_corr_a", "tok_corr_b", lookback_hours=48
        )
        assert corr is not None
        assert abs(corr - 1.0) < 1e-6

    async def test_negatively_correlated(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Mirror-image price series -> correlation ≈ -1.0."""
        prices_a = [0.50 + i * 0.01 for i in range(20)]
        prices_b = [0.70 - i * 0.01 for i in range(20)]
        await _insert_hourly_prices(migrated_pool, "tok_neg_a", prices_a)
        await _insert_hourly_prices(migrated_pool, "tok_neg_b", prices_b)

        corr = await compute_price_correlation(
            migrated_pool, "tok_neg_a", "tok_neg_b", lookback_hours=48
        )
        assert corr is not None
        assert abs(corr - (-1.0)) < 1e-6

    async def test_no_overlap_returns_none(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Non-overlapping time windows -> no aligned points -> None."""
        await _insert_hourly_prices(
            migrated_pool, "tok_nolap_a", [0.50, 0.51],
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        await _insert_hourly_prices(
            migrated_pool, "tok_nolap_b", [0.40, 0.41],
            start=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

        corr = await compute_price_correlation(
            migrated_pool, "tok_nolap_a", "tok_nolap_b", lookback_hours=48
        )
        # Both series are outside the lookback window, so no data -> None
        assert corr is None

    async def test_missing_token_returns_none(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Unknown token_id returns None."""
        corr = await compute_price_correlation(
            migrated_pool, "nonexistent_x", "nonexistent_y", lookback_hours=24
        )
        assert corr is None


# ---------------------------------------------------------------------------
# Phase 2.3 — find_correlated_pairs
# ---------------------------------------------------------------------------


class TestFindCorrelatedPairs:
    """Test pairwise correlation scanning."""

    async def test_finds_correlated_pair(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Two highly correlated tokens appear in results."""
        prices = [0.50 + i * 0.005 for i in range(30)]
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=30)
        await _insert_hourly_prices(migrated_pool, "tok_cp_a", prices, start=start)
        await _insert_hourly_prices(migrated_pool, "tok_cp_b", prices, start=start)

        pairs = await find_correlated_pairs(
            migrated_pool, min_correlation=0.9, lookback_hours=48
        )

        token_pairs = {(p[0], p[1]) for p in pairs} | {(p[1], p[0]) for p in pairs}
        assert ("tok_cp_a", "tok_cp_b") in token_pairs or \
               ("tok_cp_b", "tok_cp_a") in token_pairs

    async def test_filters_below_threshold(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Uncorrelated tokens are excluded at high min_correlation."""
        import math
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=30)
        # Orthogonal: sin and cos are uncorrelated over a full period
        prices_a = [0.50 + 0.1 * math.sin(i * 0.3) for i in range(30)]
        prices_b = [0.50 + 0.1 * math.cos(i * 0.3) for i in range(30)]
        await _insert_hourly_prices(migrated_pool, "tok_unc_a", prices_a, start=start)
        await _insert_hourly_prices(migrated_pool, "tok_unc_b", prices_b, start=start)

        pairs = await find_correlated_pairs(
            migrated_pool, min_correlation=0.95, lookback_hours=48
        )

        token_pairs = {(p[0], p[1]) for p in pairs} | {(p[1], p[0]) for p in pairs}
        assert ("tok_unc_a", "tok_unc_b") not in token_pairs and \
               ("tok_unc_b", "tok_unc_a") not in token_pairs

    async def test_empty_db_returns_empty(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """No price data returns empty list."""
        pairs = await find_correlated_pairs(migrated_pool, lookback_hours=24)
        assert pairs == []


# ---------------------------------------------------------------------------
# Phase 2.4 — detect_mispricing
# ---------------------------------------------------------------------------


class TestDetectMispricing:
    """Test YES-sum mispricing detection."""

    async def _setup_group(
        self, pool: asyncpg.Pool, prices: list[float]
    ) -> MarketGroup:
        """Insert N binary markets with given YES-token prices."""
        condition_ids = []
        token_ids = []
        now = datetime.now(timezone.utc)

        for i, price in enumerate(prices):
            cid = f"cond_mp_{i}"
            yes_tok = f"tok_mp_yes_{i}"
            no_tok = f"tok_mp_no_{i}"
            await _insert_market(pool, cid, f"event-group-mp-{i+1}", [yes_tok, no_tok])
            condition_ids.append(cid)
            token_ids.extend([yes_tok, no_tok])

            # Insert latest price for YES token
            await pool.execute(
                """
                INSERT INTO price_snapshots (ts, token_id, price, volume_24h)
                VALUES ($1, $2, $3, $4)
                """,
                now,
                yes_tok,
                price,
                None,
            )

        return MarketGroup(
            slug_prefix="event-group-mp",
            condition_ids=condition_ids,
            token_ids=token_ids,
        )

    async def test_detects_underpriced_group(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """YES prices summing to 0.85 (< 1.0) triggers a mispricing."""
        group = await self._setup_group(migrated_pool, [0.40, 0.45])

        mispricings = await detect_mispricing(migrated_pool, group, tolerance=0.01)

        assert len(mispricings) == 1
        mp = mispricings[0]
        assert abs(mp.yes_sum - 0.85) < 1e-6
        assert mp.deviation < 0  # under-priced

    async def test_detects_overpriced_group(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """YES prices summing to 1.15 (> 1.0) triggers a mispricing."""
        group = await self._setup_group(migrated_pool, [0.60, 0.55])

        mispricings = await detect_mispricing(migrated_pool, group, tolerance=0.01)

        assert len(mispricings) == 1
        mp = mispricings[0]
        assert abs(mp.yes_sum - 1.15) < 1e-6
        assert mp.deviation > 0  # over-priced

    async def test_no_mispricing_within_tolerance(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """YES prices summing to 1.0 within tolerance -> no mispricing."""
        group = await self._setup_group(migrated_pool, [0.50, 0.50])

        mispricings = await detect_mispricing(migrated_pool, group, tolerance=0.02)
        assert mispricings == []

    async def test_no_price_data_returns_empty(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Markets with no price data return empty list."""
        group = MarketGroup(
            slug_prefix="no-data",
            condition_ids=["nonexistent_cond"],
            token_ids=["nonexistent_tok"],
        )
        mispricings = await detect_mispricing(migrated_pool, group)
        assert mispricings == []
