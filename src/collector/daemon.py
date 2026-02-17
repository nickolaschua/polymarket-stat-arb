"""Collector daemon orchestrator.

Manages all 5 data collectors as concurrent asyncio tasks with graceful
shutdown, cross-platform signal handling, and crash recovery.

The daemon is the single entry point for 24/7 data collection.  It starts
four polling collectors (metadata, prices, orderbooks, resolutions) and
one WebSocket-based trade listener, then blocks until a shutdown signal
is received.

Usage::

    daemon = CollectorDaemon(pool, client, config)
    await daemon.run()   # blocks until SIGINT/SIGTERM
"""

import asyncio
import logging
import signal
import sys

import asyncpg

from src.collector.market_metadata import MarketMetadataCollector
from src.collector.orderbook_snapshots import OrderbookSnapshotCollector
from src.collector.price_snapshots import PriceSnapshotCollector
from src.collector.resolution_tracker import ResolutionTracker
from src.collector.trade_listener import TradeListener
from src.config import CollectorConfig
from src.utils.client import PolymarketClient

logger = logging.getLogger(__name__)


class CollectorDaemon:
    """Orchestrates all data collectors as concurrent asyncio tasks.

    Parameters
    ----------
    pool:
        asyncpg connection pool for database writes.
    client:
        PolymarketClient instance for API calls (metadata, prices, orderbooks).
    config:
        Collector configuration (intervals, limits, etc.).
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        client: PolymarketClient,
        config: CollectorConfig,
    ) -> None:
        self.pool = pool
        self.client = client
        self.config = config

        # Instantiate all 5 collectors
        self._metadata = MarketMetadataCollector(pool, client, config)
        self._prices = PriceSnapshotCollector(pool, client, config)
        self._orderbooks = OrderbookSnapshotCollector(pool, client, config)
        self._resolutions = ResolutionTracker(pool, config)  # NO client param
        self._trade_listener = TradeListener(pool, config)   # NO client param

        # Daemon state
        self._running = False
        self._tasks: dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

        # Crash recovery state
        self._restart_counts: dict[str, int] = {}
        self._max_restarts: int = 5
        self._base_restart_delay: float = 5.0
        self._max_restart_delay: float = 60.0

        # Store collector-interval mapping for restart (populated in run())
        self._polling_collectors: dict[str, tuple[object, int]] = {
            "metadata": (self._metadata, config.metadata_interval_sec),
            "prices": (self._prices, config.price_interval_sec),
            "orderbooks": (self._orderbooks, config.orderbook_interval_sec),
            "resolutions": (
                self._resolutions,
                config.resolution_check_interval_sec,
            ),
        }

    async def _run_polling_loop(
        self, name: str, collector: object, interval_sec: int
    ) -> None:
        """Run a polling collector in an infinite loop.

        Calls ``collector.collect_once()`` at the configured interval.
        Catches all exceptions except ``CancelledError`` to ensure one
        collector failure does not crash the loop.

        Parameters
        ----------
        name:
            Human-readable collector name for logging.
        collector:
            A collector instance with an async ``collect_once()`` method.
        interval_sec:
            Seconds to sleep between collection cycles.
        """
        while self._running:
            try:
                count = await collector.collect_once()
                logger.debug("%s: collected %d items", name, count)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.error(
                    "%s: collection error", name, exc_info=True
                )
            await asyncio.sleep(interval_sec)

    async def _monitor_tasks(self) -> None:
        """Monitor running tasks and restart crashed ones.

        Runs every 10 seconds, checking for tasks that have finished
        unexpectedly (done but not cancelled).  Crashed tasks are
        restarted with exponential backoff (5s -> 10s -> 20s -> 40s ->
        60s cap), up to ``_max_restarts`` times per collector.

        The TradeListener is fully recreated on crash because its
        internal state (queue, health, tasks) may be corrupted.
        Polling collectors reuse the existing collector instance.
        """
        while self._running:
            await asyncio.sleep(10)
            for name in list(self._tasks.keys()):
                if name == "_monitor":
                    continue
                task = self._tasks[name]
                if not task.done() or task.cancelled():
                    continue

                # Task finished unexpectedly
                try:
                    exc = task.exception()
                except (asyncio.CancelledError, asyncio.InvalidStateError):
                    continue

                logger.error("Task '%s' crashed: %s", name, exc)

                count = self._restart_counts.get(name, 0)
                if count >= self._max_restarts:
                    logger.critical(
                        "Task '%s' exceeded max restarts (%d), giving up",
                        name,
                        self._max_restarts,
                    )
                    continue

                delay = min(
                    self._base_restart_delay * (2 ** count),
                    self._max_restart_delay,
                )
                logger.warning(
                    "Restarting '%s' in %.0fs (attempt %d/%d)",
                    name,
                    delay,
                    count + 1,
                    self._max_restarts,
                )
                await asyncio.sleep(delay)

                # May have shut down during the delay
                if not self._running:
                    return

                # Recreate the task
                if name == "trades":
                    # Recreate TradeListener — internal state may be
                    # corrupted after crash
                    self._trade_listener = TradeListener(
                        self.pool, self.config
                    )
                    self._tasks[name] = asyncio.create_task(
                        self._trade_listener.run()
                    )
                elif name in self._polling_collectors:
                    collector, interval = self._polling_collectors[name]
                    self._tasks[name] = asyncio.create_task(
                        self._run_polling_loop(name, collector, interval)
                    )

                self._restart_counts[name] = count + 1

    async def run(self) -> None:
        """Start all collectors and block until shutdown signal.

        Registers cross-platform signal handlers:
        - On non-Windows: ``loop.add_signal_handler`` for SIGINT and SIGTERM
        - On Windows: ``signal.signal`` for SIGINT (loop.add_signal_handler
          is not supported on Windows)

        After all tasks are started, blocks on the shutdown event.
        When the event is set (via signal), calls ``stop()`` for graceful
        shutdown.
        """
        self._running = True
        loop = asyncio.get_running_loop()

        # Register signal handlers for graceful shutdown
        if sys.platform != "win32":
            loop.add_signal_handler(signal.SIGINT, self._shutdown_event.set)
            loop.add_signal_handler(signal.SIGTERM, self._shutdown_event.set)
        else:
            signal.signal(
                signal.SIGINT, lambda s, f: self._shutdown_event.set()
            )

        # Start 4 polling tasks
        self._tasks["metadata"] = asyncio.create_task(
            self._run_polling_loop(
                "metadata", self._metadata, self.config.metadata_interval_sec
            )
        )
        self._tasks["prices"] = asyncio.create_task(
            self._run_polling_loop(
                "prices", self._prices, self.config.price_interval_sec
            )
        )
        self._tasks["orderbooks"] = asyncio.create_task(
            self._run_polling_loop(
                "orderbooks",
                self._orderbooks,
                self.config.orderbook_interval_sec,
            )
        )
        self._tasks["resolutions"] = asyncio.create_task(
            self._run_polling_loop(
                "resolutions",
                self._resolutions,
                self.config.resolution_check_interval_sec,
            )
        )

        # Start trade listener (run/stop lifecycle, not polling)
        self._tasks["trades"] = asyncio.create_task(
            self._trade_listener.run()
        )

        # Start crash-recovery monitor
        self._tasks["_monitor"] = asyncio.create_task(self._monitor_tasks())

        logger.info("Daemon started with %d tasks", len(self._tasks))

        # Block until shutdown signal
        await self._shutdown_event.wait()
        await self.stop()

    async def stop(self) -> None:
        """Gracefully stop all collectors and the daemon.

        Idempotent -- safe to call multiple times.  Cancels all polling
        tasks, calls ``TradeListener.stop()`` for graceful queue flush,
        then gathers all tasks to ensure clean termination.
        """
        if not self._running:
            return
        self._running = False
        logger.info("Daemon shutting down...")

        # Cancel polling tasks and monitor
        for name in (
            "metadata", "prices", "orderbooks", "resolutions", "_monitor"
        ):
            task = self._tasks.get(name)
            if task and not task.done():
                task.cancel()

        # Gracefully stop TradeListener (flushes queue before stopping)
        await self._trade_listener.stop()

        # Wait for all tasks to finish
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

        logger.info("Daemon stopped")
