"""Tests for WebSocket trade listener parsing and components.

All tests are mock-based (no real WebSocket connections) due to
geoblocking constraints.  Uses unittest.mock.AsyncMock for WebSocket
object mocking and pytest-asyncio (auto mode) for async tests.

03-04 additions: connection pooling, lifecycle management, and health
state tracking tests.
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.collector.trade_listener import (
    TradeListener,
    TradeListenerHealth,
    parse_trade_event,
)
from src.config import CollectorConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade_event(
    asset_id: str = "tok123",
    price: str = "0.52",
    size: str = "100",
    side: str = "BUY",
    timestamp: str = "1700000000000",
    event_type: str = "last_trade_price",
    **overrides,
) -> dict:
    """Build a sample CLOB WebSocket trade event."""
    base = {
        "event_type": event_type,
        "asset_id": asset_id,
        "market": "cond1",
        "price": price,
        "size": size,
        "side": side,
        "fee_rate_bps": "200",
        "timestamp": timestamp,
    }
    base.update(overrides)
    return base


def _make_trade_tuple(
    ts: datetime | None = None,
    token_id: str = "tok123",
    side: str = "BUY",
    price: float = 0.52,
    size: float = 100.0,
    trade_id: None = None,
) -> tuple:
    """Build a sample trade tuple matching parse_trade_event output."""
    if ts is None:
        ts = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    return (ts, token_id, side, price, size, trade_id)


def _make_listener(
    trade_buffer_size: int = 1000,
    ws_ping_interval_sec: int = 10,
    trade_batch_drain_timeout_sec: float = 5.0,
    ws_max_instruments_per_conn: int = 500,
    running: bool = True,
) -> TradeListener:
    """Create a TradeListener with a mock pool and given config."""
    config = CollectorConfig(
        trade_buffer_size=trade_buffer_size,
        ws_ping_interval_sec=ws_ping_interval_sec,
        trade_batch_drain_timeout_sec=trade_batch_drain_timeout_sec,
        ws_max_instruments_per_conn=ws_max_instruments_per_conn,
    )
    pool = AsyncMock()
    listener = TradeListener(pool=pool, config=config)
    listener._running = running
    return listener


# =========================================================================
# parse_trade_event tests (1-6)
# =========================================================================


class TestParseTradeEvent:
    """Tests for the parse_trade_event function."""

    def test_parse_valid_trade_event(self) -> None:
        """Valid last_trade_price event returns correct 6-tuple."""
        event = _make_trade_event()
        result = parse_trade_event(event)

        assert result is not None
        ts, token_id, side, price, size, trade_id = result
        assert ts == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
        assert token_id == "tok123"
        assert side == "BUY"
        assert price == 0.52
        assert size == 100.0
        assert trade_id is None

    def test_parse_sell_side(self) -> None:
        """Sell-side event preserves SELL side."""
        event = _make_trade_event(side="SELL")
        result = parse_trade_event(event)

        assert result is not None
        assert result[2] == "SELL"

    def test_parse_filters_non_trade_event(self) -> None:
        """Non-trade event_type returns None."""
        event = _make_trade_event(event_type="price_change")
        result = parse_trade_event(event)

        assert result is None

    def test_parse_invalid_price_returns_none(self) -> None:
        """Invalid price string returns None without raising."""
        event = _make_trade_event(price="invalid")
        result = parse_trade_event(event)

        assert result is None

    def test_parse_missing_fields_returns_none(self) -> None:
        """Event missing required fields returns None."""
        event = {"event_type": "last_trade_price"}
        result = parse_trade_event(event)

        assert result is None

    def test_parse_trade_id_always_none(self) -> None:
        """trade_id (tuple[5]) is always None regardless of input."""
        event = _make_trade_event()
        result = parse_trade_event(event)

        assert result is not None
        assert result[5] is None


# =========================================================================
# _subscribe test (7)
# =========================================================================


class TestSubscribe:
    """Tests for TradeListener._subscribe."""

    async def test_subscribe_sends_correct_json(self) -> None:
        """_subscribe sends the correct subscription JSON."""
        listener = _make_listener()
        ws = AsyncMock()

        await listener._subscribe(ws, ["tok1", "tok2"])

        ws.send.assert_called_once_with(
            json.dumps({"assets_ids": ["tok1", "tok2"], "type": "market"})
        )


# =========================================================================
# _ping_loop test (8)
# =========================================================================


class TestPingLoop:
    """Tests for TradeListener._ping_loop."""

    async def test_ping_loop_sends_ping(self) -> None:
        """_ping_loop sends PING at least twice over ~0.3s with 0.1s interval."""
        listener = _make_listener(ws_ping_interval_sec=0)
        # Use interval=0 so pings fire as fast as possible
        listener.config.ws_ping_interval_sec = 0
        ws = AsyncMock()

        # Run _ping_loop as a task for a short duration
        task = asyncio.create_task(listener._ping_loop(ws))
        await asyncio.sleep(0.15)
        listener._running = False
        # Give it time to notice _running is False
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have sent PING at least twice
        ping_calls = [
            call for call in ws.send.call_args_list if call.args[0] == "PING"
        ]
        assert len(ping_calls) >= 2, (
            f"Expected at least 2 PINGs, got {len(ping_calls)}"
        )


# =========================================================================
# _drain_loop tests (9-10)
# =========================================================================


class TestDrainLoop:
    """Tests for TradeListener._drain_loop."""

    async def test_drain_loop_batches_and_inserts(self) -> None:
        """_drain_loop batches up to trade_buffer_size and calls insert_trades."""
        listener = _make_listener(
            trade_buffer_size=3,
            trade_batch_drain_timeout_sec=0.5,
        )

        # Pre-fill queue with 5 trade tuples
        for i in range(5):
            listener._queue.put_nowait(
                _make_trade_tuple(token_id=f"tok{i}")
            )

        inserted_batches = []

        async def mock_insert(pool, batch):
            inserted_batches.append(list(batch))
            return len(batch)

        with patch(
            "src.collector.trade_listener.insert_trades",
            side_effect=mock_insert,
        ):
            # Run drain for a short time, then stop
            task = asyncio.create_task(listener._drain_loop())
            # Wait enough for drain to process
            await asyncio.sleep(0.3)
            listener._running = False
            await asyncio.sleep(0.8)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # All 5 trades should have been inserted
        total_inserted = sum(len(b) for b in inserted_batches)
        assert total_inserted == 5, (
            f"Expected 5 total trades inserted, got {total_inserted}"
        )
        # First batch should be capped at trade_buffer_size=3
        assert len(inserted_batches[0]) == 3

    async def test_drain_loop_handles_insert_error(self) -> None:
        """_drain_loop logs error and continues if insert_trades raises."""
        listener = _make_listener(
            trade_buffer_size=10,
            trade_batch_drain_timeout_sec=0.5,
        )

        # Pre-fill queue
        listener._queue.put_nowait(_make_trade_tuple())

        with patch(
            "src.collector.trade_listener.insert_trades",
            side_effect=Exception("DB error"),
        ):
            task = asyncio.create_task(listener._drain_loop())
            await asyncio.sleep(0.3)
            listener._running = False
            await asyncio.sleep(0.8)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should not crash — queue should be empty (item was consumed)
        assert listener._queue.empty()


# =========================================================================
# _receive_loop tests (11-12)
# =========================================================================


class TestReceiveLoop:
    """Tests for TradeListener._receive_loop."""

    async def test_receive_loop_handles_array_message(self) -> None:
        """_receive_loop enqueues trades from a JSON array message."""
        listener = _make_listener()

        event1 = _make_trade_event(asset_id="tok1")
        event2 = _make_trade_event(asset_id="tok2")
        array_msg = json.dumps([event1, event2])

        # Create a mock WS that yields one array message then stops
        ws = AsyncMock()
        ws.__aiter__ = lambda self: self
        messages = iter([array_msg])

        async def anext_impl(self):
            try:
                return next(messages)
            except StopIteration:
                raise StopAsyncIteration

        ws.__anext__ = anext_impl

        await listener._receive_loop(ws)

        assert listener._queue.qsize() == 2

    async def test_receive_loop_handles_dict_message(self) -> None:
        """_receive_loop enqueues a trade from a single JSON dict message."""
        listener = _make_listener()

        event1 = _make_trade_event(asset_id="tok1")
        dict_msg = json.dumps(event1)

        # Create a mock WS that yields one dict message then stops
        ws = AsyncMock()
        ws.__aiter__ = lambda self: self
        messages = iter([dict_msg])

        async def anext_impl(self):
            try:
                return next(messages)
            except StopIteration:
                raise StopAsyncIteration

        ws.__anext__ = anext_impl

        await listener._receive_loop(ws)

        assert listener._queue.qsize() == 1


# =========================================================================
# Connection pooling tests (13-16)
# =========================================================================


class TestGetActiveTokenIds:
    """Tests for TradeListener._get_active_token_ids."""

    async def test_get_active_token_ids_flattens_and_deduplicates(
        self, migrated_pool
    ) -> None:
        """_get_active_token_ids flattens and deduplicates clob_token_ids."""
        from src.db.queries.markets import upsert_market

        # Insert 3 markets with overlapping token IDs
        await upsert_market(migrated_pool, {
            "condition_id": "cond1",
            "question": "Market 1?",
            "clob_token_ids": ["tok_a", "tok_b"],
            "active": True,
        })
        await upsert_market(migrated_pool, {
            "condition_id": "cond2",
            "question": "Market 2?",
            "clob_token_ids": ["tok_b", "tok_c"],  # tok_b overlaps
            "active": True,
        })
        await upsert_market(migrated_pool, {
            "condition_id": "cond3",
            "question": "Market 3?",
            "clob_token_ids": ["tok_c", "tok_d"],  # tok_c overlaps
            "active": True,
        })

        config = CollectorConfig()
        listener = TradeListener(pool=migrated_pool, config=config)

        token_ids = await listener._get_active_token_ids()

        assert sorted(token_ids) == ["tok_a", "tok_b", "tok_c", "tok_d"]

    async def test_get_active_token_ids_empty_when_no_markets(
        self, migrated_pool
    ) -> None:
        """_get_active_token_ids returns empty list when no active markets."""
        config = CollectorConfig()
        listener = TradeListener(pool=migrated_pool, config=config)

        token_ids = await listener._get_active_token_ids()

        assert token_ids == []


class TestRunChunking:
    """Tests for TradeListener.run() token chunking."""

    async def test_run_chunks_tokens_into_connections(self) -> None:
        """run() chunks tokens into connections of ws_max_instruments_per_conn."""
        listener = _make_listener(
            ws_max_instruments_per_conn=2, running=False
        )

        # Mock _get_active_token_ids to return 5 tokens
        listener._get_active_token_ids = AsyncMock(
            return_value=["t1", "t2", "t3", "t4", "t5"]
        )
        # Mock _listen_single and _drain_loop to return immediately
        listener._listen_single = AsyncMock()
        listener._drain_loop = AsyncMock()

        await listener.run()

        # _listen_single should be called 3 times: [t1,t2], [t3,t4], [t5]
        assert listener._listen_single.call_count == 3
        calls = [call.args[0] for call in listener._listen_single.call_args_list]
        assert calls[0] == ["t1", "t2"]
        assert calls[1] == ["t3", "t4"]
        assert calls[2] == ["t5"]

        # _drain_loop should be called once
        assert listener._drain_loop.call_count == 1

    async def test_run_no_tokens_returns_early(self) -> None:
        """run() returns early without starting tasks when no tokens found."""
        listener = _make_listener(running=False)

        listener._get_active_token_ids = AsyncMock(return_value=[])
        listener._listen_single = AsyncMock()
        listener._drain_loop = AsyncMock()

        await listener.run()

        listener._listen_single.assert_not_called()
        listener._drain_loop.assert_not_called()
        assert listener._running is False


# =========================================================================
# Lifecycle tests (17-18)
# =========================================================================


class TestLifecycle:
    """Tests for TradeListener.run()/stop() lifecycle."""

    async def test_stop_cancels_tasks(self) -> None:
        """stop() cancels all running tasks."""
        listener = _make_listener(running=False)

        # Mock _get_active_token_ids to return tokens
        listener._get_active_token_ids = AsyncMock(return_value=["t1", "t2"])

        # Mock _listen_single and _drain_loop to sleep forever
        async def sleep_forever(*args, **kwargs):
            await asyncio.sleep(3600)

        listener._listen_single = AsyncMock(side_effect=sleep_forever)
        listener._drain_loop = AsyncMock(side_effect=sleep_forever)

        # Start run() as a background task
        run_task = asyncio.create_task(listener.run())
        # Give time for tasks to start
        await asyncio.sleep(0.1)

        # Verify tasks exist
        assert len(listener._tasks) > 0

        # Call stop
        await listener.stop()

        # All tasks should be done (cancelled)
        for task in listener._tasks:
            assert task.done()

        # Clean up
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass

    async def test_stop_flushes_remaining_queue(self) -> None:
        """stop() flushes remaining trades in queue via insert_trades."""
        listener = _make_listener(running=False)
        listener._tasks = []  # No active tasks to cancel

        # Put trade tuples in queue
        for i in range(3):
            listener._queue.put_nowait(
                _make_trade_tuple(token_id=f"tok{i}")
            )

        inserted = []

        async def mock_insert(pool, batch):
            inserted.extend(batch)
            return len(batch)

        with patch(
            "src.collector.trade_listener.insert_trades",
            side_effect=mock_insert,
        ):
            await listener.stop()

        # All 3 trades should have been flushed
        assert len(inserted) == 3
        assert listener._queue.empty()


# =========================================================================
# Health state tests (19-21)
# =========================================================================


class TestHealthState:
    """Tests for TradeListenerHealth tracking."""

    def test_health_initial_state(self) -> None:
        """New TradeListener has health with all zeros/Nones."""
        listener = _make_listener(running=False)

        health = listener.health
        assert health.trades_received == 0
        assert health.trades_inserted == 0
        assert health.batches_inserted == 0
        assert health.connections_active == 0
        assert health.reconnections == 0
        assert health.queue_depth == 0
        assert health.last_trade_ts is None
        assert health.last_insert_ts is None
        assert health.last_reconnect_ts is None
        assert health.started_at is None

    async def test_health_updates_on_trades(self) -> None:
        """Health counters update when trades are received and inserted."""
        listener = _make_listener(
            trade_buffer_size=10,
            trade_batch_drain_timeout_sec=0.5,
        )

        # Test _receive_loop health updates: mock WS to yield one trade
        event = _make_trade_event(asset_id="tok1")
        msg = json.dumps(event)

        ws = AsyncMock()
        ws.__aiter__ = lambda self: self
        messages = iter([msg])

        async def anext_impl(self):
            try:
                return next(messages)
            except StopIteration:
                raise StopAsyncIteration

        ws.__anext__ = anext_impl

        await listener._receive_loop(ws)

        assert listener.health.trades_received == 1
        assert listener.health.last_trade_ts is not None

        # Test _drain_loop health updates: pre-filled queue
        inserted_batches = []

        async def mock_insert(pool, batch):
            inserted_batches.append(list(batch))
            return len(batch)

        with patch(
            "src.collector.trade_listener.insert_trades",
            side_effect=mock_insert,
        ):
            task = asyncio.create_task(listener._drain_loop())
            await asyncio.sleep(0.3)
            listener._running = False
            await asyncio.sleep(0.8)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert listener.health.trades_inserted == 1
        assert listener.health.batches_inserted == 1
        assert listener.health.last_insert_ts is not None

    def test_get_health_returns_current_queue_depth(self) -> None:
        """get_health() returns a snapshot with current queue_depth."""
        listener = _make_listener()

        # Put 5 items in queue
        for i in range(5):
            listener._queue.put_nowait(
                _make_trade_tuple(token_id=f"tok{i}")
            )

        health = listener.get_health()

        assert health.queue_depth == 5
        # Verify it's a copy (modifying it doesn't affect the original)
        health.queue_depth = 999
        assert listener.health.queue_depth == 5
