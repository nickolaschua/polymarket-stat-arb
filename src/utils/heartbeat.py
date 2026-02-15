"""Heartbeat manager for Polymarket CLOB order protection.

The Polymarket CLOB requires heartbeats every 10 seconds once started.
If heartbeats stop, ALL open orders are automatically cancelled.
This module provides a background heartbeat task with proper error handling.

Usage:
    heartbeat = HeartbeatManager(clob_client)
    await heartbeat.start()   # Begin sending heartbeats
    # ... place orders, trade ...
    await heartbeat.stop()    # Gracefully stop heartbeats

IMPORTANT:
- Do NOT start heartbeats unless you have a reliable connection.
- Once started, missing heartbeats = all orders cancelled.
- The manager sends heartbeats every 8 seconds (2s safety margin).
"""

import asyncio
import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# Polymarket requires heartbeats every 10 seconds.
# We send every 8 seconds to leave a 2-second safety margin.
HEARTBEAT_INTERVAL_SECONDS = 8

# After this many consecutive failures, stop heartbeating and
# trigger an emergency callback (if registered).
MAX_CONSECUTIVE_FAILURES = 3


class HeartbeatManager:
    """Manages background heartbeat sending for Polymarket CLOB.

    Once started, sends heartbeats every 8 seconds to keep open orders
    alive. Tracks consecutive failures and can trigger an emergency
    callback if heartbeats are persistently failing.
    """

    def __init__(self, clob_client, session_id: Optional[str] = None):
        """
        Args:
            clob_client: An authenticated py-clob-client ClobClient instance.
            session_id: Optional heartbeat session ID. If not provided,
                       a unique ID is generated per session.
        """
        self._client = clob_client
        self._session_id = session_id or f"bot-{uuid.uuid4().hex[:12]}"
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._consecutive_failures = 0
        self._total_heartbeats_sent = 0
        self._last_heartbeat_time: Optional[float] = None
        self._on_failure_callback = None
        self._failure_callback_fired = False

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def stats(self) -> dict:
        """Return heartbeat statistics for monitoring."""
        return {
            "session_id": self._session_id,
            "running": self.is_running,
            "total_sent": self._total_heartbeats_sent,
            "consecutive_failures": self._consecutive_failures,
            "last_heartbeat": self._last_heartbeat_time,
            "seconds_since_last": (
                time.time() - self._last_heartbeat_time
                if self._last_heartbeat_time
                else None
            ),
        }

    def on_failure(self, callback):
        """Register a callback for when heartbeats persistently fail.

        The callback receives a dict with failure details. Use this to
        trigger emergency order cancellation or alerting.

        Example:
            async def emergency_handler(details):
                await send_telegram_alert("Heartbeat failed!")
                client.cancel_all()

            heartbeat.on_failure(emergency_handler)
        """
        self._on_failure_callback = callback

    async def start(self):
        """Start sending heartbeats in the background.

        IMPORTANT: Only call this when you have open orders or are
        about to place them. Once started, stopping unexpectedly
        will cancel all your orders.
        """
        if self.is_running:
            logger.warning("Heartbeat already running (session=%s)", self._session_id)
            return

        self._running = True
        self._consecutive_failures = 0
        self._task = asyncio.create_task(self._heartbeat_loop())
        logger.info(
            "Heartbeat started (session=%s, interval=%ds)",
            self._session_id,
            HEARTBEAT_INTERVAL_SECONDS,
        )

    async def stop(self):
        """Gracefully stop sending heartbeats.

        Note: After stopping, Polymarket will cancel all open orders
        within ~10 seconds. Make sure you've already cancelled your
        orders or are okay with them being cancelled.
        """
        if not self._running:
            return

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info(
            "Heartbeat stopped (session=%s, total_sent=%d)",
            self._session_id,
            self._total_heartbeats_sent,
        )

    async def send_once(self) -> bool:
        """Send a single heartbeat. Returns True on success."""
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._client.post_heartbeat, self._session_id
            )
            self._last_heartbeat_time = time.time()
            self._total_heartbeats_sent += 1
            self._consecutive_failures = 0
            self._failure_callback_fired = False
            logger.debug("Heartbeat sent (session=%s, #%d)", self._session_id, self._total_heartbeats_sent)
            return True
        except Exception as e:
            self._consecutive_failures += 1
            logger.error(
                "Heartbeat failed (session=%s, consecutive=%d/%d): %s",
                self._session_id,
                self._consecutive_failures,
                MAX_CONSECUTIVE_FAILURES,
                e,
            )
            return False

    async def _heartbeat_loop(self):
        """Background loop that sends heartbeats at regular intervals."""
        try:
            while self._running:
                success = await self.send_once()

                if not success and self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.critical(
                        "Heartbeat failed %d times consecutively! "
                        "Orders will be cancelled by Polymarket. (session=%s)",
                        MAX_CONSECUTIVE_FAILURES,
                        self._session_id,
                    )
                    if not self._failure_callback_fired:
                        await self._handle_persistent_failure()
                        self._failure_callback_fired = True
                    # Keep trying in case connection recovers

                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)

        except asyncio.CancelledError:
            logger.debug("Heartbeat loop cancelled (session=%s)", self._session_id)
        except Exception as e:
            self._running = False
            logger.critical(
                "Heartbeat loop crashed unexpectedly (session=%s): %s",
                self._session_id,
                e,
            )
            await self._handle_persistent_failure()

    async def _handle_persistent_failure(self):
        """Called when heartbeats have failed MAX_CONSECUTIVE_FAILURES times."""
        if self._on_failure_callback:
            try:
                details = {
                    "session_id": self._session_id,
                    "consecutive_failures": self._consecutive_failures,
                    "last_success": self._last_heartbeat_time,
                    "seconds_since_last": (
                        time.time() - self._last_heartbeat_time
                        if self._last_heartbeat_time
                        else None
                    ),
                }
                if asyncio.iscoroutinefunction(self._on_failure_callback):
                    await self._on_failure_callback(details)
                else:
                    self._on_failure_callback(details)
            except Exception as e:
                logger.error("Heartbeat failure callback raised: %s", e)
