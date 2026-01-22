"""
Oracle Latency Arbitrage Engine
================================

Exploits the delay between Binance price movements
and Polymarket order book updates.

This is the "sniper" component of the hybrid strategy.
"""

import asyncio
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class SniperOpportunity:
    """Represents a detected arbitrage opportunity."""
    token_id: str
    side: str  # "YES" or "NO"
    stale_price: Decimal
    fair_price: float
    expected_profit: float
    market_question: str
    timestamp: datetime


class OracleLatencyEngine:
    """
    Snipes stale orders using oracle price advantage.
    
    Strategy:
    1. Monitor Binance for sudden BTC price moves
    2. Calculate new fair value immediately
    3. Check if Polymarket orderbook has "stale" orders
    4. If profit > fees + minimum edge, execute snipe
    
    The key insight: Polymarket market makers react slower than
    our direct Binance feed, creating brief arbitrage windows.
    """
    
    def __init__(
        self,
        fair_value_calc,
        fee_calc,
        min_edge_after_fees: float = 0.02,  # 2% minimum edge
        max_position_usd: float = 100.0,
        cooldown_seconds: float = 5.0
    ):
        """
        Args:
            fair_value_calc: FairValueCalculator instance
            fee_calc: DynamicFeeCalculator instance
            min_edge_after_fees: Minimum profit margin to execute
            max_position_usd: Maximum position size per snipe
            cooldown_seconds: Minimum time between snipes
        """
        self.fair_calc = fair_value_calc
        self.fee_calc = fee_calc
        self.min_edge = min_edge_after_fees
        self.max_position = max_position_usd
        self.cooldown = cooldown_seconds
        
        # State
        self.last_snipe_time: Optional[datetime] = None
        
        # Stats
        self.opportunities_found = 0
        self.opportunities_taken = 0
        self.total_profit = 0.0
    
    def evaluate_opportunity(
        self,
        binance_price: Decimal,
        strike_price: Decimal,
        remaining_seconds: int,
        orderbook: dict,
        market_question: str = ""
    ) -> Optional[SniperOpportunity]:
        """
        Evaluate current market for snipe opportunities.
        
        Args:
            binance_price: Current BTC price from Binance
            strike_price: Market's strike price
            remaining_seconds: Time until market closes
            orderbook: {"bids": [...], "asks": [...], "token_id": ...}
            market_question: Market question for logging
        
        Returns:
            SniperOpportunity if profitable, None otherwise
        """
        # Cooldown check
        if self.last_snipe_time:
            elapsed = (datetime.now() - self.last_snipe_time).total_seconds()
            if elapsed < self.cooldown:
                return None
        
        # Don't trade if market is about to close (< 30 seconds)
        if remaining_seconds < 30:
            return None
        
        # Calculate fair value
        fair_prob = self.fair_calc.calculate_fair_probability(
            binance_price, strike_price, remaining_seconds
        )
        
        token_id = orderbook.get("token_id", "")
        
        # Check YES side (buy the ask)
        yes_opp = self._check_yes_opportunity(
            fair_prob, orderbook, token_id, market_question
        )
        if yes_opp:
            return yes_opp
        
        # Check NO side (need to look at NO token's book or infer from YES bids)
        no_opp = self._check_no_opportunity(
            fair_prob, orderbook, token_id, market_question
        )
        if no_opp:
            return no_opp
        
        return None
    
    def _check_yes_opportunity(
        self,
        fair_prob: float,
        orderbook: dict,
        token_id: str,
        market_question: str
    ) -> Optional[SniperOpportunity]:
        """Check if buying YES is profitable."""
        asks = orderbook.get("asks", [])
        if not asks:
            return None
        
        # Get best ask (lowest price to buy YES)
        best_ask = min(asks, key=lambda x: float(x.get("price", 999)))
        ask_price = Decimal(str(best_ask.get("price", 0)))
        
        if ask_price <= 0 or ask_price >= 1:
            return None
        
        # Calculate fee at this price
        fee_rate = self.fee_calc.calculate_taker_fee(ask_price)
        
        # Calculate edge
        effective_cost = float(ask_price) * (1 + fee_rate)
        expected_payout = fair_prob * 1.0
        edge = expected_payout - effective_cost
        
        if edge >= self.min_edge:
            self.opportunities_found += 1
            
            logger.info(
                "snipe_opportunity_found",
                side="YES",
                fair_prob=f"{fair_prob:.4f}",
                market_price=str(ask_price),
                edge=f"{edge:.4f}",
                fee_rate=f"{fee_rate:.4f}"
            )
            
            return SniperOpportunity(
                token_id=token_id,
                side="YES",
                stale_price=ask_price,
                fair_price=fair_prob,
                expected_profit=edge,
                market_question=market_question,
                timestamp=datetime.now()
            )
        
        return None
    
    def _check_no_opportunity(
        self,
        fair_prob: float,
        orderbook: dict,
        token_id: str,
        market_question: str
    ) -> Optional[SniperOpportunity]:
        """Check if buying NO is profitable."""
        # For NO, we look at implied NO price from YES bids
        # If best YES bid is 0.60, then NO can be bought at ~0.40
        bids = orderbook.get("bids", [])
        if not bids:
            return None
        
        # Get best bid for YES
        best_bid = max(bids, key=lambda x: float(x.get("price", 0)))
        yes_bid_price = float(best_bid.get("price", 0))
        
        if yes_bid_price <= 0 or yes_bid_price >= 1:
            return None
        
        # Implied NO price (this is approximate)
        no_price = Decimal(str(1.0 - yes_bid_price))
        
        # Calculate fee at NO price
        fee_rate = self.fee_calc.calculate_taker_fee(no_price)
        
        # NO fair probability
        no_fair_prob = 1 - fair_prob
        
        # Calculate edge
        effective_cost = float(no_price) * (1 + fee_rate)
        expected_payout = no_fair_prob * 1.0
        edge = expected_payout - effective_cost
        
        if edge >= self.min_edge:
            self.opportunities_found += 1
            
            logger.info(
                "snipe_opportunity_found",
                side="NO",
                fair_prob=f"{no_fair_prob:.4f}",
                implied_price=str(no_price),
                edge=f"{edge:.4f}",
                fee_rate=f"{fee_rate:.4f}"
            )
            
            return SniperOpportunity(
                token_id=token_id,  # Note: This would need NO token ID
                side="NO",
                stale_price=no_price,
                fair_price=no_fair_prob,
                expected_profit=edge,
                market_question=market_question,
                timestamp=datetime.now()
            )
        
        return None
    
    def calculate_position_size(
        self,
        opportunity: SniperOpportunity
    ) -> float:
        """
        Calculate optimal position size for a snipe.
        
        Uses Kelly criterion with safety factor.
        """
        price = float(opportunity.stale_price)
        
        # Maximum shares we can buy
        max_shares = self.max_position / price
        
        # Kelly fraction (simplified)
        # f* = (bp - q) / b where b = odds, p = win prob, q = lose prob
        edge = opportunity.expected_profit
        win_prob = opportunity.fair_price
        
        # Very conservative: use 25% Kelly
        kelly_fraction = 0.25 * edge / price if price > 0 else 0
        kelly_shares = kelly_fraction * self.max_position / price
        
        # Take minimum of max and Kelly
        shares = min(max_shares, kelly_shares)
        
        # Round to reasonable amount
        return max(1.0, min(shares, 100.0))
    
    def record_execution(self, success: bool, profit: float = 0.0):
        """Record execution result."""
        if success:
            self.opportunities_taken += 1
            self.total_profit += profit
            self.last_snipe_time = datetime.now()
    
    def get_stats(self) -> dict:
        """Return strategy statistics."""
        hit_rate = (
            self.opportunities_taken / max(1, self.opportunities_found)
        )
        
        return {
            "opportunities_found": self.opportunities_found,
            "opportunities_taken": self.opportunities_taken,
            "hit_rate": f"{hit_rate:.2%}",
            "total_profit": f"${self.total_profit:.2f}",
            "min_edge_required": f"{self.min_edge:.2%}",
            "cooldown_seconds": self.cooldown
        }
