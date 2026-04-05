"""Map just eBay routes first to validate the approach."""
import asyncio
from map_routes import map_single_route, ROUTES, OUTPUT_DIR
import os

async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # eBay research first
    print("\n\n>>> Starting eBay research mapping...")
    await map_single_route("ebay_research", ROUTES["ebay_research"])

    await asyncio.sleep(3)

    # eBay listing second
    print("\n\n>>> Starting eBay listing mapping...")
    await map_single_route("ebay_listing", ROUTES["ebay_listing"])

    print(f"\n\nDone! Check {OUTPUT_DIR}/ebay_research/ and {OUTPUT_DIR}/ebay_listing/")

if __name__ == "__main__":
    asyncio.run(main())
