"""Test the market discovery module."""
import asyncio
from src.data.market_discovery import discover_15min_btc_markets

async def main():
    print("Testing market discovery with btc-updown-15m-{timestamp} pattern...")
    result = await discover_15min_btc_markets()
    print(f"\nFound {len(result)} markets matching pattern")
    
    if result:
        print("\nDiscovered markets:")
        for m in result[:10]:
            print(f"  - Slug: {m['slug']}")
            print(f"    Question: {m['question']}")
            print(f"    End Date: {m['end_date']}")
            print()
    else:
        print("\nNo markets found matching 'btc-updown-15m-{timestamp}' pattern.")
        print("This could mean:")
        print("  1. No active 15-min BTC markets are currently available")
        print("  2. The slug format may be different than expected")

if __name__ == "__main__":
    asyncio.run(main())
