# Polymarket BTC 15-Min HFT Bot

A high-frequency trading bot for Polymarket's 15-minute Bitcoin prediction markets.

## ⚠️ IMPORTANT WARNINGS

1. **This bot trades with real money** - Always start with `DRY_RUN=true`
2. **15-minute markets have dynamic fees** - Up to 3.15% taker fees at 50c
3. **Past performance doesn't guarantee future results** - Markets are highly competitive
4. **Never share your private key** - Keep `.env` secure and in `.gitignore`

## Strategy Overview
The bot employs a **Smart Hybrid Strategy (Strategy 2.0)**:

### 1. Oracle Latency Arbitrage (Sniper) 🦅
- **Grand Composite Oracle:** Aggregates real-time prices from **6 Major Exchanges** (Binance, Coinbase, Kraken, Bitstamp, Gemini, Bitfinex) to match Chainlink's reference price with >99.9% accuracy.
- **Fair Value Model:** Uses Black-Scholes adapted for 15-minute binary options.
- **Data Integrity:** "Strict Mode" rejects markets with missing or invalid pricing.

### 2. Smart Trend & Momentum Filter (The Brain) 🧠
- **Trend Following:** Never trades against the SMA (Simple Moving Average).
  - *e.g., If BTC > SMA20, ONLY Long (Up) trades are permitted.*
- **RSI Protection:** Prevents buying at tops (Overbought > 70) or selling at bottoms (Oversold < 30).
- **Sentiment Analysis:** Visualizes "AI Decision" on the Dashboard.

### 3. Risk Management Fortress 🛡️
- **Consecutive Loss Limit:** Auto-halts after 3 losing trades in a row.
- **Drawdown Brake:** Stops all trading if portfolio drops by 10%.
- **Late Settlement Protection:** Voids trades if settlement is delayed > 5 mins (prevents using stale prices).

## Project Structure

```
polymarket_bot/
├── .env.example           # Configuration template
├── .gitignore             # Protects sensitive files
├── requirements.txt       # Python dependencies
├── config/
│   └── settings.py        # Pydantic settings
├── src/
│   ├── main.py            # Main bot orchestrator
│   ├── data/
│   │   ├── binance_feed.py      # Binance WebSocket client
│   │   ├── polymarket_feed.py   # Polymarket WebSocket client
│   │   └── market_discovery.py  # 15-min market finder
│   ├── strategy/
│   │   ├── fair_value.py        # Fair value calculator
│   │   ├── latency_arb.py       # Oracle latency engine
│   │   └── market_maker.py      # Market making engine
│   ├── execution/
│   │   └── order_manager.py     # Order placement/cancellation
│   ├── risk/
│   │   ├── fee_calculator.py    # Dynamic fee calculation
│   │   └── risk_manager.py      # Risk controls
│   └── utils/
│       ├── logger.py            # Structured logging
│       └── rate_limiter.py      # API rate limiting
└── tests/                  # Unit tests (TODO)
```

## Installation

### Prerequisites
- Python 3.9+ (3.11+ recommended)
- Polygon wallet with USDC
- Polymarket account

### Setup

1. **Clone and enter directory:**
```bash
cd polymarket_bot
```

2. **Create virtual environment:**
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# or
source .venv/bin/activate  # Linux/Mac
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Configure environment:**
```bash
copy .env.example .env
# Edit .env with your settings
```

## Configuration

Edit `.env` with your settings:

```env
# CRITICAL: Start with paper trading!
DRY_RUN=true

# Your Polymarket wallet
PRIVATE_KEY=0x...
FUNDER_ADDRESS=0x...

# Strategy parameters
MIN_EDGE_PERCENT=2.0     # Minimum profit margin
MAX_POSITION_USD=100.0   # Max position size

# Risk management
DAILY_LOSS_LIMIT_USD=500
MAX_OPEN_POSITIONS=5
```

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `DRY_RUN` | true | Paper trading mode |
| `MIN_EDGE_PERCENT` | 2.0 | Minimum edge to trade (%) |
| `MAX_POSITION_USD` | 100.0 | Max position per trade |
| `SPREAD_BPS` | 50 | Market making spread (0.5%) |
| `DAILY_LOSS_LIMIT_USD` | 500.0 | Stop trading if daily loss exceeds |

## Usage

### Paper Trading (Recommended First!)

```bash
# Ensure DRY_RUN=true in .env
python -m src.main
```

### Live Trading

```bash
# ONLY after validating with paper trading!
# Set DRY_RUN=false in .env
python -m src.main
```

### 📊 Dashboard

To view the live dashboard:

```bash
uvicorn dashboard.server:app --reload
```
Open http://127.0.0.1:8000 in your browser.

## Fee Structure

Polymarket's 15-minute markets have dynamic taker fees:

| Price | Fee Rate | Fee on $100 |
|-------|----------|-------------|
| $0.10 | 0.36% | $0.04 |
| $0.30 | 2.64% | $0.79 |
| $0.50 | 3.15% | $1.58 |
| $0.70 | 2.64% | $1.85 |
| $0.90 | 0.36% | $0.32 |

**Important:** Maker orders earn rebates, not pay fees!

## Risk Management

The bot enforces strict risk controls:

1. **Position Limits**: Max size per trade
2. **Daily Loss Limit**: Stops trading if daily P&L exceeds threshold
3. **Max Open Positions**: Limits concurrent exposure
4. **Price Sanity Checks**: Rejects suspicious prices

## Monitoring

The bot prints statistics every minute:

```
CURRENT STATISTICS
==============================================================

📈 Latency Arbitrage:
   opportunities_found: 5
   opportunities_taken: 2
   hit_rate: 40.00%
   total_profit: $3.50

💹 Market Making:
   yes_position: 25
   no_position: 20
   fills_received: 12
   rebates_earned: $0.45

⚠️ Risk Manager:
   daily_pnl: $45.00
   open_positions: 2/5
   remaining_loss_budget: $455.00
```

## Troubleshooting

### "No active 15-min BTC markets found"
- Markets are created every 15 minutes
- Wait for the next market to open
- Check Polymarket website to verify markets exist

### "Private key not configured"
- Ensure `PRIVATE_KEY` is set in `.env`
- Don't include quotes around the key

### Connection errors
- Check internet connection
- Verify Polygon RPC is accessible
- Try a different RPC endpoint

## Disclaimer

This software is provided "as is" without warranty. Trading cryptocurrencies and prediction markets involves substantial risk of loss. The authors are not responsible for any financial losses incurred while using this software.

## License

MIT License - See LICENSE file for details.
