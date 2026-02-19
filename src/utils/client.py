"""Polymarket API client wrapper."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams, OrderArgs, MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from src.config import Config, get_config
from src.utils.heartbeat import HeartbeatManager

logger = logging.getLogger(__name__)


class PolymarketClient:
    """Wrapper around Polymarket APIs with async support."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self._clob_client: Optional[ClobClient] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._authenticated = False
        self._heartbeat: Optional[HeartbeatManager] = None

    @property
    def clob(self) -> ClobClient:
        """Get or create the CLOB client (read-only by default)."""
        if self._clob_client is None:
            self._clob_client = ClobClient(self.config.polymarket.clob_host)
        return self._clob_client

    @property
    def http(self) -> httpx.AsyncClient:
        """Get or create async HTTP client for Gamma API."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "polymarket-stat-arb/1.0"}
            )
        return self._http_client

    def authenticate(self) -> bool:
        """
        Authenticate with trading credentials.
        Must be called before placing orders.
        """
        wallet = self.config.wallet
        
        if not wallet.private_key:
            logger.error("Private key environment variable is not set")
            return False
        
        if not wallet.funder_address:
            logger.error("Funder address not configured")
            return False

        self._clob_client = ClobClient(
            self.config.polymarket.clob_host,
            key=wallet.private_key,
            chain_id=self.config.polymarket.chain_id,
            signature_type=wallet.signature_type,
            funder=wallet.funder_address
        )
        
        try:
            self._clob_client.set_api_creds(
                self._clob_client.create_or_derive_api_creds()
            )
            self._authenticated = True
            logger.info("Successfully authenticated with Polymarket")
            return True
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    # =========================================================================
    # Market Data (Read-Only)
    # =========================================================================

    def get_markets(self) -> Dict[str, Any]:
        """Get simplified market list from CLOB."""
        return self.clob.get_simplified_markets()

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Get orderbook for a token."""
        return self.clob.get_order_book(token_id)

    def get_orderbooks(self, token_ids: List[str]) -> List[Dict[str, Any]]:
        """Get orderbooks for multiple tokens."""
        params = [BookParams(token_id=tid) for tid in token_ids]
        return self.clob.get_order_books(params)

    def get_price(self, token_id: str, side: str = "BUY") -> str:
        """Get current price for a token."""
        return self.clob.get_price(token_id, side=side)

    def get_midpoint(self, token_id: str) -> str:
        """Get midpoint price for a token."""
        return self.clob.get_midpoint(token_id)

    async def get_events(
        self,
        active: bool = True,
        limit: int = 100,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Fetch events from Gamma API."""
        params = {
            "active": str(active).lower(),
            "limit": limit,
            "offset": offset,
            "order": "volume",
            "ascending": "false"
        }
        
        url = f"{self.config.polymarket.gamma_host}/events"
        response = await self.http.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def get_event(self, event_id: str) -> Dict[str, Any]:
        """Fetch single event details."""
        url = f"{self.config.polymarket.gamma_host}/events/{event_id}"
        response = await self.http.get(url)
        response.raise_for_status()
        return response.json()

    async def get_all_active_markets(
        self, max_events: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Fetch active markets with pagination.

        Parameters
        ----------
        max_events:
            Stop after accumulating this many events.  ``None`` means no limit,
            but callers should pass ``config.collector.max_markets`` to avoid
            unbounded memory growth on large Polymarket event sets.
        """
        all_events: List[Dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            data = await self.get_events(active=True, limit=limit, offset=offset)
            events = data if isinstance(data, list) else data.get("data", [])

            if not events:
                break

            all_events.extend(events)
            offset += limit

            if max_events is not None and len(all_events) >= max_events:
                all_events = all_events[:max_events]
                break

            if len(events) < limit:
                break

            # Small delay to respect rate limits
            await asyncio.sleep(0.1)

        return all_events

    # =========================================================================
    # Trading (Requires Authentication)
    # =========================================================================

    def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float
    ) -> Dict[str, Any]:
        """
        Place a limit order.
        
        Args:
            token_id: The token to trade
            side: "BUY" or "SELL"
            price: Price in dollars (0.00 to 1.00)
            size: Number of shares
        """
        if not self._authenticated:
            raise RuntimeError("Must authenticate before trading")
        
        if self.config.paper_trading:
            logger.info(f"[PAPER] Would place {side} order: {size} @ ${price}")
            return {"paper_trade": True, "side": side, "price": price, "size": size}

        order_side = BUY if side.upper() == "BUY" else SELL
        order = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=order_side
        )
        
        signed = self.clob.create_order(order)
        return self.clob.post_order(signed, OrderType.GTC)

    def place_market_order(
        self,
        token_id: str,
        side: str,
        amount_usd: float
    ) -> Dict[str, Any]:
        """
        Place a market order (fill-or-kill).
        
        Args:
            token_id: The token to trade
            side: "BUY" or "SELL"
            amount_usd: Dollar amount to trade
        """
        if not self._authenticated:
            raise RuntimeError("Must authenticate before trading")
        
        if self.config.paper_trading:
            logger.info(f"[PAPER] Would place market {side}: ${amount_usd}")
            return {"paper_trade": True, "side": side, "amount": amount_usd}

        order_side = BUY if side.upper() == "BUY" else SELL
        order = MarketOrderArgs(
            token_id=token_id,
            amount=amount_usd,
            side=order_side,
            order_type=OrderType.FOK
        )
        
        signed = self.clob.create_market_order(order)
        return self.clob.post_order(signed, OrderType.FOK)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        if not self._authenticated:
            raise RuntimeError("Must authenticate before trading")
        return self.clob.cancel(order_id)

    def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders."""
        if not self._authenticated:
            raise RuntimeError("Must authenticate before trading")
        return self.clob.cancel_all()

    def get_open_orders(self) -> List[Dict[str, Any]]:
        """Get all open orders."""
        if not self._authenticated:
            raise RuntimeError("Must authenticate to view orders")
        from py_clob_client.clob_types import OpenOrderParams
        return self.clob.get_orders(OpenOrderParams())

    # =========================================================================
    # Heartbeat Management
    # =========================================================================

    @property
    def heartbeat(self) -> Optional[HeartbeatManager]:
        """Get the heartbeat manager (available after authentication)."""
        return self._heartbeat

    async def start_heartbeat(self, on_failure=None):
        """Start sending heartbeats to keep open orders alive.

        IMPORTANT: Only call this when you are about to place orders.
        Once started, stopping unexpectedly cancels ALL open orders.

        Args:
            on_failure: Optional async callback invoked when heartbeats
                       fail persistently. Use for emergency alerts.
        """
        if not self._authenticated:
            raise RuntimeError("Must authenticate before starting heartbeat")
        if self._heartbeat and self._heartbeat.is_running:
            logger.warning("Heartbeat already running")
            return

        self._heartbeat = HeartbeatManager(self._clob_client)
        if on_failure:
            self._heartbeat.on_failure(on_failure)
        await self._heartbeat.start()

    async def stop_heartbeat(self):
        """Stop sending heartbeats. Orders will be cancelled by Polymarket."""
        if self._heartbeat:
            await self._heartbeat.stop()

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def close(self):
        """Clean up resources."""
        if self._heartbeat and self._heartbeat.is_running:
            await self._heartbeat.stop()
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
