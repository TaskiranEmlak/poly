"""
Polymarket WebSocket Feed
==========================

Real-time order book and trade updates from Polymarket CLOB.
"""

import asyncio
import json
from decimal import Decimal
from typing import Callable, Optional, Dict, List, Awaitable
from datetime import datetime
import websockets
import structlog

logger = structlog.get_logger()


class PolymarketFeed:
    """
    Streams real-time order book updates from Polymarket.
    
    Uses the CLOB WebSocket API for market data.
    This is the feed we compare against Binance to find latency opportunities.
    """
    
    def __init__(
        self,
        on_orderbook_update: Callable[[str, dict], Awaitable[None]],
        wss_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/"
    ):
        """
        Args:
            on_orderbook_update: Async callback(token_id, orderbook) on update
            wss_url: Polymarket WebSocket URL
        """
        self.on_orderbook_update = on_orderbook_update
        self.wss_url = wss_url
        
        # State
        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._subscribed_tokens: List[str] = []
        
        # Local orderbook cache
        self._orderbooks: Dict[str, dict] = {}
        
        # Stats
        self.messages_received = 0
        self.reconnect_count = 0
    
    async def connect(self):
        """
        Connect to Polymarket WebSocket.
        Automatically reconnects on disconnect.
        """
        self._running = True
        
        logger.info("polymarket_feed_starting", url=self.wss_url)
        
        while self._running:
            try:
                async with websockets.connect(
                    self.wss_url,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    self._ws = ws
                    logger.info("polymarket_feed_connected")
                    
                    # Re-subscribe to tokens on reconnect
                    for token_id in self._subscribed_tokens:
                        await self._send_subscribe(token_id)
                    
                    # Start ping task
                    ping_task = asyncio.create_task(self._ping_loop())
                    
                    try:
                        async for message in ws:
                            if not self._running:
                                break
                            
                            await self._handle_message(message)
                    finally:
                        ping_task.cancel()
                        
            except websockets.ConnectionClosed as e:
                if self._running:
                    self.reconnect_count += 1
                    logger.warning(
                        "polymarket_feed_disconnected",
                        reason=str(e),
                        reconnect_count=self.reconnect_count
                    )
                    await asyncio.sleep(1)
                    continue
                break
            except Exception as e:
                if self._running:
                    logger.error("polymarket_feed_error", error=str(e))
                    await asyncio.sleep(2)
                    continue
                break
        
        logger.info("polymarket_feed_stopped")
    
    async def _ping_loop(self):
        """Keep connection alive with pings."""
        while self._running and self._ws:
            try:
                await asyncio.sleep(25)
                if self._ws:
                    await self._ws.ping()
            except Exception:
                break
    
    async def subscribe(self, token_id: str):
        """Subscribe to order book updates for a token."""
        if token_id not in self._subscribed_tokens:
            self._subscribed_tokens.append(token_id)
        
        if self._ws:
            await self._send_subscribe(token_id)
    
    async def _send_subscribe(self, token_id: str):
        """Send subscription message."""
        if not self._ws:
            return
        
        subscribe_msg = {
            "auth": {},
            "type": "subscribe",
            "channel": "market",
            "markets": [token_id]
        }
        
        await self._ws.send(json.dumps(subscribe_msg))
        logger.info("polymarket_subscribed", token_id=token_id[:16] + "...")
    
    async def unsubscribe(self, token_id: str):
        """Unsubscribe from a token."""
        if token_id in self._subscribed_tokens:
            self._subscribed_tokens.remove(token_id)
        
        if self._ws:
            unsubscribe_msg = {
                "type": "unsubscribe",
                "channel": "market",
                "markets": [token_id]
            }
            await self._ws.send(json.dumps(unsubscribe_msg))
    
    async def _handle_message(self, message: str):
        """Process incoming WebSocket message."""
        try:
            data = json.loads(message)
            self.messages_received += 1
            
            msg_type = data.get("type", "")
            
            if msg_type == "book":
                # Order book update
                token_id = data.get("market", "")
                
                orderbook = {
                    "token_id": token_id,
                    "bids": self._parse_orders(data.get("bids", [])),
                    "asks": self._parse_orders(data.get("asks", [])),
                    "timestamp": datetime.now().isoformat()
                }
                
                self._orderbooks[token_id] = orderbook
                
                await self.on_orderbook_update(token_id, orderbook)
                
            elif msg_type == "price_change":
                # Price update (simpler than full book)
                token_id = data.get("market", "")
                
                if token_id in self._orderbooks:
                    # Update existing book
                    if "price" in data:
                        self._orderbooks[token_id]["last_price"] = data["price"]
                    
                    await self.on_orderbook_update(
                        token_id,
                        self._orderbooks[token_id]
                    )
            
            elif msg_type == "error":
                logger.warning("polymarket_ws_error", data=data)
                
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("polymarket_message_parse_error", error=str(e))
    
    def _parse_orders(self, orders: list) -> List[dict]:
        """Parse order list to standard format."""
        parsed = []
        for order in orders:
            if isinstance(order, dict):
                parsed.append({
                    "price": Decimal(str(order.get("price", 0))),
                    "size": Decimal(str(order.get("size", 0)))
                })
            elif isinstance(order, (list, tuple)) and len(order) >= 2:
                parsed.append({
                    "price": Decimal(str(order[0])),
                    "size": Decimal(str(order[1]))
                })
        return parsed
    
    def get_orderbook(self, token_id: str) -> Optional[dict]:
        """Get cached orderbook for a token."""
        return self._orderbooks.get(token_id)
    
    def stop(self):
        """Stop the feed gracefully."""
        self._running = False
        if self._ws:
            asyncio.create_task(self._ws.close())
    
    def get_stats(self) -> dict:
        """Return feed statistics."""
        return {
            "subscribed_tokens": len(self._subscribed_tokens),
            "cached_orderbooks": len(self._orderbooks),
            "messages_received": self.messages_received,
            "reconnect_count": self.reconnect_count,
            "connected": self._running and self._ws is not None
        }
