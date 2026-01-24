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
                    
                    outcomes = m.get("outcomes", [])
                    try:
                        import json
                        if isinstance(outcomes, str):
                            outcomes = json.loads(outcomes)
                    except: outcomes = []
                    
                    if not outcomes:
                        # Fallback for old markets or unknown structure
                        outcomes = ["Yes", "No"] 

                    # Dynamically map indexes
                    up_idx = -1
                    down_idx = -1
                    
                    for i, label in enumerate(outcomes):
                        l = label.lower()
                        if l in ["yes", "up", "long"]:
                            up_idx = i
                        elif l in ["no", "down", "short"]:
                            down_idx = i
                    
                    # If extraction failed, assume standard 0=Yes/Up, 1=No/Down
                    if up_idx == -1: up_idx = 0
                    if down_idx == -1: down_idx = 1

                    # Parse tokens and prices
                    tokens_str = m.get("clobTokenIds", "[]")
                    try:
                        import json
                        tokens_arr = json.loads(tokens_str) if isinstance(tokens_str, str) else tokens_str
                    except: tokens_arr = []
                    
                    outcome_prices_str = m.get("outcomePrices", "[]")
                    try:
                        prices_arr = json.loads(outcome_prices_str) if isinstance(outcome_prices_str, str) else outcome_prices_str
                    except: prices_arr = []
                    
                    # Safe helpers
                    def get_safe(arr, idx, default):
                        return arr[idx] if len(arr) > idx else default

                    description = m.get("description", "")
                    start_time = event.get("startDate", "") # Note: API uses startDate, not startTime usually
                    if not start_time: start_time = event.get("startTime", "")

                    # 1. Try regex from description (fallback)
                    strike_price = None
                    # Expanded regex to capture "strike price", "target price", "above", "higher than"
                    price_match = re.search(r'(?:higher than|above|price to beat|strike price|target).*?\$([\d,]+\.?\d*)', description, re.IGNORECASE)
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
                    
                    # SAFETY: If Outcome Prices are missing, DO NOT assume 0.5 (50%)
                    # Defaulting to 0.5 caused "False Opportunities"
                    up_p = get_safe(prices_arr, up_idx, None)
                    down_p = get_safe(prices_arr, down_idx, None)
                    
                    if up_p is None or down_p is None:
                        logger.warning("market_skipped_no_prices", slug=slug)
                        continue # Skip this market
                    
                    outcome_prices_dict = {
                        "up": float(up_p),
                        "down": float(down_p)
                    }

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
                            "up": get_safe(tokens_arr, up_idx, None),
                            "down": get_safe(tokens_arr, down_idx, None)
                        },
                        "outcome_prices": outcome_prices_dict,
                        "volume": float(m.get("volume", 0) or 0),
                        "liquidity": float(m.get("liquidity", 0) or 0),
                        "best_bid": float(m.get("bestBid", 0) or 0),
                        "best_ask": float(m.get("bestAsk", 0) or 0),
                        "accepting_orders": m.get("acceptingOrders", False)
                    }
                    
                    if market_info["end_date"]:
                        try:
                            end_dt = datetime.fromisoformat(market_info["end_date"].replace("Z", "+00:00"))
                            now = datetime.now(timezone.utc)
                            
                            # Validated against slug timestamp if available
                            is_valid_time = True
                            if match and isinstance(match, re.Match):
                                try:
                                    slug_ts = int(match.group(1))
                                    # If slug timestamp implies the market ended more than 15 mins ago, skip it
                                    # 15m markets usually end at slug_ts or slug_ts + 15m
                                    # Give it a small buffer, but definitely shouldn't be hours old
                                    if slug_ts < (now.timestamp() - 3600): # older than 1 hour
                                        is_valid_time = False
                                        logger.warning("stale_market_slug_detected", slug=slug, slug_ts=slug_ts, now=now.timestamp())
                                except: pass

                            if end_dt > now and is_valid_time:
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
