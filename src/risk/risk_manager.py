"""
Risk Manager
=============

Enforces risk limits and validates all trades before execution.
"""

from decimal import Decimal
from typing import Tuple
from datetime import datetime, date
import structlog

logger = structlog.get_logger()


class RiskManager:
    """
    Enforces risk controls and validates trades.
    
    Controls:
    - Maximum position size per trade
    - Daily loss limit
    - Maximum concurrent positions
    - Price sanity checks
    
    All trades must pass validation before execution!
    """
    
    def __init__(
        self,
        max_daily_loss_usd: float = 500.0,
        max_position_usd: float = 100.0,
        max_open_positions: int = 5,
        max_single_trade_usd: float = 100.0
    ):
        """
        Args:
            max_daily_loss_usd: Stop all trading if daily loss exceeds
            max_position_usd: Maximum position size
            max_open_positions: Maximum concurrent open positions
            max_single_trade_usd: Maximum single trade size
        """
        self.max_daily_loss = max_daily_loss_usd
        self.max_position = max_position_usd
        self.max_positions = max_open_positions
        self.max_trade = max_single_trade_usd
        
        # Daily tracking
        self._current_date: date = date.today()
        self.daily_pnl: float = 0.0
        self.daily_trades: int = 0
        
        # Position tracking
        self.open_positions: int = 0
        
        # Safety flags
        self.is_halted: bool = False
        self.halt_reason: str = ""
        
        # Stats
        self.trades_approved = 0
        self.trades_rejected = 0
    
    def _reset_daily_if_needed(self):
        """Reset daily counters if it's a new day."""
        today = date.today()
        if today != self._current_date:
            logger.info(
                "risk_daily_reset",
                previous_pnl=f"${self.daily_pnl:.2f}",
                previous_trades=self.daily_trades
            )
            self._current_date = today
            self.daily_pnl = 0.0
            self.daily_trades = 0
            
            # Clear halt if it was due to daily loss
            if self.is_halted and "daily loss" in self.halt_reason.lower():
                self.is_halted = False
                self.halt_reason = ""
    
    def validate_trade(
        self,
        price: float,
        size: float,
        fee_rate: float,
        side: str = "BUY"
    ) -> Tuple[bool, str]:
        """
        Validate a trade against risk limits.
        
        Args:
            price: Entry price
            size: Number of shares
            fee_rate: Expected fee rate
            side: "BUY" or "SELL"
        
        Returns:
            (is_valid, reason) - reason explains rejection if not valid
        """
        self._reset_daily_if_needed()
        
        # Check if halted
        if self.is_halted:
            self.trades_rejected += 1
            return (False, f"Trading halted: {self.halt_reason}")
        
        total_cost = price * size * (1 + fee_rate)
        
        # 1. Maximum trade size
        if total_cost > self.max_trade:
            self.trades_rejected += 1
            return (
                False,
                f"Trade too large: ${total_cost:.2f} > ${self.max_trade:.2f}"
            )
        
        # 2. Maximum position size
        if total_cost > self.max_position:
            self.trades_rejected += 1
            return (
                False,
                f"Position too large: ${total_cost:.2f} > ${self.max_position:.2f}"
            )
        
        # 3. Daily loss limit
        if self.daily_pnl < -self.max_daily_loss:
            self.is_halted = True
            self.halt_reason = f"Daily loss limit reached: ${-self.daily_pnl:.2f}"
            self.trades_rejected += 1
            return (False, self.halt_reason)
        
        # 4. Maximum open positions
        if side == "BUY" and self.open_positions >= self.max_positions:
            self.trades_rejected += 1
            return (
                False,
                f"Max positions reached: {self.open_positions}/{self.max_positions}"
            )
        
        # 5. Price sanity check
        if price > 0.99 or price < 0.01:
            self.trades_rejected += 1
            return (False, f"Suspicious price: {price}")
        
        # 6. Size sanity check
        if size <= 0 or size > 10000:
            self.trades_rejected += 1
            return (False, f"Invalid size: {size}")
        
        # All checks passed
        self.trades_approved += 1
        return (True, "OK")
    
    def record_trade_opened(self, cost: float):
        """Record that a position was opened."""
        self.open_positions += 1
        self.daily_trades += 1
        
        logger.info(
            "risk_position_opened",
            cost=f"${cost:.2f}",
            open_positions=self.open_positions,
            daily_trades=self.daily_trades
        )
    
    def record_trade_closed(self, pnl: float):
        """
        Record that a position was closed.
        
        Args:
            pnl: Profit/loss from the trade (positive = profit)
        """
        self.open_positions = max(0, self.open_positions - 1)
        self.daily_pnl += pnl
        
        logger.info(
            "risk_position_closed",
            pnl=f"${pnl:.2f}",
            daily_pnl=f"${self.daily_pnl:.2f}",
            open_positions=self.open_positions
        )
        
        # Check if we've hit daily loss limit
        if self.daily_pnl < -self.max_daily_loss:
            self.is_halted = True
            self.halt_reason = f"Daily loss limit: ${-self.daily_pnl:.2f}"
            
            logger.warning(
                "risk_trading_halted",
                reason=self.halt_reason
            )
    
    def halt_trading(self, reason: str):
        """Manually halt trading."""
        self.is_halted = True
        self.halt_reason = reason
        logger.warning("risk_manual_halt", reason=reason)
    
    def resume_trading(self):
        """Resume trading (use with caution)."""
        self.is_halted = False
        self.halt_reason = ""
        logger.info("risk_trading_resumed")
    
    def get_risk_summary(self) -> dict:
        """Generate a risk summary."""
        self._reset_daily_if_needed()
        
        remaining_loss_budget = self.max_daily_loss + self.daily_pnl
        
        return {
            "is_halted": self.is_halted,
            "halt_reason": self.halt_reason,
            "daily_pnl": f"${self.daily_pnl:.2f}",
            "daily_trades": self.daily_trades,
            "open_positions": f"{self.open_positions}/{self.max_positions}",
            "remaining_loss_budget": f"${max(0, remaining_loss_budget):.2f}",
            "trades_approved": self.trades_approved,
            "trades_rejected": self.trades_rejected,
            "approval_rate": (
                f"{self.trades_approved / max(1, self.trades_approved + self.trades_rejected):.1%}"
            )
        }
    
    def get_stats(self) -> dict:
        """Return risk manager statistics."""
        return self.get_risk_summary()
