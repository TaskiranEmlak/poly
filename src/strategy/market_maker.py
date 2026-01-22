"""
Market Maker Engine
====================

Provides liquidity and earns spread + maker rebates.
This is the passive income component of the hybrid strategy.
"""

from decimal import Decimal
from dataclasses import dataclass
from typing import Optional, List, Tuple
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class Quote:
    """Represents a quote to be placed."""
    token_id: str
    side: str  # "BUY" or "SELL"
    price: Decimal
    size: Decimal


class MarketMakerEngine:
    """
    Passive market making strategy.
    
    Places limit orders around fair value to:
    1. Earn the bid-ask spread
    2. Collect maker rebates from Polymarket
    
    Key features:
    - Inventory management to avoid directional exposure
    - Dynamic quote sizing based on imbalance
    - Anti-crossing logic (never take liquidity)
    """
    
    def __init__(
        self,
        fair_value_calc,
        spread_bps: int = 50,          # 0.5% spread
        quote_size: Decimal = Decimal("50"),
        max_inventory_imbalance: float = 0.3,
        refresh_interval_ms: int = 1000
    ):
        """
        Args:
            fair_value_calc: FairValueCalculator instance
            spread_bps: Quote spread in basis points
            quote_size: Default quote size in shares
            max_inventory_imbalance: Max acceptable inventory skew
            refresh_interval_ms: How often to update quotes
        """
        self.fair_calc = fair_value_calc
        self.spread_bps = spread_bps
        self.base_quote_size = quote_size
        self.max_imbalance = max_inventory_imbalance
        self.refresh_ms = refresh_interval_ms
        
        # Inventory tracking
        self.yes_position: Decimal = Decimal("0")
        self.no_position: Decimal = Decimal("0")
        
        # Active orders tracking
        self.active_orders: List[str] = []
        
        # Stats
        self.quotes_placed = 0
        self.fills_received = 0
        self.rebates_earned = Decimal("0")
    
    def calculate_quotes(
        self,
        fair_price: float,
        orderbook: dict,
        token_id: str
    ) -> Tuple[Optional[Quote], Optional[Quote]]:
        """
        Calculate bid and ask quotes around fair value.
        
        Adjusts sizes based on inventory to maintain balance.
        
        Args:
            fair_price: Fair probability (0.0 - 1.0)
            orderbook: Current order book
            token_id: Token to quote
        
        Returns:
            (bid_quote, ask_quote) - either can be None if skipped
        """
        half_spread = self.spread_bps / 10000 / 2
        
        # Quote prices
        bid_price = Decimal(str(max(0.01, fair_price - half_spread)))
        ask_price = Decimal(str(min(0.99, fair_price + half_spread)))
        
        # Calculate inventory imbalance
        total_inventory = self.yes_position + self.no_position
        if total_inventory > 0:
            imbalance = float(
                (self.yes_position - self.no_position) / total_inventory
            )
        else:
            imbalance = 0.0
        
        # Adjust sizes based on imbalance
        bid_size = self.base_quote_size
        ask_size = self.base_quote_size
        
        if abs(imbalance) > self.max_imbalance:
            if imbalance > 0:
                # Too much YES - reduce bid (buy less), increase ask (sell more)
                bid_size = self.base_quote_size * Decimal("0.5")
                ask_size = self.base_quote_size * Decimal("1.5")
            else:
                # Too much NO - increase bid (buy more), reduce ask
                bid_size = self.base_quote_size * Decimal("1.5")
                ask_size = self.base_quote_size * Decimal("0.5")
        
        # Anti-crossing check
        best_bid, best_ask = self._get_best_prices(orderbook)
        
        # Don't bid above best ask (would cross)
        if best_ask and bid_price >= best_ask:
            bid_price = best_ask - Decimal("0.01")
        
        # Don't ask below best bid (would cross)
        if best_bid and ask_price <= best_bid:
            ask_price = best_bid + Decimal("0.01")
        
        # Validate prices
        if bid_price <= Decimal("0") or bid_price >= Decimal("1"):
            bid_quote = None
        else:
            bid_quote = Quote(
                token_id=token_id,
                side="BUY",
                price=bid_price,
                size=bid_size
            )
        
        if ask_price <= Decimal("0") or ask_price >= Decimal("1"):
            ask_quote = None
        else:
            ask_quote = Quote(
                token_id=token_id,
                side="SELL",
                price=ask_price,
                size=ask_size
            )
        
        return (bid_quote, ask_quote)
    
    def _get_best_prices(
        self,
        orderbook: dict
    ) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """Extract best bid and ask from orderbook."""
        best_bid = None
        best_ask = None
        
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        
        if bids:
            best_bid = Decimal(str(
                max(float(b.get("price", 0)) for b in bids)
            ))
        
        if asks:
            best_ask = Decimal(str(
                min(float(a.get("price", 999)) for a in asks)
            ))
        
        return (best_bid, best_ask)
    
    def generate_quote_update(
        self,
        binance_price: Decimal,
        strike_price: Decimal,
        remaining_seconds: int,
        orderbook: dict,
        token_id: str
    ) -> Tuple[List[str], List[Quote]]:
        """
        Generate a complete quote update.
        
        Returns:
            (orders_to_cancel, orders_to_place)
        """
        # Calculate fair value
        fair_prob = self.fair_calc.calculate_fair_probability(
            binance_price, strike_price, remaining_seconds
        )
        
        # Don't quote if market is about to close
        if remaining_seconds < 60:
            return (self.active_orders.copy(), [])
        
        # Calculate new quotes
        bid_quote, ask_quote = self.calculate_quotes(
            fair_prob, orderbook, token_id
        )
        
        # Build cancel list (all current orders)
        orders_to_cancel = self.active_orders.copy()
        
        # Build new orders
        new_orders = []
        if bid_quote:
            new_orders.append(bid_quote)
        if ask_quote:
            new_orders.append(ask_quote)
        
        return (orders_to_cancel, new_orders)
    
    def record_order_placed(self, order_id: str):
        """Record that an order was placed."""
        self.active_orders.append(order_id)
        self.quotes_placed += 1
    
    def record_order_canceled(self, order_id: str):
        """Record that an order was canceled."""
        if order_id in self.active_orders:
            self.active_orders.remove(order_id)
    
    def record_fill(
        self,
        side: str,
        size: Decimal,
        rebate: Decimal = Decimal("0")
    ):
        """
        Record a fill and update inventory.
        
        Args:
            side: "BUY" or "SELL"
            size: Number of shares filled
            rebate: Rebate earned (if any)
        """
        self.fills_received += 1
        self.rebates_earned += rebate
        
        if side == "BUY":
            self.yes_position += size
        elif side == "SELL":
            self.yes_position -= size
        
        logger.info(
            "mm_fill_recorded",
            side=side,
            size=str(size),
            yes_position=str(self.yes_position),
            no_position=str(self.no_position)
        )
    
    def get_inventory_value(self, current_price: float) -> float:
        """Calculate current inventory value."""
        yes_value = float(self.yes_position) * current_price
        no_value = float(self.no_position) * (1 - current_price)
        return yes_value + no_value
    
    def get_stats(self) -> dict:
        """Return market making statistics."""
        return {
            "yes_position": str(self.yes_position),
            "no_position": str(self.no_position),
            "active_orders": len(self.active_orders),
            "quotes_placed": self.quotes_placed,
            "fills_received": self.fills_received,
            "rebates_earned": f"${self.rebates_earned:.4f}",
            "spread_bps": self.spread_bps
        }
