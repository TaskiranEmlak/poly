"""
Technical Analysis Module
========================

Provides high-performance technical indicators using NumPy.
Designed for HFT/Algorithmic trading speed.
"""

import numpy as np
import structlog
from typing import Tuple, Optional

logger = structlog.get_logger()

class TechnicalAnalysis:
    """
    Calculates technical indicators from price arrays.
    """
    
    @staticmethod
    def calculate_rsi(prices: list, period: int = 14) -> float:
        """
        Relative Strength Index (RSI).
        
        Args:
            prices: List of closing prices (must have at least period + 1)
            period: Lookback period (default 14)
            
        Returns:
            RSI value (0-100) or 50.0 if insufficient data
        """
        if len(prices) < period + 1:
            return 50.0
            
        try:
            # precise calculation using numpy
            deltas = np.diff(prices)
            seed = deltas[:period+1]
            up = seed[seed >= 0].sum() / period
            down = -seed[seed < 0].sum() / period
            rs = up / down if down != 0 else 0
            rsi = 100. - 100. / (1. + rs)

            # Smooth output for remaining
            # Note: For HFT/Live, we typically just need the LATEST value,
            # so strict Wilder's smoothing isn't strictly necessary if window is rolling.
            # But let's do a simple EMA-like smoothing for recent bars
            up_val = 0.0
            down_val = 0.0
            
            # Recalculate properly for the whole series to match TradingView
            gains = np.maximum(deltas, 0)
            losses = -np.minimum(deltas, 0)
            
            avg_gain = np.mean(gains[:period])
            avg_loss = np.mean(losses[:period])
            
            if avg_loss == 0:
                return 100.0
                
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            
            # Calculate recursive (Wilder's Smoothing)
            for i in range(period, len(prices) - 1):
                avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
                avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
                
                if avg_loss == 0:
                    rsi = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100.0 - (100.0 / (1.0 + rs))
            
            return rsi
            
        except Exception as e:
            logger.error("rsi_calc_error", error=str(e))
            return 50.0

    @staticmethod
    def calculate_sma(prices: list, period: int = 20) -> float:
        """
        Simple Moving Average (SMA).
        """
        if len(prices) < period:
            return prices[-1] if prices else 0.0
            
        try:
            return float(np.mean(prices[-period:]))
        except Exception:
            return prices[-1]
            
    @staticmethod
    def calculate_ema(prices: list, period: int = 20) -> float:
        """
        Exponential Moving Average (EMA).
        """
        if len(prices) < period:
            return prices[-1] if prices else 0.0
            
        try:
            weights = np.exp(np.linspace(-1., 0., period))
            weights /= weights.sum()
            a = np.array(prices[-period:])
            return float(np.dot(a, weights))
        except Exception:
            return prices[-1]
            
    @staticmethod
    def get_trend_state(prices: list, sma_period: int = 20) -> dict:
        """
        Determine market trend state.
        
        Returns:
            {
                "trend": "UP" | "DOWN" | "FLAT",
                "strength": 0.0-1.0,
                "rsi": float (0-100),
                "sma": float
            }
        """
        if not prices:
            return {"trend": "FLAT", "strength": 0.0, "rsi": 50.0, "sma": 0.0}
            
        current_price = prices[-1]
        sma = TechnicalAnalysis.calculate_sma(prices, sma_period)
        rsi = TechnicalAnalysis.calculate_rsi(prices)
        
        # Trend Definition
        trend = "FLAT"
        if current_price > sma * 1.0005: # 0.05% buffer
            trend = "UP"
        elif current_price < sma * 0.9995:
            trend = "DOWN"
            
        return {
            "trend": trend,
            "strength": abs(current_price - sma) / sma, # Distance from SMA
            "rsi": rsi,
            "sma": sma,
            "current_price": current_price
        }
