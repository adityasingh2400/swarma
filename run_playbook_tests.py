"""
Run all playbook live tests in one shot.

    python run_playbook_tests.py              # research + listing, all platforms
    python run_playbook_tests.py research     # research only
    python run_playbook_tests.py listing      # listing only
    python run_playbook_tests.py ebay         # one platform (research + listing)
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from browser_use import Agent, BrowserProfile
from browser_use import ChatBrowserUse

from config import settings
from models.item_card import DefectSignal, ItemCard, ItemCategory
from models.listing_package import ListingImage, ListingPackage
from playbooks.amazon import AmazonPlaybook
from playbooks.depop import DepopPlaybook
from playbooks.ebay import EbayPlaybook
from playbooks.facebook import FacebookPlaybook
from playbooks.mercari import MercariPlaybook


# ---------------------------------------------------------------------------
# Preset item — iPhone 13 Pro (used for all platforms except Depop)
# ---------------------------------------------------------------------------

ITEM = ItemCard(
    item_id="live_test_001",
    name_guess="iPhone 13 Pro 256GB",
    category=ItemCategory.ELECTRONICS,
    visible_defects=[
        DefectSignal(description="small scratch on back glass", source="visual", severity="minor"),
    ],
    accessories_included=["original charger", "box"],
    confidence=0.92,
)

IMAGES = [
    ListingImage(path="./data/test_images/hero.jpg",   role="hero"),
    ListingImage(path="./data/test_images/defect.jpg", role="defect_proof"),
    ListingImage(path="./data/test_images/spec.jpg",   role="spec_card"),
    ListingImage(path="./data/test_images/side1.jpg",  role="secondary"),
    ListingImage(path="./data/test_images/side2.jpg",  role="secondary"),
    ListingImage(path="./data/test_images/back.jpg",   role="secondary"),
]

PACKAGE = ListingPackage(
    item_id="live_test_001",
    title="Apple iPhone 13 Pro 256GB Sierra Blue Unlocked",
    description=(
        "Apple iPhone 13 Pro 256GB Sierra Blue — unlocked for all carriers.\n\n"
        "Condition: Good. Minor scratch on back glass, screen is perfect, "
        "Face ID and all features fully functional.\n\n"
        "Includes: original Apple charger and box.\n\n"
        "Ships fast in original packaging."
    ),
    price_strategy=549.00,
    images=IMAGES,
)

# Depop preset — clothing item
CLOTHING_ITEM = ItemCard(
    item_id="live_test_002",
    name_guess="Levi's 501 Jeans 32x32",
    category=ItemCategory.CLOTHING,
    confidence=0.88,
)

CLOTHING_PACKAGE = ListingPackage(
    item_id="live_test_002",
    title="Levi's 501 Original Fit Jeans 32x32 Medium Wash",
    description=(
        "Classic Levi's 501 original fit jeans. Size 32x32, medium wash.\n\n"
        "Condition: Good. Light fading consistent with wear, no rips or stains.\n\n"
        "Ships USPS First Class."
    ),
    price_strategy=45.00,
    images=IMAGES,
)


# ---------------------------------------------------------------------------
# Agent helpers — same pattern as orchestrator
# ---------------------------------------------------------------------------

def _llm():
    return ChatBrowserUse(api_key=settings.browser_use_api_key)


def _profile(platform: str) -> BrowserProfile:
    storage = settings.storage_state_map.get(platform)
    return BrowserProfile(
        storage_state=storage,
        headless=False,
        minimum_wait_page_load_time=0.5,
        wait_between_actions=0.3,
    )


def _step_printer(platform: str, phase: str):
    def callback(state, model_output, step: int):
        url = getattr(state, "url", "")
        goal = ""
        if model_output and hasattr(model_output, "current_state"):
            goal = getattr(model_output.current_state, "next_goal", "")
        print(f"    step {step:02d} | {url[:90]}")
        if goal:
            print(f"             {goal[:120]}")
    return callback


async def run_research(playbook, item: ItemCard) -> dict:
    task_str, initial_actions = playbook.research_task(item)

    agent = Agent(
        task=task_str,
        llm=_llm(),
        browser_profile=_profile(playbook.platform),
        flash_mode=True,
        max_actions_per_step=4,
        use_vision=False,
        initial_actions=initial_actions,
        register_new_step_callback=_step_printer(playbook.platform, "research"),
    )

    t0 = time.time()
    history = await agent.run(max_steps=8)
    elapsed = time.time() - t0

    raw = history.final_result() if history.is_done() else None
    parsed = playbook.parse_research(raw)

    print(f"    raw   : {str(raw)[:200]}")
    print(f"    parsed: {json.dumps(parsed)}")
    print(f"    done in {elapsed:.1f}s  ({history.number_of_steps()} steps)")
    return parsed


async def run_listing(playbook, item: ItemCard, package: ListingPackage) -> str | None:
    task_str, initial_actions = playbook.listing_task(item, package)

    if not initial_actions:
        print(f"    SKIPPED (research-only platform)")
        return None

    agent = Agent(
        task=task_str,
        llm=_llm(),
        browser_profile=_profile(playbook.platform),
        flash_mode=True,
        max_actions_per_step=4,
        use_vision="auto",
        initial_actions=initial_actions,
        register_new_step_callback=_step_printer(playbook.platform, "listing"),
    )

    t0 = time.time()
    history = await agent.run(max_steps=30)
    elapsed = time.time() - t0

    result = history.final_result() if history.is_done() else None
    print(f"    result: {str(result)[:300]}")
    print(f"    done in {elapsed:.1f}s  ({history.number_of_steps()} steps)")
    return result


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

PLATFORMS = {
    "ebay":     (EbayPlaybook(),     ITEM,          PACKAGE),
    "facebook": (FacebookPlaybook(), ITEM,          PACKAGE),
    "mercari":  (MercariPlaybook(),  ITEM,          PACKAGE),
    "depop":    (DepopPlaybook(),    CLOTHING_ITEM, CLOTHING_PACKAGE),
    "amazon":   (AmazonPlaybook(),   ITEM,          PACKAGE),
}


async def main(mode: str, filter_platform: str | None):
    results: dict[str, dict] = {}  # platform -> {research, listing, error}

    platforms = (
        {filter_platform: PLATFORMS[filter_platform]}
        if filter_platform and filter_platform in PLATFORMS
        else PLATFORMS
    )

    run_research_phase = mode in ("all", "research")
    run_listing_phase  = mode in ("all", "listing")

    for name, (pb, item, pkg) in platforms.items():
        results[name] = {"research": None, "listing": None, "error": None}

        if run_research_phase:
            print(f"\n{'='*60}")
            print(f"  {name.upper()} — RESEARCH")
            print(f"{'='*60}")
            try:
                results[name]["research"] = await run_research(pb, item)
            except Exception as e:
                print(f"    ERROR: {e}")
                results[name]["error"] = str(e)

        if run_listing_phase:
            print(f"\n{'='*60}")
            print(f"  {name.upper()} — LISTING")
            print(f"{'='*60}")
            try:
                results[name]["listing"] = await run_listing(pb, item, pkg)
            except Exception as e:
                print(f"    ERROR: {e}")
                results[name]["error"] = str(e)

    # Summary
    print(f"\n\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"{'platform':<12} {'research avg':>14} {'listing result':<40}")
    print("-" * 68)
    for name, r in results.items():
        research = r["research"]
        listing  = r["listing"]
        err      = r["error"]

        if err:
            row_research = f"ERROR: {err[:30]}"
            row_listing  = ""
        else:
            if research:
                row_research = f"${research.get('avg_sold_price', 0):.2f}  ({research.get('listings_found', 0)} listings)"
            else:
                row_research = "—"
            row_listing = str(listing)[:40] if listing else "skipped / no result"

        print(f"{name:<12} {row_research:>14}   {row_listing}")


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = "all"
    filter_platform = None

    for arg in args:
        if arg in ("research", "listing"):
            mode = arg
        elif arg in PLATFORMS:
            filter_platform = arg

    asyncio.run(main(mode, filter_platform))
