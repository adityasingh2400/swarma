"""Map all 8 routes sequentially using authenticated Chrome CDP."""
import asyncio
from map_routes import map_single_route, ROUTES, OUTPUT_DIR
import os

async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    route_order = [
        "ebay_listing",      # most important — failed before due to login
        "ebay_research",
        "mercari_listing",
        "mercari_research",
        "facebook_listing",
        "facebook_research",
        "depop_listing",
        "depop_research",
    ]

    for name in route_order:
        print(f"\n\n>>> {name}...")
        await map_single_route(name, ROUTES[name])
        await asyncio.sleep(3)

    print(f"\n\n=== ALL DONE === Check {OUTPUT_DIR}/")

if __name__ == "__main__":
    asyncio.run(main())
