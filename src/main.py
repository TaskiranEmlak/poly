"""
Polymarket HFT Bot - Main Entry Point
======================================

Hybrid strategy combining:
1. Oracle Latency Arbitrage (snipe stale orders)
2. Market Making (earn spread + rebates)

USAGE:
    python -m src.main

IMPORTANT:
    1. Copy .env.example to .env and configure
    2. Start with DRY_RUN=true for paper trading
    3. Only use real money after validating the strategy
"""

import asyncio
import signal
import sys
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from py_clob_client.client import ClobClient

# Local imports
from src.utils.logger import configure_logging, get_logger
from src.data.binance_feed import BinancePriceFeed
from src.data.polymarket_feed import PolymarketFeed
from src.data.market_discovery import (
    discover_15min_btc_markets,
    parse_strike_from_question,
    calculate_remaining_seconds
)
from src.strategy.fair_value import FairValueCalculator
from src.strategy.latency_arb import OracleLatencyEngine
from src.strategy.market_maker import MarketMakerEngine
from src.risk.fee_calculator import DynamicFeeCalculator
from src.risk.risk_manager import RiskManager
from src.execution.order_manager import OrderManager
from config.settings import settings

# Configure logging
configure_logging(level=settings.log_level)
logger = get_logger(__name__)


class PolymarketHFTBot:
    """
    Main bot orchestrator.
    
    Combines Oracle Latency Arbitrage and Market Making strategies
    for trading Polymarket 15-minute BTC prediction markets.
    """
    
    def __init__(self):
        """Initialize bot components."""
        self.dry_run = settings.dry_run
        
        logger.info(
            "bot_initializing",
            dry_run=self.dry_run,
            min_edge=f"{settings.min_edge_percent}%",
            max_position=f"${settings.max_position_usd}"
        )
        
        # Core calculators
        self.fair_calc = FairValueCalculator(
            annual_volatility=settings.annual_volatility
        )
        self.fee_calc = DynamicFeeCalculator()
        
        # Risk manager
        self.risk_manager = RiskManager(
            max_daily_loss_usd=settings.daily_loss_limit_usd,
            max_position_usd=settings.max_position_usd,
            max_open_positions=settings.max_open_positions,
            max_single_trade_usd=settings.max_single_trade_usd
        )
        
        # Initialize Polymarket client (if not dry run or for data access)
        self.clob_client: Optional[ClobClient] = None
        self._init_polymarket_client()
        
        # Order manager
        self.order_manager = OrderManager(
            clob_client=self.clob_client,
            risk_manager=self.risk_manager,
            dry_run=self.dry_run
        )
        
        # Strategy engines
        self.latency_engine = OracleLatencyEngine(
            fair_value_calc=self.fair_calc,
            fee_calc=self.fee_calc,
            min_edge_after_fees=settings.min_edge_percent / 100,
            max_position_usd=settings.max_position_usd,
            cooldown_seconds=settings.snipe_cooldown_seconds
        )
        
        self.mm_engine = MarketMakerEngine(
            fair_value_calc=self.fair_calc,
            spread_bps=settings.spread_bps,
            quote_size=Decimal(str(settings.quote_size)),
            max_inventory_imbalance=settings.max_inventory_imbalance,
            refresh_interval_ms=settings.quote_refresh_ms
        )
        
        # State
        self.current_binance_price: Decimal = Decimal("0")
        self.last_binance_update_ms: int = 0
        self.active_market: Optional[dict] = None
        self.running = False
        
        # Feeds
        self.binance_feed: Optional[BinancePriceFeed] = None
        self.polymarket_feed: Optional[PolymarketFeed] = None
        
        # Local orderbook cache
        self.current_orderbook: Optional[dict] = None
    
    def _init_polymarket_client(self):
        """Initialize the Polymarket CLOB client."""
        if not settings.private_key or settings.private_key.startswith("0x_"):
            if not self.dry_run:
                logger.error(
                    "missing_private_key",
                    message="Private key not configured. Set PRIVATE_KEY in .env"
                )
            self.clob_client = ClobClient(
                host=settings.polymarket_host
            )
            return
        
        try:
            self.clob_client = ClobClient(
                host=settings.polymarket_host,
                key=settings.private_key,
                chain_id=137,  # Polygon
                signature_type=0,  # EOA
                funder=settings.funder_address or None
            )
            
            # Derive/create API credentials
            self.clob_client.set_api_creds(
                self.clob_client.create_or_derive_api_creds()
            )
            
            logger.info("polymarket_client_initialized")
            
        except Exception as e:
            logger.error("polymarket_client_error", error=str(e))
            # Fall back to read-only client
            self.clob_client = ClobClient(host=settings.polymarket_host)
    
    async def on_binance_price(self, price: Decimal, timestamp_ms: int):
        """
        Callback for Binance price updates.
        
        This is where the main strategy logic runs.
        """
        self.current_binance_price = price
        self.last_binance_update_ms = timestamp_ms
        
        if not self.active_market or not self.current_orderbook:
            return
        
        # Parse market data
        strike = parse_strike_from_question(self.active_market["question"])
        if not strike:
            return
        
        strike_decimal = Decimal(str(strike))
        
        # Calculate remaining time
        remaining = calculate_remaining_seconds(self.active_market["end_date"])
        
        if remaining <= 0:
            # Market closed - discover new one
            await self._discover_new_market()
            return
        
        # =========================================
        # STRATEGY 1: Oracle Latency Arbitrage
        # =========================================
        opportunity = self.latency_engine.evaluate_opportunity(
            binance_price=self.current_binance_price,
            strike_price=strike_decimal,
            remaining_seconds=remaining,
            orderbook=self.current_orderbook,
            market_question=self.active_market["question"]
        )
        
        if opportunity:
            logger.info(
                "snipe_opportunity",
                side=opportunity.side,
                fair_price=f"{opportunity.fair_price:.4f}",
                stale_price=str(opportunity.stale_price),
                expected_profit=f"${opportunity.expected_profit:.4f}"
            )
            
            if not self.dry_run:
                # Calculate position size
                size = self.latency_engine.calculate_position_size(opportunity)
                
                # Execute snipe
                result = await self.order_manager.place_market_order(
                    token_id=opportunity.token_id,
                    side="BUY",
                    amount=float(opportunity.stale_price) * size
                )
                
                if result.get("success"):
                    self.latency_engine.record_execution(
                        success=True,
                        profit=opportunity.expected_profit * size
                    )
            else:
                # Dry run - just log
                self.latency_engine.record_execution(success=True)
        
        # =========================================
        # STRATEGY 2: Market Making
        # =========================================
        # Only run if no latency opportunity (avoid conflicts)
        if not opportunity:
            orders_to_cancel, new_quotes = self.mm_engine.generate_quote_update(
                binance_price=self.current_binance_price,
                strike_price=strike_decimal,
                remaining_seconds=remaining,
                orderbook=self.current_orderbook,
                token_id=self.active_market["tokens"]["yes"]
            )
            
            # Cancel stale orders
            for order_id in orders_to_cancel:
                await self.order_manager.cancel_order(order_id)
                self.mm_engine.record_order_canceled(order_id)
            
            # Place new quotes
            for quote in new_quotes:
                result = await self.order_manager.place_limit_order(
                    token_id=quote.token_id,
                    side=quote.side,
                    price=float(quote.price),
                    size=float(quote.size)
                )
                
                if result.get("success"):
                    self.mm_engine.record_order_placed(result["order_id"])
    
    async def on_orderbook_update(self, token_id: str, orderbook: dict):
        """Callback for Polymarket orderbook updates."""
        self.current_orderbook = orderbook
    
    async def _discover_new_market(self):
        """Discover a new active 15-minute BTC market."""
        logger.info("discovering_new_market")
        
        try:
            markets = await discover_15min_btc_markets(settings.gamma_api)
            
            if markets:
                self.active_market = markets[0]
                
                logger.info(
                    "new_market_found",
                    question=self.active_market["question"],
                    end_date=self.active_market["end_date"]
                )
                
                # Subscribe to the new market
                if self.polymarket_feed and self.active_market["tokens"]["yes"]:
                    await self.polymarket_feed.subscribe(
                        self.active_market["tokens"]["yes"]
                    )
            else:
                logger.warning("no_active_markets_found")
                self.active_market = None
                
        except Exception as e:
            logger.error("market_discovery_error", error=str(e))
    
    def _print_startup_banner(self):
        """Print startup banner with configuration."""
        fee_table = self.fee_calc.format_fee_table()
        
        banner = f"""
╔══════════════════════════════════════════════════════════════════╗
║         POLYMARKET BTC 15-MIN HFT BOT                            ║
╠══════════════════════════════════════════════════════════════════╣
║  Mode: {'DRY RUN (Paper Trading)' if self.dry_run else '🔴 LIVE TRADING 🔴'}                         
║                                                                  
║  Strategy: Hybrid Oracle Latency + Market Making                 
║  Min Edge: {settings.min_edge_percent}%                                           
║  Max Position: ${settings.max_position_usd}                                       
║  Daily Loss Limit: ${settings.daily_loss_limit_usd}                                 
║                                                                  
╠══════════════════════════════════════════════════════════════════╣
{fee_table}
╚══════════════════════════════════════════════════════════════════╝
"""
        print(banner)
    
    def _print_stats(self):
        """Print current statistics."""
        print("\n" + "=" * 60)
        print("CURRENT STATISTICS")
        print("=" * 60)
        
        print("\n📈 Latency Arbitrage:")
        for k, v in self.latency_engine.get_stats().items():
            print(f"   {k}: {v}")
        
        print("\n💹 Market Making:")
        for k, v in self.mm_engine.get_stats().items():
            print(f"   {k}: {v}")
        
        print("\n⚠️ Risk Manager:")
        for k, v in self.risk_manager.get_risk_summary().items():
            print(f"   {k}: {v}")
        
        print("\n📝 Order Manager:")
        for k, v in self.order_manager.get_stats().items():
            print(f"   {k}: {v}")
        
        print("=" * 60 + "\n")
    
    async def run(self):
        """Main bot execution loop."""
        self._print_startup_banner()
        
        self.running = True
        
        # Discover initial market
        await self._discover_new_market()
        
        if not self.active_market:
            logger.error("no_markets_available")
            return
        
        # Initialize feeds
        self.binance_feed = BinancePriceFeed(
            on_price_update=self.on_binance_price,
            wss_url=settings.binance_wss
        )
        
        self.polymarket_feed = PolymarketFeed(
            on_orderbook_update=self.on_orderbook_update,
            wss_url=settings.polymarket_ws
        )
        
        # Subscribe to active market
        if self.active_market["tokens"]["yes"]:
            await self.polymarket_feed.subscribe(
                self.active_market["tokens"]["yes"]
            )
        
        # Start feed tasks
        binance_task = asyncio.create_task(self.binance_feed.connect())
        polymarket_task = asyncio.create_task(self.polymarket_feed.connect())
        
        # Stats printing task
        async def print_stats_periodically():
            while self.running:
                await asyncio.sleep(60)  # Print every minute
                if self.running:
                    self._print_stats()
        
        stats_task = asyncio.create_task(print_stats_periodically())
        
        # Market refresh task
        async def refresh_market_periodically():
            while self.running:
                await asyncio.sleep(300)  # Check every 5 minutes
                if self.running:
                    await self._discover_new_market()
        
        refresh_task = asyncio.create_task(refresh_market_periodically())
        
        # Volatility update task
        async def update_volatility_periodically():
            while self.running:
                try:
                    vol = await BinancePriceFeed.fetch_realtime_volatility()
                    self.fair_calc.annual_vol = vol
                    logger.info("volatility_updated", new_vol=f"{vol:.2%}")
                except Exception as e:
                    logger.error("vol_update_error", error=str(e))
                
                await asyncio.sleep(3600)  # Update every hour
        
        vol_task = asyncio.create_task(update_volatility_periodically())
        
        try:
            # Run until stopped
            await asyncio.gather(
                binance_task,
                polymarket_task,
                stats_task,
                refresh_task,
                vol_task
            )
        except asyncio.CancelledError:
            logger.info("bot_tasks_cancelled")
        finally:
            self.running = False
            self._print_stats()
    
    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("bot_shutting_down")
        
        self.running = False
        
        # Cancel all orders
        await self.order_manager.cancel_all_orders()
        
        # Stop feeds
        if self.binance_feed:
            self.binance_feed.stop()
        if self.polymarket_feed:
            self.polymarket_feed.stop()
        
        logger.info("bot_shutdown_complete")


async def main():
    """Entry point."""
    bot = PolymarketHFTBot()
    
    # Setup signal handlers
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("shutdown_signal_received")
        asyncio.create_task(bot.shutdown())
    
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
        await bot.shutdown()
    except Exception as e:
        logger.error("bot_crashed", error=str(e), exc_info=True)
        await bot.shutdown()
        raise


if __name__ == "__main__":
    # Optimize event loop on non-Windows systems
    if sys.platform != "win32":
        try:
            import uvloop
            uvloop.install()
            print("🚀 uvloop installed for maximum performance")
        except ImportError:
            pass

    print("\n🚀 Starting Polymarket HFT Bot...\n")
    asyncio.run(main())
