"""
Binance WebSocket Price Feed
=============================

Real-time BTC price from Binance Futures.
This is the FASTEST source - always ahead of Polymarket oracle.
"""

import asyncio
import json
from decimal import Decimal
from typing import Callable, Optional, Awaitable
from datetime import datetime
import websockets
import structlog

logger = structlog.get_logger()


class BinancePriceFeed:
    """
    Streams real-time BTC/USDT price from Binance Futures.
    
    Uses aggTrade stream for lowest latency.
    This price is our "oracle" to compare against Polymarket.
    """
    
    def __init__(
        self,
        on_price_update: Callable[[Decimal, int], Awaitable[None]],
        symbol: str = "btcusdt",
        wss_url: str = "wss://fstream.binance.com/ws"
    ):
        """
        Args:
            on_price_update: Async callback(price, timestamp_ms) on each tick
            symbol: Trading pair (lowercase)
            wss_url: Binance Futures WebSocket URL
        """
        self.on_price_update = on_price_update
        self.symbol = symbol.lower()
        self.wss_url = wss_url
        
        # State
        self.current_price: Decimal = Decimal("0")
        self.last_update_ms: int = 0
        self._running = False
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        
        # Stats
        self.messages_received = 0
        self.reconnect_count = 0
    
    @property
    def stream_url(self) -> str:
        """Full WebSocket stream URL."""
        return f"{self.wss_url}/{self.symbol}@aggTrade"
    
    async def connect(self):
        """
        Connect to Binance and stream price updates.
        Automatically reconnects on disconnect.
        """
        self._running = True
        
        logger.info("binance_feed_starting", symbol=self.symbol, url=self.stream_url)
        
        while self._running:
            try:
                async with websockets.connect(
                    self.stream_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5
                ) as ws:
                    self._ws = ws
                    logger.info("binance_feed_connected")
                    
                    async for message in ws:
                        if not self._running:
                            break
                        
                        await self._handle_message(message)
                        
            except websockets.ConnectionClosed as e:
                if self._running:
                    self.reconnect_count += 1
                    logger.warning(
                        "binance_feed_disconnected",
                        reason=str(e),
                        reconnect_count=self.reconnect_count
                    )
                    await asyncio.sleep(1)
                    continue
                break
            except Exception as e:
                if self._running:
                    logger.error("binance_feed_error", error=str(e))
                    await asyncio.sleep(2)
                    continue
                break
        
        logger.info("binance_feed_stopped")
    
    async def _handle_message(self, message: str):
        """Process incoming aggTrade message."""
        try:
            data = json.loads(message)
            
            # aggTrade format: {"e":"aggTrade","p":"95000.50","T":1737500000000,...}
            price = Decimal(data["p"])
            timestamp_ms = data["T"]
            
            self.current_price = price
            self.last_update_ms = timestamp_ms
            self.messages_received += 1
            
            # Callback to strategy
            await self.on_price_update(price, timestamp_ms)
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("binance_message_parse_error", error=str(e))
    
    def stop(self):
        """Stop the feed gracefully."""
        self._running = False
        if self._ws:
            asyncio.create_task(self._ws.close())
    
    def get_stats(self) -> dict:
        """Return feed statistics."""
        return {
            "current_price": str(self.current_price),
            "last_update_ms": self.last_update_ms,
            "messages_received": self.messages_received,
            "reconnect_count": self.reconnect_count,
            "connected": self._running and self._ws is not None
        }
