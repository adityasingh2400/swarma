"""Smoke test — runs 2 stub agents on Browser-Use Cloud to validate the orchestrator."""
import asyncio
import time

from contracts import AgentEvent, Playbook
from models.item_card import ItemCard
from models.listing_package import ListingPackage
from orchestrator import Orchestrator, register_playbook


class StubEbayPlaybook(Playbook):
    platform = "ebay"

    def research_task(self, item: ItemCard) -> str:
        return (
            f'Go to https://www.ebay.com/sch/i.html?_nkw={item.name_guess.replace(" ", "+")}'
            f"&LH_Complete=1&LH_Sold=1 and find the average sold price for the top 3 results. "
            f"Return the average price and number of listings found."
        )

    def listing_task(self, item: ItemCard, package: ListingPackage) -> str:
        return "This is a stub — do not actually list anything."

    def parse_research(self, result: str) -> dict:
        # For testing, return mock data since we're just validating the pipeline
        return {"avg_sold_price": 799.0, "listings_found": 5}


class StubFacebookPlaybook(Playbook):
    platform = "facebook"

    def research_task(self, item: ItemCard) -> str:
        return (
            f"Go to https://www.facebook.com/marketplace and search for '{item.name_guess}'. "
            f"Find the average listing price from the first 3 results."
        )

    def listing_task(self, item: ItemCard, package: ListingPackage) -> str:
        return "This is a stub — do not actually list anything."

    def parse_research(self, result: str) -> dict:
        return {"avg_sold_price": 750.0, "listings_found": 3}


async def drain_events(orchestrator: Orchestrator):
    """Print events as they come in."""
    while True:
        try:
            event = orchestrator.events.get_nowait()
            print(f"  [{event.type}] {event.agent_id} — {event.data}")
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.5)


async def main():
    # Register stub playbooks
    register_playbook(StubEbayPlaybook())
    register_playbook(StubFacebookPlaybook())

    # Create orchestrator with 2 concurrent agents (small test)
    orchestrator = Orchestrator(max_concurrent=2)

    # Create a test item
    item = ItemCard(
        name_guess="iPhone 15 Pro 256GB",
        job_id="test-job-001",
    )

    print(f"\n=== Orchestrator Smoke Test ===")
    print(f"Item: {item.name_guess}")
    print(f"Playbooks: {[p.platform for p in orchestrator.agents]}" if orchestrator.agents else "Playbooks: ebay, facebook")
    print(f"Cloud: {orchestrator.profiles}")
    print(f"Starting pipeline...\n")

    # Start event drainer in background
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
    while not orchestrator.events.empty():
        event = orchestrator.events.get_nowait()
        print(f"  [{event.type}] {event.agent_id} — {event.data}")

    print(f"\n=== Done in {elapsed:.1f}s ===")
    print(f"Agent states:")
    for state in orchestrator.get_active_agents():
        print(f"  {state.agent_id}: {state.status} ({state.platform}/{state.phase})")


if __name__ == "__main__":
    asyncio.run(main())
