"""
Market Discovery
=================

Discovers active 15-minute BTC prediction markets on Polymarket.
"""

import asyncio
import aiohttp
import re
import socket
from datetime import datetime, timezone
from typing import List, Optional
import structlog

logger = structlog.get_logger()

# Exact slug pattern: btc-updown-15m-{timestamp}
# Exact slug pattern: btc-updown-15m-{timestamp}
BTC_15M_SLUG_PATTERN = re.compile(r'^btc-updown-15m-(\d+)$', re.IGNORECASE)

# Cache for historical prices to avoid rate limits
PRICE_CACHE = {}

async def get_btc_price_at_time(iso_time: str) -> Optional[float]:
    """
    Fetch BTC price at a specific time from Binance.
    Used to determine Strike Price for started markets.
    """
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        ts = int(dt.timestamp() * 1000)
        
        # Check cache
        if ts in PRICE_CACHE:
            return PRICE_CACHE[ts]
            
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "startTime": ts,
            "limit": 1
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and len(data) > 0:
                        # Open price of the minute
                        price = float(data[0][1])
                        PRICE_CACHE[ts] = price
                        return price
    except Exception as e:
        logger.error("historical_price_fetch_error", error=str(e))
    return None

async def discover_15min_btc_markets(
    gamma_api_base: str = "https://gamma-api.polymarket.com"
) -> List[dict]:
    # ... (rest of the function remains same until processing loop)
    logger.info("discovering_15min_markets", api=gamma_api_base)
    
    markets = []
    
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(family=socket.AF_INET)
    ) as session:
        try:
            # Query 15-minute markets using the 15M tag
            params = {
                "tag_slug": "15M",
                "closed": "false",
                "active": "true",
                "limit": 100
            }
            
            async with session.get(
                f"{gamma_api_base}/events",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.error("gamma_api_error", status=resp.status)
                    return []
                
                all_events = await resp.json()
            
            logger.debug("fetched_15m_events", count=len(all_events))
            
            for event in all_events:
                slug = event.get("slug", "")
                match = BTC_15M_SLUG_PATTERN.match(slug)
                
                # FALLBACK: Check tags and description if slug doesn't match
                # Fallback mechanism for market discovery handles slug changes.
                if not match:
                    tags = event.get("tags", [])
                    has_15m_tag = any(t.get("slug") == "15M" or t.get("label") == "15M" for t in tags)
                    
                    # Check first market description for BTC keywords
                    event_markets_check = event.get("markets", [])
                    if event_markets_check:
                        desc = event_markets_check[0].get("description", "").lower()
                        title = event_markets_check[0].get("question", "").lower()
                        is_btc = "bitcoin" in desc or "btc" in desc or "bitcoin" in title or "btc" in title
                        
                        if has_15m_tag and is_btc:
                            # Create a dummy match object or just set flag
                            match = True
                
                if match:
                    event_markets = event.get("markets", [])
                    if not event_markets:
                        continue
                    
                    m = event_markets[0]
                    
                    # Parse tokens and prices
                    tokens_str = m.get("clobTokenIds", "[]")
                    try:
                        import json
                        tokens = json.loads(tokens_str) if isinstance(tokens_str, str) else tokens_str
                    except: tokens = []
                    
                    outcome_prices_str = m.get("outcomePrices", "[]")
                    try:
                        outcome_prices = json.loads(outcome_prices_str) if isinstance(outcome_prices_str, str) else outcome_prices_str
                    except: outcome_prices = []
                    
                    description = m.get("description", "")
                    start_time = event.get("startDate", "") # Note: API uses startDate, not startTime usually
                    if not start_time: start_time = event.get("startTime", "")

                    # 1. Try regex from description (fallback)
                    strike_price = None
                    price_match = re.search(r'(?:higher than|above|price to beat).*?\$([\d,]+\.?\d*)', description, re.IGNORECASE)
                    if price_match:
                        try:
                            strike_price = float(price_match.group(1).replace(",", ""))
                        except: pass
                    
                    # 2. If no strike and market started, fetch from History
                    if not strike_price and start_time:
                        try:
                            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                            if start_dt <= datetime.now(timezone.utc):
                                # Market started, fetch historical Open Price
                                strike_price = await get_btc_price_at_time(start_time)
                        except: pass

                    market_info = {
                        "condition_id": m.get("conditionId", ""),
                        "question_id": m.get("questionID", ""),
                        "question": m.get("question", ""),
                        "description": description,
                        "strike_price": strike_price,
                        "slug": slug,
                        "end_date": m.get("endDate", ""),
                        "start_time": start_time,
                        "tokens": {
                            "up": tokens[0] if len(tokens) > 0 else None,
                            "down": tokens[1] if len(tokens) > 1 else None
                        },
                        "outcome_prices": {
                            "up": float(outcome_prices[0]) if len(outcome_prices) > 0 else 0.5,
                            "down": float(outcome_prices[1]) if len(outcome_prices) > 1 else 0.5
                        },
                        "volume": float(m.get("volume", 0) or 0),
                        "liquidity": float(m.get("liquidity", 0) or 0),
                        "best_bid": float(m.get("bestBid", 0) or 0),
                        "best_ask": float(m.get("bestAsk", 0) or 0),
                        "accepting_orders": m.get("acceptingOrders", False)
                    }
                    
                    if market_info["end_date"]:
                        try:
                            end_dt = datetime.fromisoformat(market_info["end_date"].replace("Z", "+00:00"))
                            if end_dt > datetime.now(timezone.utc):
                                markets.append(market_info)
                                logger.debug("found_btc_15m_market", slug=slug, strike=strike_price)
                        except: pass
            
            logger.info("discovered_markets", count=len(markets))
            
        except Exception as e:
            logger.error("market_discovery_error", error=str(e))
    
    markets.sort(key=lambda x: x.get("end_date", ""))
    return markets



async def get_market_details(
    condition_id: str,
    gamma_api_base: str = "https://gamma-api.polymarket.com"
) -> Optional[dict]:
    """
    Get detailed information about a specific market.
    
    Args:
        condition_id: The market's condition ID
        gamma_api_base: Gamma API base URL
    
    Returns:
        Market details dict or None
    """
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{gamma_api_base}/markets/{condition_id}",
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                    
        except Exception as e:
            logger.error(
                "get_market_details_error",
                condition_id=condition_id,
                error=str(e)
            )
    
    return None


def parse_strike_from_question(question: str) -> Optional[float]:
    """
    Extract strike price from market question.
    
    Examples:
        "Will BTC be above $95,000 at 12:00 UTC?" -> 95000.0
        "Bitcoin above 94500" -> 94500.0
    """
    import re
    
    # Try to find price patterns like $95,000 or 95000
    patterns = [
        r'\$?([\d,]+(?:\.\d+)?)',  # $95,000 or 95000.50
        r'above\s+([\d,]+)',       # above 95000
        r'>\s*([\d,]+)',           # > 95000
    ]
    
    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            price_str = match.group(1).replace(",", "")
            try:
                price = float(price_str)
                # Sanity check - BTC price should be reasonable
                if 10000 < price < 500000:
                    return price
            except ValueError:
                continue
    
    return None


def calculate_remaining_seconds(end_date_iso: str) -> int:
    """
    Calculate seconds remaining until market closes.
    
    Args:
        end_date_iso: ISO format end date string
    
    Returns:
        Seconds remaining (0 if already closed)
    """
    try:
        end_dt = datetime.fromisoformat(
            end_date_iso.replace("Z", "+00:00")
        )
        remaining = (end_dt - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))
    except (ValueError, TypeError):
        return 0
