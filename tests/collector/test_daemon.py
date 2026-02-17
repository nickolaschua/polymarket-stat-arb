"""Tests for CollectorDaemon orchestrator.

Covers lifecycle management, crash recovery with exponential backoff,
and health/stats tracking.  All tests are pure unit tests -- no real
database, no network, no testcontainers.

Uses unittest.mock to patch all 5 collector constructors so that
``CollectorDaemon.__init__`` never touches real I/O.
"""

import asyncio
import logging
from dataclasses import dataclass
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from src.collector.daemon import CollectorDaemon
from src.collector.trade_listener import TradeListenerHealth
from src.config import CollectorConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_trade_listener_health() -> TradeListenerHealth:
    """Return a TradeListenerHealth with plausible test values."""
    health = TradeListenerHealth()
    health.trades_received = 42
    health.trades_inserted = 40
    health.connections_active = 2
    health.queue_depth = 3
    return health


def _make_collector_patches():
    """Return a dict of 5 mock.patch context managers for all collectors.

    Each patch replaces the collector *class* inside ``src.collector.daemon``
    with a MagicMock whose return_value is an AsyncMock.  Calling the class
    (i.e., inside ``CollectorDaemon.__init__``) produces the AsyncMock
    instance with ``collect_once`` pre-configured.
    """
    patches = {}
    for name in (
        "MarketMetadataCollector",
        "PriceSnapshotCollector",
        "OrderbookSnapshotCollector",
        "ResolutionTracker",
    ):
        m = MagicMock()
        instance = AsyncMock()
        instance.collect_once = AsyncMock(return_value=5)
        m.return_value = instance
        patches[name] = m

    # TradeListener needs run/stop/get_health
    tl = MagicMock()
    tl_instance = AsyncMock()
    tl_instance.run = AsyncMock()
    tl_instance.stop = AsyncMock()
    tl_instance.get_health = MagicMock(return_value=_mock_trade_listener_health())
    tl.return_value = tl_instance
    patches["TradeListener"] = tl

    return patches


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_pool():
    """asyncpg.Pool mock -- never actually used by mocked collectors."""
    return AsyncMock(spec=asyncpg.Pool)


@pytest.fixture
def mock_client():
    """PolymarketClient mock."""
    return MagicMock()


@pytest.fixture
def mock_config():
    """CollectorConfig with short intervals for fast tests."""
    return CollectorConfig(
        price_interval_sec=1,
        orderbook_interval_sec=1,
        metadata_interval_sec=1,
        resolution_check_interval_sec=1,
        trade_buffer_size=100,
        max_markets=10,
        ws_ping_interval_sec=1,
        ws_max_instruments_per_conn=50,
        trade_batch_drain_timeout_sec=1.0,
    )


@pytest.fixture
def collector_patches():
    """Apply all 5 collector patches and yield the mock classes."""
    mocks = _make_collector_patches()
    with (
        patch("src.collector.daemon.MarketMetadataCollector", mocks["MarketMetadataCollector"]),
        patch("src.collector.daemon.PriceSnapshotCollector", mocks["PriceSnapshotCollector"]),
        patch("src.collector.daemon.OrderbookSnapshotCollector", mocks["OrderbookSnapshotCollector"]),
        patch("src.collector.daemon.ResolutionTracker", mocks["ResolutionTracker"]),
        patch("src.collector.daemon.TradeListener", mocks["TradeListener"]),
    ):
        yield mocks


@pytest.fixture
def daemon(mock_pool, mock_client, mock_config, collector_patches):
    """CollectorDaemon with all collectors mocked."""
    return CollectorDaemon(mock_pool, mock_client, mock_config)


# =========================================================================
# Task 1: Lifecycle tests
# =========================================================================


class TestDaemonInit:
    """Tests for CollectorDaemon constructor."""

    def test_init_creates_all_collectors(
        self, mock_pool, mock_client, mock_config, collector_patches
    ):
        """All 5 collector classes are instantiated with correct args."""
        daemon = CollectorDaemon(mock_pool, mock_client, mock_config)

        # 3 collectors that take (pool, client, config)
        collector_patches["MarketMetadataCollector"].assert_called_once_with(
            mock_pool, mock_client, mock_config
        )
        collector_patches["PriceSnapshotCollector"].assert_called_once_with(
            mock_pool, mock_client, mock_config
        )
        collector_patches["OrderbookSnapshotCollector"].assert_called_once_with(
            mock_pool, mock_client, mock_config
        )

        # 2 collectors that take (pool, config) -- NO client
        collector_patches["ResolutionTracker"].assert_called_once_with(
            mock_pool, mock_config
        )
        collector_patches["TradeListener"].assert_called_once_with(
            mock_pool, mock_config
        )


