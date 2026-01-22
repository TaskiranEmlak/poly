import unittest
import sys
import os
from decimal import Decimal

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.strategy.fair_value import FairValueCalculator

class TestFairValueCalculator(unittest.TestCase):
    def setUp(self):
        self.calculator = FairValueCalculator(annual_volatility=0.8)
    
    def test_fair_probability_at_strike(self):
        """At current = strike, probability should be roughly 0.50"""
        prob = self.calculator.calculate_fair_probability(
            current_price=Decimal("90000"),
            strike_price=Decimal("90000"),
            remaining_seconds=300
        )
        self.assertTrue(0.48 <= prob <= 0.52)
        
    def test_high_probability(self):
        """Current > Strike should yield high probability"""
        prob = self.calculator.calculate_fair_probability(
            current_price=Decimal("91000"),
            strike_price=Decimal("90000"),
            remaining_seconds=60
        )
        self.assertGreater(prob, 0.90)
        
    def test_low_probability(self):
        """Current < Strike should yield low probability"""
        prob = self.calculator.calculate_fair_probability(
            current_price=Decimal("89000"),
            strike_price=Decimal("90000"),
            remaining_seconds=60
        )
        self.assertLess(prob, 0.10)
        
    def test_expired_market(self):
        """Expired market logic check"""
        prob = self.calculator.calculate_fair_probability(
            current_price=Decimal("90001"),
            strike_price=Decimal("90000"),
            remaining_seconds=0
        )
        self.assertEqual(prob, 1.0)
        
        prob = self.calculator.calculate_fair_probability(
            current_price=Decimal("89999"),
            strike_price=Decimal("90000"),
            remaining_seconds=0
        )
        self.assertEqual(prob, 0.0)

if __name__ == "__main__":
    unittest.main()
