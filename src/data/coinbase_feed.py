"""
Coinbase Price Feed
====================

Real-time BTC price from Coinbase for dual-source pricing.
Polymarket uses average of Binance + Coinbase.
"""

import aiohttp
import asyncio
from decimal import Decimal
from typing import Optional
import structlog

logger = structlog.get_logger()


class CoinbasePriceFeed:
    """
    Fetches BTC price from Coinbase REST API.
    
    Polymarket uses the average of Binance and Coinbase prices
    for 15-minute market settlement.
    """
    
    COINBASE_URL = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    
    def __init__(self):
        self.last_price: Decimal = Decimal("0")
        self.last_update_ms: int = 0
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_price(self) -> Decimal:
        """Fetch current BTC price from Coinbase."""
        try:
            if not self._session:
                self._session = aiohttp.ClientSession()
            
            async with self._session.get(self.COINBASE_URL, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    price = Decimal(data["data"]["amount"])
                    self.last_price = price
                    self.last_update_ms = int(asyncio.get_event_loop().time() * 1000)
                    return price
                else:
                    logger.warning("coinbase_api_error", status=response.status)
                    return self.last_price
                    
        except Exception as e:
            logger.error("coinbase_fetch_error", error=str(e))
            return self.last_price
    
    async def close(self):
        """Close the HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None


async def get_dual_source_price() -> tuple[Decimal, Decimal, Decimal]:
    """
    Get BTC price from both Binance and Coinbase.
    Returns: (binance_price, coinbase_price, average_price)
    """
    import aiohttp
    
    binance_url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
    coinbase_url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
    
    async with aiohttp.ClientSession() as session:
        try:
            # Fetch both in parallel
            binance_task = session.get(binance_url, timeout=5)
            coinbase_task = session.get(coinbase_url, timeout=5)
            
            binance_resp, coinbase_resp = await asyncio.gather(
                binance_task, coinbase_task,
                return_exceptions=True
            )
            
            # Parse Binance
            binance_price = Decimal("0")
            if not isinstance(binance_resp, Exception) and binance_resp.status == 200:
                data = await binance_resp.json()
                binance_price = Decimal(data["price"])
            
            # Parse Coinbase
            coinbase_price = Decimal("0")
            if not isinstance(coinbase_resp, Exception) and coinbase_resp.status == 200:
                data = await coinbase_resp.json()
                coinbase_price = Decimal(data["data"]["amount"])
            
            # Calculate average
            if binance_price > 0 and coinbase_price > 0:
                average = (binance_price + coinbase_price) / 2
            elif binance_price > 0:
                average = binance_price
            elif coinbase_price > 0:
                average = coinbase_price
            else:
                average = Decimal("0")
            
            return (binance_price, coinbase_price, average)
            
        except Exception as e:
            logger.error("dual_source_error", error=str(e))
            return (Decimal("0"), Decimal("0"), Decimal("0"))
