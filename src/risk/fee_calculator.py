"""
Dynamic Fee Calculator
=======================

Calculates Polymarket's dynamic taker fees for 15-minute markets.

CRITICAL: These fees were introduced in January 2026 and make 
simple arbitrage strategies unprofitable!
"""

from decimal import Decimal
from typing import Tuple
import structlog

logger = structlog.get_logger()


class DynamicFeeCalculator:
    """
    Calculates taker fees for Polymarket 15-minute markets.
    
    Fee Structure (as of January 2026):
    - Maximum fee at 50c (highest uncertainty): ~3.15%
    - Fees decrease toward extremes (near 0c or 100c)
    - At 10c or 90c: ~0.20%
    
    This follows a parabolic curve: fee = max_fee × 4 × p × (1-p)
    where p is the share price.
    
    IMPORTANT: Maker orders earn rebates, not pay fees!
    """
    
    # Maximum fee at 50c (from Polymarket documentation)
    MAX_FEE_BPS = 315  # 3.15%
    
    def __init__(self, max_fee_bps: int = 315):
        """
        Args:
            max_fee_bps: Maximum fee in basis points at 50c
        """
        self.max_fee_bps = max_fee_bps
        self._calculations = 0
        
        # SAFETY CHECK: Warn user to verify fees
        logger.warning(
            "fee_structure_check",
            message="Using Jan 2026 Parabolic Fee Model (Max 3.15%). Verify latest rates at docs.polymarket.com",
            max_fee_bps=max_fee_bps
        )
    
    def calculate_taker_fee(self, price: Decimal) -> float:
        """
        Calculate taker fee rate at a given price.
        
        Args:
            price: Share price (0.00 - 1.00)
        
        Returns:
            Fee rate as decimal (0.0315 = 3.15%)
        """
        self._calculations += 1
        
        p = float(price)
        
        # Parabolic fee curve
        # Maximum at p=0.5, minimum at p=0 or p=1
        # fee = max_fee × 4 × p × (1-p)
        fee_multiplier = 4 * p * (1 - p)
        
        fee_rate = (self.max_fee_bps / 10000) * fee_multiplier
        
        return max(0.0, fee_rate)
    
    def calculate_effective_cost(
        self,
        price: Decimal,
        size: Decimal
    ) -> Tuple[Decimal, Decimal]:
        """
        Calculate total cost including fees.
        
        Args:
            price: Share price
            size: Number of shares
        
        Returns:
            (total_cost, fee_amount)
        """
        fee_rate = self.calculate_taker_fee(price)
        
        base_cost = price * size
        fee_amount = base_cost * Decimal(str(fee_rate))
        total_cost = base_cost + fee_amount
        
        return (total_cost, fee_amount)
    
    def calculate_breakeven_edge(self, price: Decimal) -> float:
        """
        Calculate minimum edge needed to break even at this price.
        
        This is critical for strategy decisions!
        
        Args:
            price: Target entry price
        
        Returns:
            Minimum edge required (as decimal)
        """
        fee_rate = self.calculate_taker_fee(price)
        
        # Need to overcome round-trip fees (buy + sell)
        # But in binary options, you don't sell - you either 
        # win ($1) or lose ($0)
        # So breakeven edge = fee on entry
        return fee_rate
    
    def is_profitable_entry(
        self,
        price: Decimal,
        fair_value: float,
        side: str = "BUY"
    ) -> Tuple[bool, float]:
        """
        Check if entry is profitable after fees.
        
        Args:
            price: Entry price
            fair_value: Our calculated fair probability
            side: "BUY" (YES) or opposite
        
        Returns:
            (is_profitable, expected_profit)
        """
        fee_rate = self.calculate_taker_fee(price)
        
        entry_cost = float(price) * (1 + fee_rate)
        
        if side == "BUY":
            # Buying YES: payout is $1 if YES wins (prob = fair_value)
            expected_value = fair_value * 1.0
        else:
            # Buying NO: payout is $1 if NO wins (prob = 1 - fair_value)
            expected_value = (1 - fair_value) * 1.0
        
        expected_profit = expected_value - entry_cost
        
        return (expected_profit > 0, expected_profit)
    
    def format_fee_table(self) -> str:
        """Generate a fee table for display."""
        lines = [
            "Polymarket 15-Min Market Fee Table",
            "=" * 40,
            f"{'Price':>10} | {'Fee Rate':>10} | {'Fee on $100':>12}",
            "-" * 40
        ]
        
        for price_cents in [5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95]:
            price = Decimal(str(price_cents / 100))
            fee_rate = self.calculate_taker_fee(price)
            fee_on_100 = 100 * float(price) * fee_rate
            
            lines.append(
                f"${price_cents/100:>8.2f} | "
                f"{fee_rate*100:>9.2f}% | "
                f"${fee_on_100:>10.2f}"
            )
        
        return "\n".join(lines)
    
    def get_stats(self) -> dict:
        """Return calculator statistics."""
        return {
            "max_fee_bps": self.max_fee_bps,
            "max_fee_percent": f"{self.max_fee_bps/100:.2f}%",
            "calculations": self._calculations
        }
