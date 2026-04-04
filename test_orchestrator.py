"""Smoke test — runs 2 optimized agents on Browser-Use Cloud.
Tests: initial_actions pre-nav, use_vision=False, flash_mode, step callbacks."""
import asyncio
import time

from contracts import Playbook
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from orchestrator import Orchestrator, register_playbook


class StubEbayPlaybook(Playbook):
    platform = "ebay"

    def research_task(self, item):
        query = item.name_guess.replace(" ", "+")
        url = f"https://www.ebay.com/sch/i.html?_nkw={query}&LH_Complete=1&LH_Sold=1"
        # initial_actions navigates BEFORE the LLM runs (no LLM call for navigation)
        # Task assumes agent is ALREADY on the search results page
        return (
            "Extract the sold prices of the first 5 listings and the total number of results. "
            "Return the average price and count.",
            [{"navigate": {"url": url}}],
        )

    def listing_task(self, item, package):
        return ("Stub — do not list.", [])

    def parse_research(self, result):
        return {"avg_sold_price": 799.0, "listings_found": 5}


class StubFacebookPlaybook(Playbook):
    platform = "facebook"

    def research_task(self, item):
        query = item.name_guess.replace(" ", "%20")
        url = f"https://www.facebook.com/marketplace/search/?query={query}"
        return (
            "Extract the listing prices of the first 5 results. "
            "Return the average price and count.",
            [{"navigate": {"url": url}}],
        )

    def listing_task(self, item, package):
        return ("Stub — do not list.", [])

    def parse_research(self, result):
        return {"avg_sold_price": 750.0, "listings_found": 3}


async def drain_events(orchestrator):
    screenshot_count = 0
    while True:
        try:
            event = orchestrator.events.get_nowait()
            if event.type == "agent:screenshot":
                screenshot_count += 1
                # Don't print full b64, just note it
                url = event.data.get("url", "")
                step = event.data.get("step", "?")
                has_img = "screenshot_b64" in event.data and event.data["screenshot_b64"]
                print(f"  [SCREENSHOT #{screenshot_count}] {event.agent_id} step={step} url={url[:60]} has_image={bool(has_img)}")
            elif event.type == "agent:status":
                thoughts = event.data.get("thoughts", {})
                memory = thoughts.get("memory", "")[:80] if thoughts else ""
                actions = event.data.get("actions", [])
                action_names = [list(a.keys())[0] for a in actions if a] if actions else []
                print(f"  [STATUS] {event.agent_id} step={event.data.get('step','?')} actions={action_names} memory={memory}")
            else:
                print(f"  [{event.type}] {event.agent_id} — {event.data}")
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.3)


async def main():
    register_playbook(StubEbayPlaybook())
    register_playbook(StubFacebookPlaybook())

    orchestrator = Orchestrator(max_concurrent=2)

    item = ItemCard(
        name_guess="iPhone 15 Pro 256GB",
        job_id="test-job-001",
    )

    print(f"\n=== Orchestrator Speed + Visual Test ===")
    print(f"Item: {item.name_guess}")
    print(f"Optimizations: initial_actions, use_vision=False, flash_mode, max_actions_per_step=4")
    print(f"Visual: register_new_step_callback → agent:screenshot events")
    print(f"Starting pipeline...\n")

    drain_task = asyncio.create_task(drain_events(orchestrator))

    start = time.time()
    try:
        await orchestrator.start_pipeline("test-job-001", [item])
    except Exception as e:
        print(f"\n*** Pipeline error: {e}")
    finally:
        drain_task.cancel()

    elapsed = time.time() - start

    # Drain remaining events
    screenshot_count = 0
    while not orchestrator.events.empty():
        event = orchestrator.events.get_nowait()
        if event.type == "agent:screenshot":
            screenshot_count += 1
        else:
            print(f"  [{event.type}] {event.agent_id} — {event.data}")

    print(f"\n=== Done in {elapsed:.1f}s ===")
    print(f"Screenshots captured: {screenshot_count}")
    print(f"Agent states:")
    for state in orchestrator.get_active_agents():
        print(f"  {state.agent_id}: {state.status} ({state.platform}/{state.phase})")


if __name__ == "__main__":
    asyncio.run(main())
