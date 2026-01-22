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
    btc_markets = []
    for m in markets:
        slug = m.get("slug", "").lower()
        question = m.get("question", "").lower()
        
        if "btc" in slug or "bitcoin" in question or "btc" in question:
            btc_markets.append({
                "slug": m.get("slug"),
                "question": m.get("question", "")[:100]
            })
    
    print(f"BTC-related markets found: {len(btc_markets)}\n")
    
    if btc_markets:
        print("BTC market slugs:")
        for m in btc_markets:
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
