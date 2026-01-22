"""
Rate Limiter - Token Bucket Algorithm
======================================

Implements rate limiting to prevent API throttling.
"""

import asyncio
import time
from typing import Optional


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter for API calls.
    
    Polymarket allows up to 350 orders/second, but we use
    a conservative limit to avoid issues.
    """
    
    def __init__(
        self,
        rate: float = 50.0,  # tokens per second
        capacity: float = 50.0  # max tokens in bucket
    ):
        """
        Args:
            rate: Tokens added per second
            capacity: Maximum tokens the bucket can hold
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: float = 1.0) -> float:
        """
        Acquire tokens from the bucket.
        
        Blocks if not enough tokens available.
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            Time waited (seconds)
        """
        async with self._lock:
            wait_time = 0.0
            
            # Refill bucket based on time elapsed
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now
            
            # Check if we need to wait
            if tokens > self.tokens:
                # Calculate wait time
                deficit = tokens - self.tokens
                wait_time = deficit / self.rate
                
                await asyncio.sleep(wait_time)
                
                # Refill after waiting
                self.tokens = min(
                    self.capacity,
                    self.tokens + wait_time * self.rate
                )
            
            # Consume tokens
            self.tokens -= tokens
            
            return wait_time
    
    def try_acquire(self, tokens: float = 1.0) -> bool:
        """
        Try to acquire tokens without waiting.
        
        Args:
            tokens: Number of tokens to acquire
        
        Returns:
            True if tokens were acquired, False if not available
        """
        # Refill bucket
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.rate
        )
        self.last_update = now
        
        if tokens <= self.tokens:
            self.tokens -= tokens
            return True
        
        return False
    
    def get_wait_time(self, tokens: float = 1.0) -> float:
        """
        Get estimated wait time without acquiring.
        
        Args:
            tokens: Number of tokens needed
        
        Returns:
            Estimated wait time in seconds
        """
        # Refill bucket
        now = time.monotonic()
        elapsed = now - self.last_update
        current_tokens = min(
            self.capacity,
            self.tokens + elapsed * self.rate
        )
        
        if tokens <= current_tokens:
            return 0.0
        
        deficit = tokens - current_tokens
        return deficit / self.rate
    
    def reset(self):
        """Reset the bucket to full capacity."""
        self.tokens = self.capacity
        self.last_update = time.monotonic()


# Global rate limiter instance
_global_limiter: Optional[TokenBucketRateLimiter] = None


def get_rate_limiter(
    rate: float = 50.0,
    capacity: float = 50.0
) -> TokenBucketRateLimiter:
    """
    Get the global rate limiter instance.
    
    Creates one if it doesn't exist.
    """
    global _global_limiter
    
    if _global_limiter is None:
        _global_limiter = TokenBucketRateLimiter(rate, capacity)
    
    return _global_limiter
