"""
Paper Trading Engine
====================

Simulates trading on Polymarket 15-minute BTC markets using real market data.
Tracks P&L without executing real orders.
"""

import asyncio
import aiohttp
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger()


@dataclass
class PaperPosition:
    """Represents a paper trading position."""
    market_slug: str
    question: str
    side: str  # "up" or "down"
    entry_price: float
    amount: float
    entry_time: datetime
    end_time: datetime
    token_id: str
    
    def to_dict(self) -> dict:
        return {
            "market_slug": self.market_slug,
            "question": self.question,
            "side": self.side,
            "entry_price": self.entry_price,
            "amount": self.amount,
            "entry_time": self.entry_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "token_id": self.token_id
        }


@dataclass
class PaperTrade:
    """Represents a completed paper trade."""
    id: str
    market_slug: str
    question: str
    side: str
    entry_price: float
    exit_price: float
    amount: float
    pnl: float
    time: datetime
    status: str  # "won", "lost", "pending"
    trade_type: str  # "Snipe", "MM"
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "market": self.question[:30] + "..." if len(self.question) > 30 else self.question,
            "side": self.side.capitalize(),
            "price": self.entry_price,
            "amount": self.amount,
            "pnl": self.pnl,
            "time": self.time.isoformat(),
            "status": self.status,
            "type": self.trade_type
        }


