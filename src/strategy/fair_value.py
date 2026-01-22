"""
Fair Value Calculator
======================

Calculates the theoretical fair probability for binary options
using a simplified Black-Scholes-like model.
"""

import math
from decimal import Decimal
from scipy.stats import norm
from typing import Tuple
import structlog

logger = structlog.get_logger()


class FairValueCalculator:
    """
    Calculates fair probability for 15-minute BTC binary options.
    
    Model:
        P(BTC > Strike) = Φ((Current - Strike) / (σ × √T))
    
    Where:
        - Φ = Normal distribution CDF
        - σ = Annualized volatility (scaled for time period)
        - T = Time remaining (in years)
    
    This gives us the "true" probability which we compare to market prices.
    """
    
    # Default BTC annual volatility (calibrate with historical data)
    DEFAULT_ANNUAL_VOL = 0.80  # 80% annual volatility
    
    def __init__(self, annual_volatility: float = DEFAULT_ANNUAL_VOL):
        """
        Args:
            annual_volatility: Annualized BTC volatility (0.80 = 80%)
        """
        self.annual_vol = annual_volatility
        self._calc_count = 0
    
    def calculate_fair_probability(
        self,
        current_price: Decimal,
        strike_price: Decimal,
        remaining_seconds: int
    ) -> float:
        """
        Calculate fair probability that BTC will be above strike at expiry.
        
        Args:
            current_price: Current BTC price (from Binance)
            strike_price: Strike/target price from market
            remaining_seconds: Seconds until market closes
        
        Returns:
            Fair probability (0.0 - 1.0) that YES wins
        """
        self._calc_count += 1
        
        # Edge case: expired or about to expire
        if remaining_seconds <= 0:
            # Binary outcome - price already determined
            return 1.0 if current_price > strike_price else 0.0
        
        # Convert to float for calculations
        S = float(current_price)  # Current spot price
        K = float(strike_price)   # Strike price
        
        # Time to expiry in years
        T = remaining_seconds / (365.25 * 24 * 60 * 60)
        
        # Volatility scaled for time period
        sigma_t = self.annual_vol * math.sqrt(T)
        
        # Avoid division by zero
        if sigma_t < 0.0001 or S <= 0:
            return 1.0 if S > K else 0.0
        
        # d = (ln(S/K)) / (σ√T) for log-normal model
        # Simplified: (S - K) / (S × σ√T) for small T
        try:
            # Use log-normal for better accuracy
            d = math.log(S / K) / sigma_t if K > 0 else 0
            
            # Φ(d) = P(BTC > Strike)
            probability = norm.cdf(d)
            
        except (ValueError, ZeroDivisionError):
            probability = 1.0 if S > K else 0.0
        
        # Clip to reasonable bounds (never 0 or 1 exactly)
        return max(0.01, min(0.99, probability))
    
    def calculate_edge(
        self,
        fair_prob: float,
        market_price: Decimal,
        fee_rate: float = 0.03
    ) -> Tuple[float, str]:
        """
        Calculate expected edge over market price.
        
        Args:
            fair_prob: Our calculated fair probability
            market_price: Current YES market price (0.00 - 1.00)
            fee_rate: Taker fee rate
        
        Returns:
            (edge_amount, direction) where direction is "BUY_YES", "BUY_NO", or "NONE"
        """
        market_prob = float(market_price)
        
        # Expected value calculation for YES
        # Cost to buy YES: market_price × (1 + fee)
        # Expected payout: fair_prob × $1.00
        yes_cost = market_prob * (1 + fee_rate)
        yes_ev = fair_prob * 1.0
        yes_edge = yes_ev - yes_cost
        
        # Expected value calculation for NO
        no_price = 1.0 - market_prob
        no_cost = no_price * (1 + fee_rate)
        no_ev = (1 - fair_prob) * 1.0
        no_edge = no_ev - no_cost
        
        # Return the better opportunity
        if yes_edge > no_edge and yes_edge > 0:
            return (yes_edge, "BUY_YES")
        elif no_edge > yes_edge and no_edge > 0:
            return (no_edge, "BUY_NO")
        else:
            return (0.0, "NONE")
    
    def is_mispriced(
        self,
        fair_prob: float,
        market_price: Decimal,
        fee_rate: float = 0.03,
        min_edge: float = 0.02
    ) -> Tuple[bool, str, float]:
        """
        Check if market is mispriced enough to trade.
        
        Args:
            fair_prob: Our calculated fair probability
            market_price: Current YES market price
            fee_rate: Taker fee rate
            min_edge: Minimum required edge to trade
        
        Returns:
            (is_opportunity, direction, expected_profit)
        """
        edge, direction = self.calculate_edge(fair_prob, market_price, fee_rate)
        
        if edge >= min_edge:
            return (True, direction, edge)
        
        return (False, "NONE", 0.0)
    
    def get_stats(self) -> dict:
        """Return calculator statistics."""
        return {
            "annual_volatility": self.annual_vol,
            "calculations_performed": self._calc_count
        }
