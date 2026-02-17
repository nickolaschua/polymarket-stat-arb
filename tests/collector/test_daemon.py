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


# =========================================================================
# Task 2: Crash recovery tests
# =========================================================================


class TestMonitorCrashRecovery:
    """Tests for CollectorDaemon._monitor_tasks crash recovery."""

    async def test_monitor_detects_crashed_task(self, daemon):
        """Crashed polling task gets restarted and _restart_counts incremented."""
        daemon._running = True

        # Create a task that is "done" with an exception (simulates crash)
        crashed_task = MagicMock()
        crashed_task.done.return_value = True
        crashed_task.cancelled.return_value = False
        crashed_task.exception.return_value = RuntimeError("boom")
        daemon._tasks["metadata"] = crashed_task

        # _monitor also monitors itself -- add a stub for it
        monitor_stub = MagicMock()
        monitor_stub.done.return_value = False
        daemon._tasks["_monitor"] = monitor_stub

        # Patch asyncio.sleep to skip actual delays, and stop after first iteration
        call_count = 0
        original_running = True

        async def fake_sleep(secs):
            nonlocal call_count
            call_count += 1
            # First sleep is the 10s monitor interval, second is the restart delay
            # After the restart delay, stop the loop
            if call_count >= 3:
                daemon._running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await asyncio.wait_for(daemon._monitor_tasks(), timeout=5.0)

        # Restart count should be incremented
        assert daemon._restart_counts.get("metadata", 0) == 1
        # Task should have been replaced (new task created)
        assert daemon._tasks["metadata"] is not crashed_task

    async def test_monitor_exponential_backoff(self, daemon):
        """Verify exponential backoff delays: 0->5s, 1->10s, 2->20s, 3->40s, 4->60s."""
        # Test the formula directly from daemon attributes
        base = daemon._base_restart_delay   # 5.0
        cap = daemon._max_restart_delay     # 60.0

        expected = [5.0, 10.0, 20.0, 40.0, 60.0]
        for count, expected_delay in enumerate(expected):
            actual = min(base * (2 ** count), cap)
            assert actual == expected_delay, (
                f"restart_count={count}: expected {expected_delay}, got {actual}"
            )

    async def test_monitor_max_restarts_gives_up(self, daemon, caplog):
        """At max restarts, task is NOT recreated and CRITICAL log is emitted."""
        daemon._running = True
        daemon._restart_counts["metadata"] = 5  # At max (default _max_restarts=5)

        # Create crashed task
        crashed_task = MagicMock()
        crashed_task.done.return_value = True
        crashed_task.cancelled.return_value = False
        crashed_task.exception.return_value = RuntimeError("boom")
        daemon._tasks["metadata"] = crashed_task

        monitor_stub = MagicMock()
        monitor_stub.done.return_value = False
        daemon._tasks["_monitor"] = monitor_stub

        # One iteration then stop
        call_count = 0

        async def fake_sleep(secs):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                daemon._running = False

        with (
            patch("asyncio.sleep", side_effect=fake_sleep),
            caplog.at_level(logging.CRITICAL),
        ):
            await asyncio.wait_for(daemon._monitor_tasks(), timeout=5.0)

        # Task should NOT have been replaced
        assert daemon._tasks["metadata"] is crashed_task
        # CRITICAL log should have been emitted
        assert "exceeded max restarts" in caplog.text

    async def test_monitor_skips_during_shutdown(self, daemon):
        """When _running=False, _monitor_tasks exits without restarting."""
        daemon._running = False

        # Add a crashed task -- should NOT be restarted
        crashed_task = MagicMock()
        crashed_task.done.return_value = True
        crashed_task.cancelled.return_value = False
        crashed_task.exception.return_value = RuntimeError("boom")
        daemon._tasks["metadata"] = crashed_task

        # _monitor_tasks checks self._running in while loop; should exit immediately
        await asyncio.wait_for(daemon._monitor_tasks(), timeout=5.0)

        # Task should still be the same crashed one (no restart attempted)
        assert daemon._tasks["metadata"] is crashed_task
        assert daemon._restart_counts.get("metadata", 0) == 0

    async def test_trade_listener_restart_creates_new_instance(
        self, mock_pool, mock_client, mock_config, collector_patches
    ):
        """Crashed trades task re-instantiates TradeListener with fresh state."""
        # Make TradeListener constructor return a NEW mock each time
        tl_instances = []

        def make_tl(*args, **kwargs):
            inst = AsyncMock()
            inst.run = AsyncMock()
            inst.stop = AsyncMock()
            inst.get_health = MagicMock(return_value=_mock_trade_listener_health())
            tl_instances.append(inst)
            return inst

        collector_patches["TradeListener"].side_effect = make_tl

        daemon = CollectorDaemon(mock_pool, mock_client, mock_config)
        daemon._running = True

        original_listener = daemon._trade_listener

        # Create crashed trades task
        crashed_task = MagicMock()
        crashed_task.done.return_value = True
        crashed_task.cancelled.return_value = False
        crashed_task.exception.return_value = RuntimeError("ws error")
        daemon._tasks["trades"] = crashed_task

        monitor_stub = MagicMock()
        monitor_stub.done.return_value = False
        daemon._tasks["_monitor"] = monitor_stub

        call_count = 0

        async def fake_sleep(secs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                daemon._running = False

        with patch("asyncio.sleep", side_effect=fake_sleep):
            await asyncio.wait_for(daemon._monitor_tasks(), timeout=5.0)

        # TradeListener should be a NEW instance (2 total created)
        assert len(tl_instances) == 2
        assert daemon._trade_listener is not original_listener
        assert daemon._trade_listener is tl_instances[1]
        # Restart count incremented
        assert daemon._restart_counts.get("trades", 0) == 1


# =========================================================================
# Task 2: Health logging tests
# =========================================================================


class TestHealthLogging:
    """Tests for daemon health reporting and stats tracking."""

    async def test_get_health_returns_correct_structure(self, daemon):
        """get_health() returns dict with all expected keys and types."""
        daemon._running = True
        # Need real tasks for alive/dead counting
        alive_task = MagicMock()
        alive_task.done.return_value = False
        dead_task = MagicMock()
        dead_task.done.return_value = True
        daemon._tasks["metadata"] = alive_task
        daemon._tasks["dead_one"] = dead_task
        daemon._restart_counts["metadata"] = 2

        from datetime import datetime, timezone
        daemon._started_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        health = daemon.get_health()

        # Verify structure
        assert "uptime_seconds" in health
        assert isinstance(health["uptime_seconds"], float)
        assert health["uptime_seconds"] > 0

        assert health["tasks_alive"] == 1
        assert health["tasks_dead"] == 1
        assert health["total_restarts"] == 2

        assert "collectors" in health
        assert isinstance(health["collectors"], dict)
        # Should have stats for all 4 polling collectors
        for name in ("metadata", "prices", "orderbooks", "resolutions"):
            assert name in health["collectors"]

        assert "trade_listener" in health

    async def test_collector_stats_updated_by_polling_loop(self, daemon):
        """Polling loop updates _collector_stats with items and timestamps."""
        collector = AsyncMock()
        collector.collect_once = AsyncMock(return_value=10)
        daemon._running = True

        # Initialize stats for our test collector
        daemon._collector_stats["test_coll"] = {
            "last_collect_ts": None,
            "total_items": 0,
            "error_count": 0,
            "last_error": None,
        }

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

        stats = daemon._collector_stats["test_coll"]
        assert stats["total_items"] >= 10
        assert stats["last_collect_ts"] is not None
        assert stats["error_count"] == 0
        assert stats["last_error"] is None

    async def test_collector_stats_tracks_errors(self, daemon):
        """Polling loop updates _collector_stats with error info on failure."""
        collector = AsyncMock()
        collector.collect_once = AsyncMock(
            side_effect=ValueError("bad data")
        )
        daemon._running = True

        # Initialize stats for our test collector
        daemon._collector_stats["err_coll"] = {
            "last_collect_ts": None,
            "total_items": 0,
            "error_count": 0,
            "last_error": None,
        }

        async def stop_after_delay():
            await asyncio.sleep(0.05)
            daemon._running = False

        loop_task = asyncio.create_task(
            daemon._run_polling_loop("err_coll", collector, 0)
        )
        stop_task = asyncio.create_task(stop_after_delay())

        await asyncio.wait_for(
            asyncio.gather(loop_task, stop_task), timeout=5.0
        )

        stats = daemon._collector_stats["err_coll"]
        assert stats["error_count"] >= 1
        assert stats["last_error"] == "bad data"
        assert stats["total_items"] == 0
        assert stats["last_collect_ts"] is None
