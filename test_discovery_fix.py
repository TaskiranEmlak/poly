"""Test the updated market discovery."""
import asyncio
from src.data.market_discovery import discover_15min_btc_markets

async def main():
    print("Testing updated market discovery...")
    markets = await discover_15min_btc_markets()
    print(f"\nFound {len(markets)} BTC 15m markets:\n")
    
    for m in markets[:5]:
        print(f"  Slug: {m['slug']}")
        print(f"  Question: {m['question']}")
        print(f"  Up Price: {m['outcome_prices']['up']:.3f}")
        print(f"  Down Price: {m['outcome_prices']['down']:.3f}")
        print(f"  Tokens: Up={m['tokens']['up'][:20]}... Down={m['tokens']['down'][:20]}...")
        print(f"  End Date: {m['end_date']}")
        print(f"  Accepting Orders: {m['accepting_orders']}")
        print()

if __name__ == "__main__":
    asyncio.run(main())