class TestDaemonRun:
    """Tests for CollectorDaemon.run() task creation."""

    async def test_run_starts_all_tasks(self, daemon):
        """run() creates 7 asyncio tasks (4 polling + trades + monitor + health)."""
        # Set the shutdown event immediately so run() does not block
        daemon._shutdown_event.set()

        await asyncio.wait_for(daemon.run(), timeout=5.0)

        # After run() completes, _tasks should have 7 entries
        expected_keys = {
            "metadata", "prices", "orderbooks", "resolutions",
            "trades", "_monitor", "_health",
        }
        assert set(daemon._tasks.keys()) == expected_keys


class TestDaemonStop:
    """Tests for CollectorDaemon.stop()."""

    async def test_stop_cancels_polling_tasks(self, daemon):
        """stop() cancels polling/monitor/health tasks and awaits TradeListener.stop()."""
        daemon._running = True

        # Create mock tasks for each slot
        cancel_names = [
            "metadata", "prices", "orderbooks", "resolutions",
            "_monitor", "_health",
        ]
        for name in cancel_names:
            task = MagicMock()
            task.done.return_value = False
            daemon._tasks[name] = task

        # Trades task -- should NOT be cancelled directly, stop() is used
        trades_task = MagicMock()
        trades_task.done.return_value = False
        daemon._tasks["trades"] = trades_task

        # Make gather a no-op (tasks are mocks, not real asyncio.Tasks)
        with patch("asyncio.gather", new_callable=AsyncMock):
            await asyncio.wait_for(daemon.stop(), timeout=5.0)

        # Polling tasks should have cancel() called
        for name in cancel_names:
            daemon._tasks[name].cancel.assert_called_once()

        # TradeListener.stop() should have been awaited
        daemon._trade_listener.stop.assert_awaited_once()

        # _running should be False
        assert daemon._running is False

    async def test_stop_is_idempotent(self, daemon):
        """Calling stop() twice does not raise."""
        daemon._running = True

        for name in ["metadata", "prices", "orderbooks", "resolutions",
                      "_monitor", "_health", "trades"]:
            task = MagicMock()
            task.done.return_value = False
            daemon._tasks[name] = task

        with patch("asyncio.gather", new_callable=AsyncMock):
            await asyncio.wait_for(daemon.stop(), timeout=5.0)
            # Second call should be a no-op (returns immediately)
            await asyncio.wait_for(daemon.stop(), timeout=5.0)

        assert daemon._running is False


class TestPollingLoop:
    """Tests for CollectorDaemon._run_polling_loop."""

    async def test_polling_loop_calls_collect_once(self, daemon):
        """_run_polling_loop calls collector.collect_once() at least once."""
        collector = AsyncMock()
        collector.collect_once = AsyncMock(return_value=10)
        daemon._running = True

        async def stop_after_delay():
            await asyncio.sleep(0.05)
            daemon._running = False

        loop_task = asyncio.create_task(
            daemon._run_polling_loop("test_coll", collector, 0)
        )
        stop_task = asyncio.create_task(stop_after_delay())

        await asyncio.wait_for(
            asyncio.gather(loop_task, stop_task), timeout=5.0
        )

        assert collector.collect_once.await_count >= 1

    async def test_polling_loop_survives_exception(self, daemon, caplog):
        """_run_polling_loop continues after collect_once raises."""
        collector = AsyncMock()
        collector.collect_once = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        daemon._running = True

        async def stop_after_delay():
            await asyncio.sleep(0.1)
            daemon._running = False

        with caplog.at_level(logging.ERROR):
            loop_task = asyncio.create_task(
                daemon._run_polling_loop("test_coll", collector, 0)
            )
            stop_task = asyncio.create_task(stop_after_delay())

            await asyncio.wait_for(
                asyncio.gather(loop_task, stop_task), timeout=5.0
            )

        # Should have been called multiple times despite errors
        assert collector.collect_once.await_count >= 2
        # Error should have been logged
        assert "collection error" in caplog.text
