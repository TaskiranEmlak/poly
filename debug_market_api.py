import asyncio
import aiohttp
import json
import re

async def main():
    async with aiohttp.ClientSession() as session:
        params = {
            "tag_slug": "15M",
            "closed": "false",
            "active": "true",
            "limit": 5
        }
        url = "https://gamma-api.polymarket.com/events"
        print(f"Fetching from {url}...")
        
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                print(f"Error: {resp.status}")
                return
            
            data = await resp.json()
            print(f"Fetched {len(data)} events")
            
            for event in data:
                slug = event.get("slug", "")
                if "btc" in slug and "15m" in slug:
                    print(f"\n--- FOUND BTC 15M EVENT: {slug} ---")
                    print(json.dumps(event, indent=2))
                    
                    # Check description specifically
                    markets = event.get("markets", [])
                    if markets:
                        m = markets[0]
                        desc = m.get("description", "NO_DESCRIPTION")
                        print(f"\nDESCRIPTION: {desc}")
                        
                        question = m.get("question", "NO_QUESTION")
                        print(f"QUESTION: {question}")
                    break

if __name__ == "__main__":
    asyncio.run(main())