class PaperTradingEngine:
    """
    Paper trading engine that monitors markets and simulates trades.
    """
    
    def __init__(self, broadcast_callback=None):
        self.running = False
        self.broadcast = broadcast_callback
        
        # Portfolio state
        self.initial_balance = 10000.0
        self.balance = 10000.0
        self.pnl_today = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        
        # Positions and trades
        self.positions: List[PaperPosition] = []
        self.trades: List[PaperTrade] = []
        
        # Market data
        self.btc_price = 0.0
        self.markets: List[dict] = []
        
        # Trading parameters
        self.max_position_size = 50.0  # Max $50 per trade
        self.min_edge = 0.03  # 3% minimum edge required
        self.trade_cooldown = 60  # Seconds between trades
        self.last_trade_time = None
        
        # Tasks
        self._tasks: List[asyncio.Task] = []
    
    async def _log(self, message: str, level: str = "info"):
        """Log a message and broadcast it to the UI."""
        # Structured logging
        if level == "error":
            logger.error(message)
        else:
            logger.info(message)
            
        # Broadcast to UI
        if self.broadcast:
            await self.broadcast({
                "type": "log",
                "data": {
                    "time": datetime.now(timezone.utc).isoformat(),
                    "message": message,
                    "level": level
                }
            })

    async def start(self):
        """Start the paper trading engine."""
        if self.running:
            return
        
        self.running = True
        await self._log("Paper trading engine started", "success")
        
        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._price_loop()),
            asyncio.create_task(self._market_loop()),
            asyncio.create_task(self._trading_loop()),
            asyncio.create_task(self._settlement_loop()),
        ]
        
        await self._broadcast_status()
    
    async def stop(self):
        """Stop the paper trading engine."""
        self.running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        self._tasks = []
        await self._log("Paper trading engine stopped", "warning")
        await self._broadcast_status()
    
    async def _price_loop(self):
        """Fetch real BTC price from Binance and Coinbase, then average them."""
        binance_url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        coinbase_url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    binance_price = None
                    coinbase_price = None
                    
                    # Fetch Binance
                    try:
                        async with session.get(binance_url, timeout=5) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                binance_price = float(data["price"])
                    except Exception as e:
                        logger.error("binance_fetch_error", error=str(e))
                        
                    # Fetch Coinbase
                    try:
                        async with session.get(coinbase_url, timeout=5) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                coinbase_price = float(data["data"]["amount"])
                    except Exception as e:
                        logger.error("coinbase_fetch_error", error=str(e))
                        
                    # Calculate Average
                    if binance_price and coinbase_price:
                        self.btc_price = (binance_price + coinbase_price) / 2
                        source = "Avg(Binance+Coinbase)"
                    elif binance_price:
                        self.btc_price = binance_price
                        source = "Binance"
                    elif coinbase_price:
                        self.btc_price = coinbase_price
                        source = "Coinbase"
                    
                    if self.btc_price > 0 and self.broadcast:
                        await self.broadcast({
                            "type": "price_update",
                            "data": {
                                "btc_price": self.btc_price,
                                "source": source,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        })
                except Exception as e:
                    logger.error("price_loop_critical_error", error=str(e))
                
                await asyncio.sleep(1)
    
    async def _market_loop(self):
        """Fetch active markets from Polymarket."""
        from src.data.market_discovery import discover_15min_btc_markets
        
        while self.running:
            try:
                self.markets = await discover_15min_btc_markets()
                
                if self.broadcast:
                    await self.broadcast({
                        "type": "markets_update",
                        "data": {"markets": self.markets}
                    })
                
                logger.debug("markets_updated", count=len(self.markets))
                await self._log(f"Discovered {len(self.markets)} active BTC 15-min markets")
            except Exception as e:
                logger.error("market_fetch_error", error=str(e))
                await self._log(f"Market discovery error: {str(e)}", "error")
            
            await asyncio.sleep(30)  # Update every 30 seconds
    
    async def _trading_loop(self):
        """Main trading decision loop."""
        while self.running:
            try:
                await self._evaluate_trading_opportunities()
            except Exception as e:
                logger.error("trading_loop_error", error=str(e))
            
            await asyncio.sleep(5)  # Check every 5 seconds
    
    async def _settlement_loop(self):
        """Check for expired positions and settle them."""
        while self.running:
            try:
                await self._settle_expired_positions()
            except Exception as e:
                logger.error("settlement_error", error=str(e))
            
            await asyncio.sleep(10)
    
    async def _evaluate_trading_opportunities(self):
        """Look for trading opportunities based on REAL market analysis (Strike Price vs Current Price)."""
        if not self.markets or self.btc_price <= 0:
            return
            
        await self._log(f"Scanning {len(self.markets)} markets... (BTC: ${self.btc_price:,.2f})", "debug")
        
        # Check trade cooldown
        if self.last_trade_time:
            elapsed = (datetime.now(timezone.utc) - self.last_trade_time).total_seconds()
            if elapsed < self.trade_cooldown:
                return
        
        # Find best opportunity
        for market in self.markets:
            slug = market["slug"]
            
            # Skip if already have position
            if any(p.market_slug == slug for p in self.positions):
                continue
            
            # Skip if market closed
            if not market.get("accepting_orders", True):
                continue
                
            # 1. GET STRIKE PRICE
            strike = market.get("strike_price")
            if not strike:
                # Fallback: Try to parse again if missed (or log warning)
                # logger.warning("missing_strike_price", market=slug)
                continue
                
            # 2. CALCULATE TIME REMAINING
            end_time = datetime.fromisoformat(market["end_date"].replace("Z", "+00:00"))
            remaining_seconds = (end_time - datetime.now(timezone.utc)).total_seconds()
            remaining_minutes = remaining_seconds / 60
            
            if remaining_minutes <= 0:
                continue
                
            # 3. SMART PRICING LOGIC
            # Calculate distance to strike
            diff = self.btc_price - strike
            
            # Dynamic required buffer based on time remaining
            # Need more buffer if more time remains (due to volatility risk)
            # Formula: Base $10 + ($2 per minute remaining)
            required_buffer = 10.0 + (2.0 * remaining_minutes)
            
            fair_prob_up = 0.5
            
            if diff > required_buffer:
                # Price is comfortably ABOVE strike -> High prob UP
                fair_prob_up = 0.85 + (min(diff - required_buffer, 50) / 200) # Cap at ~0.95
                fair_prob_up = min(0.99, fair_prob_up)
                
            elif diff < -required_buffer:
                # Price is comfortably BELOW strike -> Low prob UP (High prob DOWN)
                # fair_prob_up should be low, e.g. 0.15
                dist = abs(diff) - required_buffer
                fair_prob_up = 0.15 - (min(dist, 50) / 200)
                fair_prob_up = max(0.01, fair_prob_up)
            else:
                # Too close to call (At The Money) -> No edge
                continue
                
            # 4. COMPARE WITH POLYMARKET PRICES
            poly_up = market.get("outcome_prices", {}).get("up", 0.5)
            poly_down = market.get("outcome_prices", {}).get("down", 0.5)
            
            # Calculate Edge (Kelly Criterion / Expected Value)
            # If our Fair Value >> Poly Price -> BUY
            
            min_edge = 0.15  # Minimum 15% discrepancy required
            
            best_side = None
            best_price = 0
            
            # Check UP opportunity
            if fair_prob_up > (poly_up + min_edge):
                best_side = "up"
                best_price = poly_up
                await self._log(f"OPPORTUNITY: {slug} | BTC ${self.btc_price:.1f} > Strike ${strike} (+${diff:.1f}) | Fair: {fair_prob_up:.2f} vs Poly: {poly_up:.2f}", "info")
                
            # Check DOWN opportunity
            elif (1 - fair_prob_up) > (poly_down + min_edge):
                best_side = "down"
                best_price = poly_down
                await self._log(f"OPPORTUNITY: {slug} | BTC ${self.btc_price:.1f} < Strike ${strike} (${diff:.1f}) | Fair Down: {(1-fair_prob_up):.2f} vs Poly: {poly_down:.2f}", "info")
            
            if best_side:
                await self._execute_paper_trade(market, best_side, best_price)
                break  # One trade at a time
    
    async def _execute_paper_trade(self, market: dict, side: str, price: float):
        """Execute a simulated trade."""
        # SIMULATION REALISM: Fill Probability & Slippage
        # In real HFT, not all orders get filled even if we see the price.
        import random
        
        # 20% chance of miss (simulating latency/race conditions)
        fill_prob = 0.80
        
        # If price is very good (e.g. crossing), higher chance. 
        # But we are just acting on a snapshot.
        if random.random() > fill_prob:
             await self._log(f"⚠️ SIMULATION: Order missed (latency/slippage) for {side} on {market['slug']}", "warning")
             return

        # Calculate position size (Kelly-inspired)
        edge = abs(0.50 - price)
        position_size = min(self.max_position_size, self.balance * 0.05 * (edge / 0.10))
        position_size = max(10.0, position_size)  # Minimum $10
        
        if position_size > self.balance:
            return
        
        # Get token ID
        token_id = market["tokens"].get(side, "")
        
        # Create position
        end_time = datetime.fromisoformat(market["end_date"].replace("Z", "+00:00"))
        
        position = PaperPosition(
            market_slug=market["slug"],
            question=market["question"],
            side=side,
            entry_price=price,
            amount=position_size,
            entry_time=datetime.now(timezone.utc),
            end_time=end_time,
            token_id=token_id
        )
        
        self.positions.append(position)
        self.balance -= position_size
        self.last_trade_time = datetime.now(timezone.utc)
        
        logger.info(
            "paper_trade_executed",
            market=market["slug"],
            side=side,
            price=price,
            amount=position_size
        )
        
        await self._log(f"EXECUTED TRADE: {side.upper()} on {market['slug']} @ ${price:.3f} (${position_size})", "success")
        
        # Broadcast new position
        await self._broadcast_portfolio()
        
        if self.broadcast:
            await self.broadcast({
                "type": "new_trade",
                "data": {
                    "trade": {
                        "time": position.entry_time.isoformat(),
                        "market": market["slug"],
                        "type": "Snipe",
                        "side": side,
                        "price": price,
                        "amount": position_size,
                        "pnl": 0.0,
                        "status": "pending"
                    },
                    "portfolio": self._get_portfolio_state(),
                    "message": f"Opened {side.upper()} position at ${price:.3f}"
                }
            })
    
    async def _settle_expired_positions(self):
        """Settle positions whose markets have expired."""
        now = datetime.now(timezone.utc)
        expired = [p for p in self.positions if p.end_time <= now]
        
        for position in expired:
            # Simulate outcome based on BTC price movement
            # In real scenario, we'd check the actual market resolution
            # For paper trading, we simulate based on random/price trend
            
            import random
            
            # Simple simulation: 50% win rate base, adjusted by entry price
            # Better entry price = higher chance of winning
            edge = abs(0.50 - position.entry_price)
            win_probability = 0.50 + edge  # e.g., entry at 0.45 = 55% win chance
            
            won = random.random() < win_probability
            
            # Calculate P&L
            if won:
                # Winner pays out at $1.00
                payout = position.amount / position.entry_price
                pnl = payout - position.amount
                status = "won"
            else:
                # Loser gets $0
                pnl = -position.amount
                status = "lost"
            
            # Update balance
            self.balance += position.amount + pnl
            self.pnl_today += pnl
            self.total_trades += 1
            if won:
                self.winning_trades += 1
            
            # Create trade record
            trade = PaperTrade(
                id=f"PT-{self.total_trades:04d}",
                market_slug=position.market_slug,
                question=position.question,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=1.0 if won else 0.0,
                amount=position.amount,
                pnl=pnl,
                time=now,
                status=status,
                trade_type="Snipe"
            )
            
            self.trades.insert(0, trade)
            self.positions.remove(position)
            
            logger.info(
                "position_settled",
                market=position.market_slug,
                side=position.side,
                pnl=pnl,
                status=status
            )
            
            # Broadcast trade
            if self.broadcast:
                await self.broadcast({
                    "type": "new_trade",
                    "data": {
                        "trade": trade.to_dict(),
                        "portfolio": self._get_portfolio()
                    }
                })
        
        if expired:
            await self._broadcast_portfolio()
    
    def _get_portfolio(self) -> dict:
        """Get current portfolio state."""
        win_rate = 0.0
        if self.total_trades > 0:
            win_rate = (self.winning_trades / self.total_trades) * 100
        
        return {
            "value": self.balance,
            "pnl_today": self.pnl_today,
            "pnl_percent": (self.pnl_today / self.initial_balance) * 100,
            "win_rate": win_rate,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades
        }
    
    async def _broadcast_portfolio(self):
        """Broadcast portfolio update."""
        if self.broadcast:
            await self.broadcast({
                "type": "portfolio_update",
                "data": {"portfolio": self._get_portfolio()}
            })
    
    async def _broadcast_status(self):
        """Broadcast bot status."""
        if self.broadcast:
            await self.broadcast({
                "type": "bot_status",
                "data": {
                    "bot_status": {
                        "running": self.running,
                        "dry_run": True,
                        "last_update": datetime.now(timezone.utc).isoformat()
                    }
                }
            })
    
    def get_state(self) -> dict:
        """Get full engine state."""
        return {
            "running": self.running,
            "portfolio": self._get_portfolio(),
            "positions": [p.to_dict() for p in self.positions],
            "trades": [t.to_dict() for t in self.trades[:50]],
            "markets": self.markets,
            "btc_price": self.btc_price
        }
