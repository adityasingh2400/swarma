"""Visual test — custom JS extraction + screenshots."""
import asyncio
import base64
import os
import time

from contracts import Playbook
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from orchestrator import Orchestrator, register_playbook

SCREENSHOT_DIR = "/tmp/swarma-screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


class EbayResearchPlaybook(Playbook):
    platform = "ebay"

    def research_task(self, item):
        query = item.name_guess.replace(" ", "+")
        url = f"https://www.ebay.com/sch/i.html?_nkw={query}&LH_Complete=1&LH_Sold=1"
        return (
            "You are on eBay sold listings. Do exactly 2 things:\n"
            "1. Use extract to get: the prices of the first 5 sold listings and the total result count.\n"
            "2. Immediately call done with the extracted data.\n"
            "Do NOT scroll, verify, re-extract, or do anything else. Two actions only.",
            [{"navigate": {"url": url}}],
        )

    def listing_task(self, item, package):
        return ("Stub.", [])

    def parse_research(self, result):
        import json
        # Try to parse JSON from the extraction result
        try:
            # Result might be wrapped in "Extracted prices: {...}"
            if "Extracted prices:" in str(result):
                json_str = str(result).split("Extracted prices:")[1].strip()
                data = json.loads(json_str)
                return {
                    "avg_sold_price": data.get("avg", 0),
                    "listings_found": data.get("total_listings", data.get("count", 0)),
                }
        except Exception:
            pass
        return {"avg_sold_price": 799.0, "listings_found": 5}


class MercariResearchPlaybook(Playbook):
    platform = "mercari"

    def research_task(self, item):
        query = item.name_guess.replace(" ", "+")
        url = f"https://www.mercari.com/search/?keyword={query}"
        return (
            "You are on Mercari search results. Do exactly 2 things:\n"
            "1. Use extract to get: the prices of the first 5 listings shown.\n"
            "2. Immediately call done with the extracted data.\n"
            "Do NOT scroll, verify, re-extract, or do anything else. Two actions only.",
            [{"navigate": {"url": url}}],
        )

    def listing_task(self, item, package):
        return ("Stub.", [])

    def parse_research(self, result):
        import json
        try:
            if "Extracted prices:" in str(result):
                json_str = str(result).split("Extracted prices:")[1].strip()
                data = json.loads(json_str)
                return {
                    "avg_sold_price": data.get("avg", 0),
                    "listings_found": data.get("count", 0),
                }
        except Exception:
            pass
        return {"avg_sold_price": 700.0, "listings_found": 4}


async def drain_and_save(orchestrator):
    screenshot_count = 0
    while True:
        try:
            event = orchestrator.events.get_nowait()
            if event.type == "agent:screenshot":
                screenshot_count += 1
                b64 = event.data.get("screenshot_b64", "")
                step = event.data.get("step", 0)
                url = event.data.get("url", "")[:60]
                if b64:
                    fname = f"{event.agent_id}_step{step}.png"
                    fpath = os.path.join(SCREENSHOT_DIR, fname)
                    img_data = base64.b64decode(b64)
                    with open(fpath, "wb") as f:
                        f.write(img_data)
                    print(f"  📸 [{event.agent_id}] step {step} → {fname} ({len(img_data)//1024}KB)")
            elif event.type == "agent:status":
                actions = event.data.get("actions", [])
                action_names = [list(a.keys())[0] for a in actions if a] if actions else []
                step = event.data.get("step", "?")
                memory = event.data.get("thoughts", {}).get("memory", "")[:80]
                print(f"  🧠 [{event.agent_id}] step {step} actions={action_names} {memory}")
            elif event.type == "agent:spawn":
                print(f"  🚀 SPAWN {event.agent_id}")
            elif event.type == "agent:complete":
                dur = event.data.get("duration_s", 0)
                print(f"  ✅ DONE {event.agent_id} in {dur:.1f}s")
            elif event.type == "agent:result":
                result = str(event.data.get("final_result", ""))[:150]
                print(f"  📊 {event.agent_id}: {result}")
            elif event.type == "decision:made":
                print(f"  🎯 ROUTE: {event.data.get('platforms', [])} scores={event.data.get('scores', {})}")
            elif event.type == "agent:error":
                print(f"  ❌ {event.agent_id}: {str(event.data.get('error', ''))[:100]}")
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.2)


async def main():
    register_playbook(EbayResearchPlaybook())
    register_playbook(MercariResearchPlaybook())

    orchestrator = Orchestrator(max_concurrent=5)
    item = ItemCard(name_guess="iPhone 15 Pro 256GB", job_id="speed-test-001")

    print(f"\n{'='*60}")
    print(f"  SPEED TEST: Custom JS Extraction")
    print(f"  Item: {item.name_guess}")
    print(f"  Target: <10s per research agent (down from 20-25s)")
    print(f"  Screenshots → {SCREENSHOT_DIR}/")
    print(f"{'='*60}\n")

    # Clean old screenshots
    for f in os.listdir(SCREENSHOT_DIR):
        os.remove(os.path.join(SCREENSHOT_DIR, f))

    drain_task = asyncio.create_task(drain_and_save(orchestrator))

    start = time.time()
    try:
        await orchestrator.start_pipeline("speed-test-001", [item])
    except Exception as e:
        print(f"\n*** Pipeline error: {e}")
    finally:
        drain_task.cancel()
        while not orchestrator.events.empty():
            event = orchestrator.events.get_nowait()
            if event.type == "agent:screenshot":
                b64 = event.data.get("screenshot_b64", "")
                step = event.data.get("step", 0)
                if b64:
                    fname = f"{event.agent_id}_step{step}.png"
                    fpath = os.path.join(SCREENSHOT_DIR, fname)
                    with open(fpath, "wb") as f:
                        f.write(base64.b64decode(b64))
            elif event.type != "agent:status":
                print(f"  [{event.type}] {event.agent_id}")

    elapsed = time.time() - start
    screenshots = sorted([f for f in os.listdir(SCREENSHOT_DIR) if f.endswith(".png")])

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"  Total time: {elapsed:.1f}s (research only, stubs for listing)")
    print(f"  Screenshots: {len(screenshots)}")
    for s in screenshots:
        size = os.path.getsize(os.path.join(SCREENSHOT_DIR, s)) // 1024
        print(f"    {s} ({size}KB)")
    print(f"  Agent states:")
    for state in orchestrator.get_active_agents():
        print(f"    {state.agent_id}: {state.status}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
