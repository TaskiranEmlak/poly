"""
Pydantic Settings Configuration
================================

All bot configuration is loaded from environment variables.
Copy .env.example to .env and fill in your values.
"""

from decimal import Decimal
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Main configuration settings loaded from environment."""
    
    # ==========================================
    # MODE
    # ==========================================
    dry_run: bool = Field(
        default=True,
        description="Paper trading mode - no real trades"
    )
    
    # ==========================================
    # WALLET & AUTH
    # ==========================================
    private_key: str = Field(
        default="",
        description="Ethereum private key for signing"
    )
    funder_address: str = Field(
        default="",
        description="Polymarket wallet address that holds funds"
    )
    rpc_url: str = Field(
        default="https://polygon-rpc.com",
        description="Polygon RPC endpoint"
    )
    
    # ==========================================
    # POLYMARKET API
    # ==========================================
    polymarket_host: str = Field(
        default="https://clob.polymarket.com",
        description="Polymarket CLOB API host"
    )
    polymarket_ws: str = Field(
        default="wss://ws-subscriptions-clob.polymarket.com/ws/market",
        description="Polymarket WebSocket endpoint"
    )
    gamma_api: str = Field(
        default="https://gamma-api.polymarket.com",
        description="Polymarket Gamma API for market discovery"
    )
    
    # ==========================================
    # BINANCE
    # ==========================================
    binance_wss: str = Field(
        default="wss://fstream.binance.com/ws",
        description="Binance Futures WebSocket"
    )
    
    # ==========================================
    # STRATEGY SELECTION
    # ==========================================
    strategy_type: str = Field(
        default="hybrid",
        description="Strategy mode: 'hybrid', 'maker_only', or 'taker_only'"
    )

    # ==========================================
    # ORACLE LATENCY ARBITRAGE
    # ==========================================
    min_edge_percent: float = Field(
        default=2.0,
        description="Minimum edge after fees to take a snipe"
    )
    max_position_usd: float = Field(
        default=100.0,
        description="Maximum position size per trade"
    )
    annual_volatility: float = Field(
        default=0.80,
        description="BTC annual volatility for fair value calculation"
    )
    snipe_cooldown_seconds: float = Field(
        default=5.0,
        description="Cooldown between snipe attempts"
    )
    
    # ==========================================
    # MARKET MAKING
    # ==========================================
    spread_bps: int = Field(
        default=50,
        description="Quote spread in basis points"
    )
    quote_size: float = Field(
        default=50.0,
        description="Default quote size in shares"
    )
    max_inventory_imbalance: float = Field(
        default=0.30,
        description="Max inventory skew before rebalancing"
    )
    quote_refresh_ms: int = Field(
        default=1000,
        description="Quote refresh interval in milliseconds"
    )
    
    # ==========================================
    # RISK MANAGEMENT
    # ==========================================
    daily_loss_limit_usd: float = Field(
        default=500.0,
        description="Stop trading if daily loss exceeds this"
    )
    max_open_positions: int = Field(
        default=5,
        description="Maximum concurrent open positions"
    )
    max_single_trade_usd: float = Field(
        default=100.0,
        description="Maximum single trade size"
    )
    
    # ==========================================
    # RATE LIMITING
    # ==========================================
    max_orders_per_second: int = Field(
        default=50,
        description="Rate limit for order operations"
    )
    order_lifetime_ms: int = Field(
        default=3000,
        description="Cancel orders older than this"
    )
    
    # ==========================================
    # LOGGING
    # ==========================================
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )
    metrics_port: int = Field(
        default=9305,
        description="Prometheus metrics port"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
