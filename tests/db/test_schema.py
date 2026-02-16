"""Schema verification tests.

Runs all migrations against a real TimescaleDB container and verifies
the end-state schema: tables, hypertables, continuous aggregates,
compression settings, indexes, and retention policies.
"""

import asyncpg
import pytest


class TestSchemaEndState:
    """Verify the complete schema after all migrations have run."""

    async def test_all_tables_exist(self, migrated_pool: asyncpg.Pool) -> None:
        """All 5 application tables should exist in the public schema."""
        expected_tables = {
            "markets",
            "price_snapshots",
            "orderbook_snapshots",
            "trades",
            "resolutions",
        }

        async with migrated_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename = ANY($1::text[])
                """,
                list(expected_tables),
            )
            found = {r["tablename"] for r in rows}

        assert found == expected_tables, f"Missing tables: {expected_tables - found}"

    async def test_hypertables_exist(self, migrated_pool: asyncpg.Pool) -> None:
        """3 hypertables should exist: price_snapshots, orderbook_snapshots, trades."""
        expected = {"price_snapshots", "orderbook_snapshots", "trades"}

        async with migrated_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT hypertable_name
                FROM timescaledb_information.hypertables
                WHERE hypertable_schema = 'public'
                """
            )
            found = {r["hypertable_name"] for r in rows}

        assert expected.issubset(found), f"Missing hypertables: {expected - found}"

    async def test_continuous_aggregates_exist(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """2 continuous aggregates should exist: price_candles_1h, trade_volume_1h."""
        expected = {"price_candles_1h", "trade_volume_1h"}

        async with migrated_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT view_name
                FROM timescaledb_information.continuous_aggregates
                WHERE view_schema = 'public'
                """
            )
            found = {r["view_name"] for r in rows}

        assert expected.issubset(found), f"Missing aggregates: {expected - found}"

    async def test_compression_enabled(self, migrated_pool: asyncpg.Pool) -> None:
        """Compression should be enabled on all 3 hypertables."""
        expected = {"price_snapshots", "orderbook_snapshots", "trades"}

        async with migrated_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT hypertable_name
                FROM timescaledb_information.compression_settings
                WHERE hypertable_schema = 'public'
                """
            )
            found = {r["hypertable_name"] for r in rows}

        assert expected.issubset(found), f"Missing compression: {expected - found}"

    async def test_indexes_exist(self, migrated_pool: asyncpg.Pool) -> None:
        """Key indexes should exist on time-series tables."""
        expected_indexes = {
            "idx_markets_active",
            "idx_price_snapshots_token_time",
            "idx_orderbook_snapshots_token_time",
            "idx_trades_token_time",
            "idx_trades_trade_id",
        }

        async with migrated_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT indexname FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = ANY($1::text[])
                """,
                list(expected_indexes),
            )
            found = {r["indexname"] for r in rows}

        assert found == expected_indexes, (
            f"Missing indexes: {expected_indexes - found}"
        )

    async def test_retention_policies_exist(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Retention policies should exist on price_snapshots and trades."""
        async with migrated_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT hypertable_name
                FROM timescaledb_information.jobs
                WHERE proc_name = 'policy_retention'
                  AND hypertable_schema = 'public'
                """
            )
            found = {r["hypertable_name"] for r in rows}

        expected = {"price_snapshots", "trades"}
        assert expected.issubset(found), (
            f"Missing retention policies: {expected - found}"
        )

    async def test_schema_migrations_tracked(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """schema_migrations should have exactly 8 rows after full migration."""
        async with migrated_pool.acquire() as conn:
            count = await conn.fetchval("SELECT count(*) FROM schema_migrations")

        assert count == 8
