"""Live integration tests for all playbook research and listing methods.

Each test spins up a real browser-use agent using the same pattern as the
orchestrator. Research tests navigate, extract prices, and assert on parsed
output. Listing tests navigate to the listing creation page and attempt to
fill the form with hardcoded preset values.

Run a single test:
    python -m pytest tests/test_playbooks_live.py::test_ebay_research -s -v

Run all research tests:
    python -m pytest tests/test_playbooks_live.py -k research -s -v

Run all listing tests (require logged-in cookie files):
    python -m pytest tests/test_playbooks_live.py -k listing -s -v

Requirements:
    - GEMINI_API_KEY in .env (or env var) for the LLM
    - Cookie files in ./auth/ for listing tests (ebay, facebook, mercari, depop)
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Make sure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from browser_use import Agent, BrowserProfile

from config import settings
from models.item_card import DefectSignal, ItemCard, ItemCategory
from models.listing_package import ListingImage, ListingPackage
from playbooks.amazon import AmazonPlaybook
from playbooks.depop import DepopPlaybook

from playbooks.ebay import EbayPlaybook
from playbooks.facebook import FacebookPlaybook
from playbooks.mercari import MercariPlaybook


# ---------------------------------------------------------------------------
# Hardcoded preset item + package used for all tests
# ---------------------------------------------------------------------------

PRESET_ITEM = ItemCard(
    item_id="live_test_001",
    name_guess="iPhone 13 Pro 256GB",
    category=ItemCategory.ELECTRONICS,
    visible_defects=[
        DefectSignal(description="small scratch on back glass", source="visual", severity="minor"),
    ],
    accessories_included=["original charger", "box"],
    confidence=0.92,
)

PRESET_IMAGES = [
    ListingImage(path="./data/test_images/hero.jpg", role="hero"),
    ListingImage(path="./data/test_images/defect.jpg", role="defect_proof"),
    ListingImage(path="./data/test_images/spec.jpg", role="spec_card"),
    ListingImage(path="./data/test_images/side1.jpg", role="secondary"),
    ListingImage(path="./data/test_images/side2.jpg", role="secondary"),
    ListingImage(path="./data/test_images/back.jpg", role="secondary"),
]

PRESET_PACKAGE = ListingPackage(
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
    images=PRESET_IMAGES,
)


# ---------------------------------------------------------------------------
# Agent builder — mirrors orchestrator._build_agent / _make_llm / _make_profile
# ---------------------------------------------------------------------------

def _make_llm():
    from browser_use import ChatBrowserUse
    return ChatBrowserUse(api_key=settings.browser_use_api_key)


def _make_profile(platform: str, headless: bool = False) -> BrowserProfile:
    """Build a BrowserProfile. Uses cookies if available, always runs headed
    so you can watch what's happening."""
    storage = settings.storage_state_map.get(platform)
    return BrowserProfile(
        storage_state=storage,
        headless=headless,
        minimum_wait_page_load_time=0.5,
        wait_between_actions=0.3,
    )


def _collect_steps(steps: list) -> None:
    """Callback that prints each step as it happens."""
    def callback(state, model_output, step: int):
        url = getattr(state, "url", "")
        goal = ""
        if model_output and hasattr(model_output, "current_state"):
            goal = getattr(model_output.current_state, "next_goal", "")
        print(f"  step {step:02d} | {url[:80]}")
        if goal:
            print(f"           goal: {goal[:120]}")
    steps.append(callback)


async def _run_research(playbook, item: ItemCard, max_steps: int = 8) -> dict:
    """Spin up a research agent for the given playbook and return parsed result."""
    task_str, initial_actions = playbook.research_task(item)
    profile = _make_profile(playbook.platform)

    steps_log: list = []
    _collect_steps(steps_log)

    agent = Agent(
        task=task_str,
        llm=_make_llm(),
        browser_profile=profile,
        flash_mode=True,
        max_actions_per_step=4,
        use_vision=False,
        initial_actions=initial_actions,
        register_new_step_callback=steps_log[0],
    )

    print(f"\n[{playbook.platform.upper()} RESEARCH] Starting agent...")
    print(f"  Task: {task_str[:200]}")
    t0 = time.time()
    history = await agent.run(max_steps=max_steps)
    elapsed = time.time() - t0

    raw = history.final_result() if history.is_done() else None
    print(f"  Raw result: {raw}")
    print(f"  Duration: {elapsed:.1f}s  |  Steps: {history.number_of_steps()}")

    parsed = playbook.parse_research(raw)
    print(f"  Parsed: {json.dumps(parsed, indent=2)}")
    return parsed


async def _run_listing(playbook, item: ItemCard, package: ListingPackage,
                       max_steps: int = 30) -> str | None:
    """Spin up a listing agent for the given playbook and return the final result text."""
    task_str, initial_actions = playbook.listing_task(item, package)
    profile = _make_profile(playbook.platform)

    steps_log: list = []
    _collect_steps(steps_log)

    agent = Agent(
        task=task_str,
        llm=_make_llm(),
        browser_profile=profile,
        flash_mode=True,
        max_actions_per_step=4,
        use_vision="auto",
        initial_actions=initial_actions,
        register_new_step_callback=steps_log[0],
    )

    print(f"\n[{playbook.platform.upper()} LISTING] Starting agent...")
    print(f"  Task preview: {task_str[:300]}")
    t0 = time.time()
    history = await agent.run(max_steps=max_steps)
    elapsed = time.time() - t0

    result = history.final_result() if history.is_done() else None
    print(f"  Result: {result}")
    print(f"  Duration: {elapsed:.1f}s  |  Steps: {history.number_of_steps()}")
    return result


