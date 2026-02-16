"""Full end-to-end integration test for the database layer.

Validates the complete pipeline: pool -> migrations -> schema -> models -> queries.
This is the "Phase 1 complete" smoke test proving all 5 tables work together.

Steps:
1. Run all migrations (via migrated_pool fixture)
2. Upsert 3 markets
3. Insert 100 price snapshots across 3 token_ids
4. Insert 10 orderbook snapshots
5. Insert 50 trades
6. Upsert 1 resolution
7. Query each table and verify data integrity
8. Verify get_unresolved_markets returns correct markets
9. Verify get_latest_prices returns one per token
"""

from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from src.db.queries.markets import (
    get_active_markets,
    get_market,
    upsert_market,
    upsert_markets,
)
from src.db.queries.prices import (
    get_latest_prices,
    get_price_count,
    insert_price_snapshots,
)
from src.db.queries.orderbooks import (
    get_latest_orderbook,
    get_orderbook_history,
    insert_orderbook_snapshots,
)
from src.db.queries.trades import (
    get_recent_trades,
    get_trade_count,
    insert_trades,
)
from src.db.queries.resolutions import (
    get_resolution,
    get_unresolved_markets,
    upsert_resolution,
)


class TestFullIntegration:
    """End-to-end test proving all 5 tables work together."""

    async def test_complete_pipeline(
        self, migrated_pool: asyncpg.Pool
    ) -> None:
        """Full pipeline: markets, prices, orderbooks, trades, resolutions all work together."""
        base_ts = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)

        # ---- Step 1: Upsert 3 markets ----
        markets = [
            {
                "condition_id": f"0x_integ_{i}",
                "question": f"Integration test market {i}?",
                "slug": f"integ-{i}",
                "market_type": "binary",
                "outcomes": ["Yes", "No"],
                "clob_token_ids": [f"tok_integ_{i}_yes", f"tok_integ_{i}_no"],
                "active": True if i < 2 else False,
                "closed": False if i < 2 else True,
                "end_date_iso": None,
            }
            for i in range(3)
        ]
        await upsert_markets(migrated_pool, markets)

        # Verify all 3 markets exist
        for i in range(3):
            m = await get_market(migrated_pool, f"0x_integ_{i}")
            assert m is not None, f"Market 0x_integ_{i} not found"
            assert m.question == f"Integration test market {i}?"

        # ---- Step 2: Insert 100 price snapshots across 3 token_ids ----
        token_ids = ["tok_integ_0_yes", "tok_integ_1_yes", "tok_integ_2_yes"]
        price_snapshots = []
        for idx, token_id in enumerate(token_ids):
            for j in range(33):
                price_snapshots.append((
                    base_ts + timedelta(minutes=j),
                    token_id,
                    0.50 + idx * 0.1 + j * 0.001,
                    1000.0 + j,
                ))
        # Add one more to reach exactly 100
        price_snapshots.append((
            base_ts + timedelta(minutes=33),
            token_ids[0],
            0.533,
            1033.0,
        ))
        assert len(price_snapshots) == 100

        price_count = await insert_price_snapshots(migrated_pool, price_snapshots)
        assert price_count == 100

        total_prices = await get_price_count(migrated_pool)
        assert total_prices == 100

        # ---- Step 3: Insert 10 orderbook snapshots ----
        ob_snapshots = [
            (
                base_ts + timedelta(minutes=i * 5),
                token_ids[i % 3],
                {"levels": [[0.48 + i * 0.005, 100 + i * 10]]},
                {"levels": [[0.52 - i * 0.005, 100 + i * 10]]},
                0.04 - i * 0.002,
                0.50,
            )
            for i in range(10)
        ]

        ob_count = await insert_orderbook_snapshots(migrated_pool, ob_snapshots)
        assert ob_count == 10

        # ---- Step 4: Insert 50 trades ----
        trade_records = [
            (
                base_ts + timedelta(seconds=i),
                token_ids[i % 3],
                "BUY" if i % 2 == 0 else "SELL",
                0.50 + i * 0.005,
                10.0 + i,
                f"integ_trade_{i}",
            )
            for i in range(50)
        ]

        trade_count = await insert_trades(migrated_pool, trade_records)
        assert trade_count == 50

        total_trades = await get_trade_count(migrated_pool)
        assert total_trades == 50

        # ---- Step 5: Upsert 1 resolution (for the closed market) ----
        await upsert_resolution(migrated_pool, {
            "condition_id": "0x_integ_2",
            "outcome": "Yes",
            "winner_token_id": "tok_integ_2_yes",
            "resolved_at": base_ts + timedelta(hours=1),
            "payout_price": 1.0,
            "detection_method": "final_price",
        })

        resolution = await get_resolution(migrated_pool, "0x_integ_2")
        assert resolution is not None
        assert resolution.outcome == "Yes"

        # ---- Step 6: Query each table and verify integrity ----

        # Markets: active markets should be markets 0 and 1
        active = await get_active_markets(migrated_pool)
        active_ids = {m.condition_id for m in active}
        assert "0x_integ_0" in active_ids
        assert "0x_integ_1" in active_ids
        assert "0x_integ_2" not in active_ids

        # Prices: get_latest_prices returns one per token
        latest_prices = await get_latest_prices(migrated_pool, token_ids)
        assert len(latest_prices) == 3
        price_map = {p.token_id: p for p in latest_prices}
        for tid in token_ids:
            assert tid in price_map

        # Orderbooks: get_latest_orderbook returns a snapshot
        for tid in token_ids:
            ob = await get_latest_orderbook(migrated_pool, tid)
            assert ob is not None
            assert ob.token_id == tid
            assert ob.bids is not None

        # Trades: get_recent_trades for each token
        for tid in token_ids:
            recent = await get_recent_trades(migrated_pool, tid, limit=10)
            assert len(recent) > 0
            # Verify ordering
            for k in range(len(recent) - 1):
                assert recent[k].ts >= recent[k + 1].ts

        # Trade count by token
        count_0 = await get_trade_count(migrated_pool, token_id=token_ids[0])
        count_1 = await get_trade_count(migrated_pool, token_id=token_ids[1])
        count_2 = await get_trade_count(migrated_pool, token_id=token_ids[2])
        assert count_0 + count_1 + count_2 == 50

        # ---- Step 7: Verify get_unresolved_markets ----
        # Market 2 is closed AND has a resolution -> NOT unresolved
        # Markets 0 and 1 are active (not closed) -> NOT unresolved
        unresolved = await get_unresolved_markets(migrated_pool)
        assert "0x_integ_2" not in unresolved  # has resolution
        assert "0x_integ_0" not in unresolved  # not closed
        assert "0x_integ_1" not in unresolved  # not closed
