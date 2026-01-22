"""
Order Manager
==============

Handles order placement, cancellation, and management through
the Polymarket CLOB API.
"""

from decimal import Decimal
from typing import Optional, List, Dict, Any
from datetime import datetime
import asyncio
import structlog

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    OrderArgs,
    MarketOrderArgs,
    OrderType,
    OpenOrderParams
)
from py_clob_client.order_builder.constants import BUY, SELL

logger = structlog.get_logger()


class OrderManager:
    """
    Manages order operations on Polymarket.
    
    Supports:
    - Limit orders (maker - no fees)
    - Market orders (taker - with fees)
    - Order cancellation
    - Position tracking
    
    Includes dry-run mode for paper trading.
    """
    
    def __init__(
        self,
        clob_client: ClobClient,
        risk_manager=None,
        dry_run: bool = True
    ):
        """
        Args:
            clob_client: Initialized py-clob-client ClobClient
            risk_manager: Optional RiskManager for trade validation
            dry_run: If True, don't actually place orders
        """
        self.client = clob_client
        self.risk_manager = risk_manager
        self.dry_run = dry_run
        
        # Order tracking
        self.active_orders: Dict[str, dict] = {}
        self.order_history: List[dict] = []
        
        # Stats
        self.orders_placed = 0
        self.orders_canceled = 0
        self.orders_filled = 0
        
        # Rate limiting
        self._last_order_time: Optional[datetime] = None
        self._order_count_this_second = 0
        self._max_orders_per_second = 50
    
    async def _rate_limit_check(self):
        """Ensure we don't exceed rate limits."""
        now = datetime.now()
        
        if self._last_order_time:
            elapsed = (now - self._last_order_time).total_seconds()
            
            if elapsed < 1.0:
                self._order_count_this_second += 1
                
                if self._order_count_this_second >= self._max_orders_per_second:
                    wait_time = 1.0 - elapsed
                    logger.debug(
                        "rate_limit_wait",
                        wait_seconds=f"{wait_time:.3f}"
                    )
                    await asyncio.sleep(wait_time)
                    self._order_count_this_second = 0
            else:
                self._order_count_this_second = 1
        else:
            self._order_count_this_second = 1
        
        self._last_order_time = now
    
    async def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float
    ) -> dict:
        """
        Place a limit order (maker - no fees).
        
        Args:
            token_id: Token to trade
            side: "BUY" or "SELL"
            price: Limit price (0.01 - 0.99)
            size: Number of shares
        
        Returns:
            Result dict with order_id if successful
        """
        await self._rate_limit_check()
        
        # Risk validation
        if self.risk_manager:
            valid, reason = self.risk_manager.validate_trade(
                price, size, 0.0, side  # No fee for maker
            )
            if not valid:
                logger.warning(
                    "order_rejected_risk",
                    reason=reason,
                    token_id=token_id[:16] + "...",
                    side=side,
                    price=price,
                    size=size
                )
                return {"success": False, "error": reason}
        
        if self.dry_run:
            # Paper trade - simulate order
            order_id = f"DRY_{datetime.now().timestamp()}"
            
            logger.info(
                "dry_run_limit_order",
                order_id=order_id,
                token_id=token_id[:16] + "...",
                side=side,
                price=price,
                size=size
            )
            
            self.orders_placed += 1
            self.active_orders[order_id] = {
                "order_id": order_id,
                "token_id": token_id,
                "side": side,
                "price": price,
                "size": size,
                "type": "limit",
                "status": "open",
                "timestamp": datetime.now().isoformat()
            }
            
            return {"success": True, "order_id": order_id}
        
        try:
            # Real order
            order_side = BUY if side.upper() == "BUY" else SELL
            
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side
            )
            
            signed_order = self.client.create_order(order_args)
            response = self.client.post_order(signed_order, OrderType.GTC)
            
            if response and response.get("orderID"):
                order_id = response["orderID"]
                self.orders_placed += 1
                
                self.active_orders[order_id] = {
                    "order_id": order_id,
                    "token_id": token_id,
                    "side": side,
                    "price": price,
                    "size": size,
                    "type": "limit",
                    "status": "open",
                    "timestamp": datetime.now().isoformat()
                }
                
                if self.risk_manager:
                    self.risk_manager.record_trade_opened(price * size)
                
                logger.info(
                    "limit_order_placed",
                    order_id=order_id,
                    side=side,
                    price=price,
                    size=size
                )
                
                return {"success": True, "order_id": order_id}
            else:
                logger.error("limit_order_failed", response=response)
                return {"success": False, "error": str(response)}
                
        except Exception as e:
            logger.error("limit_order_exception", error=str(e))
            return {"success": False, "error": str(e)}
    
    async def place_market_order(
        self,
        token_id: str,
        side: str,
        amount: float
    ) -> dict:
        """
        Place a market order (taker - with fees).
        
        Args:
            token_id: Token to trade
            side: "BUY" or "SELL"
            amount: Dollar amount to trade
        
        Returns:
            Result dict with order details if successful
        """
        await self._rate_limit_check()
        
        # Estimate price for risk check (assume mid-market)
        estimated_price = 0.50
        estimated_shares = amount / estimated_price
        estimated_fee = 0.015  # Conservative estimate
        
        # Risk validation
        if self.risk_manager:
            valid, reason = self.risk_manager.validate_trade(
                estimated_price, estimated_shares, estimated_fee, side
            )
            if not valid:
                logger.warning(
                    "market_order_rejected_risk",
                    reason=reason,
                    amount=amount
                )
                return {"success": False, "error": reason}
        
        if self.dry_run:
            order_id = f"DRY_MKT_{datetime.now().timestamp()}"
            
            logger.info(
                "dry_run_market_order",
                order_id=order_id,
                token_id=token_id[:16] + "...",
                side=side,
                amount=amount
            )
            
            self.orders_placed += 1
            self.orders_filled += 1
            
            return {
                "success": True,
                "order_id": order_id,
                "filled_amount": amount,
                "filled_price": estimated_price
            }
        
        try:
            order_side = BUY if side.upper() == "BUY" else SELL
            
            market_args = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                side=order_side,
                order_type=OrderType.FOK  # Fill-or-Kill
            )
            
            signed_order = self.client.create_market_order(market_args)
            response = self.client.post_order(signed_order, OrderType.FOK)
            
            if response and response.get("success"):
                self.orders_placed += 1
                self.orders_filled += 1
                
                if self.risk_manager:
                    self.risk_manager.record_trade_opened(amount)
                
                logger.info(
                    "market_order_filled",
                    side=side,
                    amount=amount,
                    response=response
                )
                
                return {
                    "success": True,
                    "order_id": response.get("orderID", ""),
                    "response": response
                }
            else:
                logger.error("market_order_failed", response=response)
                return {"success": False, "error": str(response)}
                
        except Exception as e:
            logger.error("market_order_exception", error=str(e))
            return {"success": False, "error": str(e)}
    
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a specific order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            True if canceled successfully
        """
        await self._rate_limit_check()
        
        if self.dry_run:
            if order_id in self.active_orders:
                del self.active_orders[order_id]
                self.orders_canceled += 1
                
                logger.info("dry_run_order_canceled", order_id=order_id)
                return True
            return False
        
        try:
            response = self.client.cancel(order_id)
            
            if response:
                if order_id in self.active_orders:
                    del self.active_orders[order_id]
                self.orders_canceled += 1
                
                logger.info("order_canceled", order_id=order_id)
                return True
            return False
            
        except Exception as e:
            logger.error(
                "cancel_order_error",
                order_id=order_id,
                error=str(e)
            )
            return False
    
    async def cancel_all_orders(self) -> int:
        """
        Cancel all active orders.
        
        Returns:
            Number of orders canceled
        """
        if self.dry_run:
            count = len(self.active_orders)
            self.active_orders.clear()
            self.orders_canceled += count
            
            logger.info("dry_run_all_orders_canceled", count=count)
            return count
        
        try:
            response = self.client.cancel_all()
            
            count = len(self.active_orders)
            self.active_orders.clear()
            self.orders_canceled += count
            
            logger.info("all_orders_canceled", count=count)
            return count
            
        except Exception as e:
            logger.error("cancel_all_error", error=str(e))
            return 0
    
    async def get_open_orders(self) -> List[dict]:
        """Get all open orders from the exchange."""
        if self.dry_run:
            return list(self.active_orders.values())
        
        try:
            orders = self.client.get_orders(OpenOrderParams())
            return orders if orders else []
        except Exception as e:
            logger.error("get_orders_error", error=str(e))
            return []
    
    def get_stats(self) -> dict:
        """Return order manager statistics."""
        return {
            "dry_run": self.dry_run,
            "active_orders": len(self.active_orders),
            "orders_placed": self.orders_placed,
            "orders_canceled": self.orders_canceled,
            "orders_filled": self.orders_filled,
            "fill_rate": (
                f"{self.orders_filled / max(1, self.orders_placed):.1%}"
            )
        }