# ---------------------------------------------------------------------------
# Helper to run async tests without pytest-asyncio
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# eBay
# ---------------------------------------------------------------------------

def test_ebay_research():
    pb = EbayPlaybook()
    result = run(_run_research(pb, PRESET_ITEM))
    assert "avg_sold_price" in result
    assert "listings_found" in result
    assert result["price_type"] == "sold"
    assert isinstance(result["avg_sold_price"], (int, float))
    print(f"\n  avg_sold_price={result['avg_sold_price']}  listings_found={result['listings_found']}")


def test_ebay_listing():
    pb = EbayPlaybook()
    result = run(_run_listing(pb, PRESET_ITEM, PRESET_PACKAGE))
    # Either returns a listing URL or a descriptive completion message
    assert result is not None, "Agent returned no result"
    print(f"\n  Listing result: {result}")


# ---------------------------------------------------------------------------
# Facebook Marketplace
# ---------------------------------------------------------------------------

def test_facebook_research():
    pb = FacebookPlaybook()
    result = run(_run_research(pb, PRESET_ITEM))
    assert "avg_sold_price" in result
    assert result["price_type"] == "active"
    assert isinstance(result["avg_sold_price"], (int, float))
    print(f"\n  avg_sold_price={result['avg_sold_price']}  listings_found={result['listings_found']}")


def test_facebook_listing():
    pb = FacebookPlaybook()
    result = run(_run_listing(pb, PRESET_ITEM, PRESET_PACKAGE))
    assert result is not None, "Agent returned no result"
    print(f"\n  Listing result: {result}")


# ---------------------------------------------------------------------------
# Mercari
# ---------------------------------------------------------------------------

def test_mercari_research():
    pb = MercariPlaybook()
    result = run(_run_research(pb, PRESET_ITEM))
    assert "avg_sold_price" in result
    assert result["price_type"] == "sold"
    assert isinstance(result["avg_sold_price"], (int, float))
    print(f"\n  avg_sold_price={result['avg_sold_price']}  listings_found={result['listings_found']}")


def test_mercari_listing():
    pb = MercariPlaybook()
    result = run(_run_listing(pb, PRESET_ITEM, PRESET_PACKAGE))
    assert result is not None, "Agent returned no result"
    print(f"\n  Listing result: {result}")


# ---------------------------------------------------------------------------
# Depop
# ---------------------------------------------------------------------------

PRESET_CLOTHING_ITEM = ItemCard(
    item_id="live_test_002",
    name_guess="Levi's 501 Jeans 32x32",
    category=ItemCategory.CLOTHING,
    confidence=0.88,
)

PRESET_CLOTHING_PACKAGE = ListingPackage(
    item_id="live_test_002",
    title="Levi's 501 Original Fit Jeans 32x32 Medium Wash",
    description=(
        "Classic Levi's 501 original fit jeans. Size 32x32, medium wash.\n\n"
        "Condition: Good. Light fading consistent with wear, no rips or stains.\n\n"
        "Ships USPS First Class."
    ),
    price_strategy=45.00,
    images=PRESET_IMAGES,
)


def test_depop_research():
    pb = DepopPlaybook()
    result = run(_run_research(pb, PRESET_CLOTHING_ITEM))
    assert "avg_sold_price" in result
    assert result["price_type"] == "active"
    assert isinstance(result["avg_sold_price"], (int, float))
    print(f"\n  avg_sold_price={result['avg_sold_price']}  listings_found={result['listings_found']}")


def test_depop_listing():
    pb = DepopPlaybook()
    result = run(_run_listing(pb, PRESET_CLOTHING_ITEM, PRESET_CLOTHING_PACKAGE))
    assert result is not None, "Agent returned no result"
    print(f"\n  Listing result: {result}")


# ---------------------------------------------------------------------------
# Amazon (research-only)
# ---------------------------------------------------------------------------

def test_amazon_research():
    pb = AmazonPlaybook()
    result = run(_run_research(pb, PRESET_ITEM, max_steps=6))
    assert "parts" in result or "avg_sold_price" in result
    print(f"\n  Amazon research result: {json.dumps(result, indent=2)}")


# ---------------------------------------------------------------------------
# All platforms research in parallel (mirrors the orchestrator pipeline)
# ---------------------------------------------------------------------------

def test_all_research_parallel():
    """Run all 5 platform research agents concurrently and print a summary table."""

    async def run_all():
        item = PRESET_ITEM
        playbooks = [
            EbayPlaybook(),
            FacebookPlaybook(),
            MercariPlaybook(),
            DepopPlaybook(),
            AmazonPlaybook(),
        ]
        tasks = [_run_research(pb, item, max_steps=8) for pb in playbooks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return playbooks, results

    playbooks, results = run(run_all())

    print("\n\n=== RESEARCH SUMMARY ===")
    print(f"{'Platform':<12} {'avg_price':>10} {'listings':>10} {'price_type':<12} {'status':<10}")
    print("-" * 58)
    for pb, res in zip(playbooks, results):
        if isinstance(res, Exception):
            print(f"{pb.platform:<12} {'ERROR':>10}  {str(res)[:40]}")
        else:
            listings = res.get('listings_found', 0)
            listings = listings if listings is not None else 0
            print(
                f"{pb.platform:<12} "
                f"{res.get('avg_sold_price', 0):>10.2f} "
                f"{listings!s:>10} "
                f"{res.get('price_type', '?'):<12} "
                f"{'ok':<10}"
            )

    # At least one platform should succeed
    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) > 0, "All research agents failed"
