"""Check what BTC-related slugs exist in the API."""
import asyncio
import aiohttp

async def main():
    print("Fetching all markets to find BTC-related slugs...\n")
    
    async with aiohttp.ClientSession() as session:
        params = {
            "closed": "false",
            "active": "true",
            "limit": 200
        }
        
        async with session.get(
            "https://gamma-api.polymarket.com/markets",
            params=params,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            markets = await resp.json()
    
    print(f"Total markets fetched: {len(markets)}\n")
    
    # Find BTC-related markets
    
    # The following line was likely a mistake in the provided edit, as 'events' is not defined.
    # print(f"\nTotal markets fetched: {len(events)}") 
    
    btc_slugs = []
    
    for event in markets: # Changed 'events' to 'markets' to match existing variable
        # Assuming 'title' in the edit corresponds to 'question' in the original structure
        if "15m" in event.get("slug", "") or "Bitcoin Up or Down" in event.get("question", ""):
            btc_slugs.append({
                "slug": event.get("slug"),
                "question": event.get("question")
            })
    
    print(f"\nBTC-related markets found: {len(btc_slugs)}\n") # Fixed syntax error: extra '}'
    
    if btc_slugs: # Changed 'btc_markets' to 'btc_slugs'
        print("BTC market slugs:")
        for m in btc_slugs: # Changed 'btc_markets' to 'btc_slugs'
            print(f"  Slug: {m['slug']}")
            print(f"  Question: {m['question']}")
            print()
    else:
        print("No BTC markets found in current API response.")
        print("\nSample slugs from API (first 10):")
        for m in markets[:10]:
            print(f"  - {m.get('slug')}")

if __name__ == "__main__":
    asyncio.run(main())
