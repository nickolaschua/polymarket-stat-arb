"""Tests for WebSocket trade listener parsing and components.

All tests are mock-based (no real WebSocket connections) due to
geoblocking constraints.  Uses unittest.mock.AsyncMock for WebSocket
object mocking and pytest-asyncio (auto mode) for async tests.
"""

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.collector.trade_listener import TradeListener, parse_trade_event
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
) -> TradeListener:
    """Create a TradeListener with a mock pool and given config."""
    config = CollectorConfig(
        trade_buffer_size=trade_buffer_size,
        ws_ping_interval_sec=ws_ping_interval_sec,
        trade_batch_drain_timeout_sec=trade_batch_drain_timeout_sec,
    )
    pool = AsyncMock()
    listener = TradeListener(pool=pool, config=config)
    listener._running = True
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
