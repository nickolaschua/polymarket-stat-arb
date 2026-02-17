"""WebSocket trade listener for Polymarket CLOB market channel.

Connects to the Polymarket WebSocket trade stream, subscribes to active
markets, and streams every ``last_trade_price`` event into an
``asyncio.Queue``.  A drain loop batches queued trades and bulk-inserts
them via ``insert_trades()``.

Usage::

    listener = TradeListener(pool, config)
    # start/stop managed by daemon supervisor (Phase 4)

Key design decisions:
- ``websockets`` async iterator for auto-reconnect (no hand-rolled retry)
- ``asyncio.Queue`` decouples receive from DB writes
- ``put_nowait`` in receive loop to avoid blocking (would miss heartbeat)
- App-level ``"PING"`` every 10s (Polymarket requirement, separate from
  protocol ping/pong)
- ``trade_id = None`` for all WS trades (not in event payload)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from src.config import CollectorConfig, get_config
from src.db.queries.trades import insert_trades

logger = logging.getLogger(__name__)


def parse_trade_event(event: dict) -> Optional[tuple]:
    """Parse a single WebSocket trade event into a DB-ready tuple.

    Parameters
    ----------
    event:
        A dict from the CLOB WebSocket market channel.  Only events
        with ``event_type == "last_trade_price"`` are processed.

    Returns
    -------
    tuple or None
        A 6-tuple ``(ts, token_id, side, price, size, trade_id)``
        ready for ``insert_trades()``, or ``None`` if the event is
        not a trade or conversion fails.

    Notes
    -----
    This function **never raises**.  Any conversion error returns
    ``None`` with a warning log so that one malformed event cannot
    crash the receive loop.
    """
    try:
        if event.get("event_type") != "last_trade_price":
            return None

        ts = datetime.fromtimestamp(
            int(event["timestamp"]) / 1000, tz=timezone.utc
        )
        token_id = event["asset_id"]
        side = event["side"]
        price = float(event["price"])
        size = float(event["size"])
        trade_id = None  # Not in WS events (RESEARCH.md pitfall 2)

        return (ts, token_id, side, price, size, trade_id)

    except Exception:
        logger.warning(
            "Failed to parse trade event: %s",
            event,
            exc_info=True,
        )
        return None


class TradeListener:
    """WebSocket trade stream listener with producer-consumer queue.

    Connects to the Polymarket CLOB WebSocket market channel,
    subscribes to the given token IDs, and streams parsed trade
    events into an internal queue.  A drain loop batches queued
    trades and bulk-inserts them into TimescaleDB.

    Parameters
    ----------
    pool:
        asyncpg connection pool for database writes.
    config:
        Collector configuration (buffer sizes, intervals, etc.).
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        config: CollectorConfig,
    ) -> None:
        self.pool = pool
        self.config = config
        self._ws_url = get_config().polymarket.ws_host + "/ws/market"
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def _subscribe(self, ws, token_ids: list[str]) -> None:
        """Send subscription message for a list of token IDs.

        Parameters
        ----------
        ws:
            An open WebSocket connection.
        token_ids:
            List of CLOB token IDs to subscribe to.
        """
        msg = json.dumps({"assets_ids": token_ids, "type": "market"})
        await ws.send(msg)
        logger.info("Subscribed to %d tokens", len(token_ids))

    async def _ping_loop(self, ws) -> None:
        """Send application-level PING at the configured interval.

        Polymarket requires a text ``"PING"`` every 10 seconds
        (separate from WebSocket protocol-level ping/pong).

        Parameters
        ----------
        ws:
            An open WebSocket connection.
        """
        try:
            while self._running:
                await asyncio.sleep(self.config.ws_ping_interval_sec)
                await ws.send("PING")
        except asyncio.CancelledError:
            return

    async def _receive_loop(self, ws) -> None:
        """Read messages from the WebSocket and enqueue parsed trades.

        Events may arrive as a single JSON dict or a JSON array of
        dicts.  Each event is parsed via ``parse_trade_event()`` and
        enqueued with ``put_nowait`` to avoid blocking the receive
        loop (which would cause missed heartbeats).

        Parameters
        ----------
        ws:
            An open WebSocket connection.
        """
        async for raw in ws:
            parsed = json.loads(raw)
            events = parsed if isinstance(parsed, list) else [parsed]
            for event in events:
                trade = parse_trade_event(event)
                if trade is not None:
                    try:
                        self._queue.put_nowait(trade)
                    except asyncio.QueueFull:
                        logger.warning("Trade queue full, dropping event")

    async def _drain_loop(self) -> None:
        """Consume trades from the queue and batch-insert into the DB.

        Waits for the first trade (with timeout), then greedily drains
        up to ``trade_buffer_size`` items before inserting.  Continues
        until ``_running`` is ``False`` and the queue is empty.
        """
        while self._running or not self._queue.empty():
            batch: list[tuple] = []
            try:
                trade = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=self.config.trade_batch_drain_timeout_sec,
                )
                batch.append(trade)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Drain remaining items up to batch_size
            while len(batch) < self.config.trade_buffer_size:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Insert batch
            if batch:
                try:
                    await insert_trades(self.pool, batch)
                    logger.info("Inserted %d trades", len(batch))
                except Exception:
                    logger.error(
                        "Failed to insert %d trades",
                        len(batch),
                        exc_info=True,
                    )

    async def _listen_single(self, token_ids: list[str]) -> None:
        """Run a single WebSocket connection with auto-reconnect.

        Uses the ``websockets`` async iterator pattern for automatic
        reconnection with exponential backoff.  Re-subscribes on every
        (re)connect since subscriptions are ephemeral.

        Parameters
        ----------
        token_ids:
            List of CLOB token IDs to subscribe to on this connection
            (max 500 per Polymarket limit).
        """
        async for ws in connect(self._ws_url):
            try:
                await self._subscribe(ws, token_ids)
                ping_task = asyncio.create_task(self._ping_loop(ws))
                try:
                    await self._receive_loop(ws)
                finally:
                    ping_task.cancel()
                    try:
                        await ping_task
                    except asyncio.CancelledError:
                        pass
            except ConnectionClosed:
                logger.warning("WebSocket disconnected, reconnecting...")
                continue
            except asyncio.CancelledError:
                break
