"""Route Mapper — crawls marketplace listing/research flows step by step.
Takes a screenshot AND captures the DOM state at every page.
Runs one marketplace at a time, sequentially. No rushing.

Output: /tmp/swarma-routes/{platform}/{step_N}_screenshot.png + {step_N}_dom.txt
"""
import asyncio
import base64
import json
import os
import time

from browser_use import Agent, BrowserProfile, ChatBrowserUse

OUTPUT_DIR = "/tmp/swarma-routes"


# --- Routes to map ---
# Each route is a sequence of pages to visit and document.
# The agent documents what it sees, does NOT fill anything in.

ROUTES = {
    "ebay_research": {
        "description": "eBay sold listings search results",
        "start_url": "https://www.ebay.com/sch/i.html?_nkw=iPhone+15+Pro+256GB&LH_Complete=1&LH_Sold=1",
        "task": (
            "You are on an eBay search results page showing sold listings. "
            "Your job is to DOCUMENT this page — do NOT click or modify anything. "
            "Describe in detail:\n"
            "1. Where is the total result count displayed? What text surrounds it?\n"
            "2. How are individual listings structured? What info does each listing show?\n"
            "3. Where exactly are the SOLD PRICES displayed for each listing? "
            "What HTML-visible text format are they in (e.g., '$499.99')?\n"
            "4. List the first 5 listings with their exact titles and prices as shown.\n"
            "5. Are there any filters, sorting options, or navigation elements visible?\n"
            "6. Any popups, banners, or overlays blocking content?\n"
            "Use the extract tool to get this information from the page content."
        ),
    },
    "ebay_listing": {
        "description": "eBay listing creation flow",
        "start_url": "https://www.ebay.com/sell/create",
        "task": (
            "You are on eBay's listing creation page. "
            "Your job is to DOCUMENT every field and button on this page — do NOT fill anything in. "
            "Describe in detail:\n"
            "1. What is the URL you're on?\n"
            "2. List EVERY input field, dropdown, button, and interactive element visible.\n"
            "3. For each field: what is its visible LABEL text? Is it required?\n"
            "4. What is the order of fields from top to bottom?\n"
            "5. Are there sections/groups? What are they called?\n"
            "6. What does the submit/publish button say?\n"
            "7. Any popups, login prompts, or blockers?\n"
            "8. Any dropdowns — what options are visible?\n"
            "Use the extract tool to capture all field labels and structure from the page."
        ),
    },
    "mercari_research": {
        "description": "Mercari search results",
        "start_url": "https://www.mercari.com/search/?keyword=iPhone+15+Pro+256GB",
        "task": (
            "You are on Mercari search results. "
            "DOCUMENT this page — do NOT click or modify anything.\n"
            "1. Where is the total result count?\n"
            "2. How are listings structured? What does each listing card show?\n"
            "3. Where are prices displayed? What text format?\n"
            "4. List the first 5 listings with exact titles and prices.\n"
            "5. Any filters, sorting, or navigation?\n"
            "6. Any popups or overlays?\n"
            "Use extract to capture this."
        ),
    },
    "mercari_listing": {
        "description": "Mercari listing creation flow",
        "start_url": "https://www.mercari.com/sell/",
        "task": (
            "You are on Mercari's listing creation page. "
            "DOCUMENT every field and button — do NOT fill anything in.\n"
            "1. What URL are you on?\n"
            "2. List EVERY input field, dropdown, button, and interactive element.\n"
            "3. For each field: visible LABEL text, required or optional?\n"
            "4. Order of fields top to bottom.\n"
            "5. Sections/groups and their names.\n"
            "6. Submit button text.\n"
            "7. Any login prompts, popups, blockers?\n"
            "8. Photo upload area — how does it work?\n"
            "Use extract to capture all structure."
        ),
    },
    "facebook_research": {
        "description": "Facebook Marketplace search results",
        "start_url": "https://www.facebook.com/marketplace/search/?query=iPhone%2015%20Pro%20256GB",
        "task": (
            "You are on Facebook Marketplace search results. "
            "DOCUMENT this page — do NOT click or modify anything.\n"
            "1. Where is the total result count (if shown)?\n"
            "2. How are listing cards structured?\n"
            "3. Where are prices displayed? Format?\n"
            "4. List the first 5 listings with titles and prices.\n"
            "5. Any filters or sorting?\n"
            "6. Any login prompts, popups, or blockers?\n"
            "Use extract to capture this."
        ),
    },
    "facebook_listing": {
        "description": "Facebook Marketplace listing creation",
        "start_url": "https://www.facebook.com/marketplace/create/item",
        "task": (
            "You are on Facebook Marketplace's item creation page. "
            "DOCUMENT every field and button — do NOT fill anything in.\n"
            "1. What URL are you on?\n"
            "2. List EVERY input field, dropdown, button, interactive element.\n"
            "3. Visible LABEL text for each field.\n"
            "4. Order top to bottom.\n"
            "5. Photo upload area.\n"
            "6. Submit button text.\n"
            "7. Login prompts, popups, location prompts?\n"
            "Use extract to capture all structure."
        ),
    },
    "depop_research": {
        "description": "Depop search results",
        "start_url": "https://www.depop.com/search/?q=iPhone%2015%20Pro%20256GB",
        "task": (
            "You are on Depop search results. "
            "DOCUMENT this page — do NOT click or modify anything.\n"
            "1. How are listings displayed?\n"
            "2. Where are prices? Format?\n"
            "3. First 5 listings with titles and prices.\n"
            "4. Any filters, sorting, popups?\n"
            "Use extract to capture this."
        ),
    },
    "depop_listing": {
        "description": "Depop listing creation",
        "start_url": "https://www.depop.com/products/create/",
        "task": (
            "You are on Depop's listing creation page. "
            "DOCUMENT every field and button — do NOT fill anything in.\n"
            "1. URL?\n"
            "2. List ALL fields, dropdowns, buttons.\n"
            "3. Visible labels for each.\n"
            "4. Order top to bottom.\n"
            "5. Photo upload area.\n"
            "6. Submit button text.\n"
            "7. Login prompts or blockers?\n"
            "Use extract to capture all structure."
        ),
    },
}


async def map_single_route(name: str, route: dict):
    """Map a single route — navigate, screenshot, capture DOM, document."""
    route_dir = os.path.join(OUTPUT_DIR, name)
    os.makedirs(route_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  MAPPING: {name}")
    print(f"  {route['description']}")
    print(f"  URL: {route['start_url']}")
    print(f"  Output: {route_dir}/")
    print(f"{'='*60}\n")

    screenshots = []
    dom_states = []

    def step_callback(state, model_output, step: int):
        # Save screenshot
        screenshot = getattr(state, "screenshot", None)
        if screenshot:
            fpath = os.path.join(route_dir, f"step_{step}_screenshot.png")
            img_data = base64.b64decode(screenshot)
            with open(fpath, "wb") as f:
                f.write(img_data)
            screenshots.append(fpath)
            print(f"  📸 Step {step} screenshot saved ({len(img_data)//1024}KB)")

        # Save DOM/page state info
        dom_info = {
            "step": step,
            "url": getattr(state, "url", ""),
            "title": getattr(state, "title", ""),
        }
        if model_output and hasattr(model_output, "current_state"):
            cs = model_output.current_state
            dom_info["page_summary"] = getattr(cs, "page_summary", "")
            dom_info["memory"] = getattr(cs, "memory", "")
            dom_info["next_goal"] = getattr(cs, "next_goal", "")
        if model_output and hasattr(model_output, "action"):
            dom_info["actions"] = [
                a.model_dump(exclude_unset=True) for a in model_output.action
            ]

        fpath = os.path.join(route_dir, f"step_{step}_state.json")
        with open(fpath, "w") as f:
            json.dump(dom_info, f, indent=2, default=str)
        dom_states.append(fpath)

        # Print agent's thinking
        if model_output and hasattr(model_output, "current_state"):
            memory = getattr(model_output.current_state, "memory", "")
            if memory:
                print(f"  🧠 Step {step}: {memory[:120]}")

    # Connect to the user's authenticated Chrome via CDP
    print(f"  🔑 Connecting to Chrome via CDP (localhost:9222)")

    profile = BrowserProfile(
        cdp_url="http://localhost:9222",
        minimum_wait_page_load_time=0.5,
        wait_between_actions=0.5,
    )

    agent = Agent(
        task=route["task"],
        llm=ChatBrowserUse(),
        browser_profile=profile,
        flash_mode=False,  # want FULL thinking for documentation
        use_vision=True,   # want visual understanding for accurate descriptions
        max_steps=10,
        initial_actions=[{"navigate": {"url": route["start_url"]}}],
        register_new_step_callback=step_callback,
    )

    start = time.time()
    try:
        history = await agent.run()
        result = history.final_result() if history.is_done() else "No result"
    except Exception as e:
        result = f"Error: {e}"

    elapsed = time.time() - start

    # Save final result
    result_path = os.path.join(route_dir, "result.txt")
    with open(result_path, "w") as f:
        f.write(f"Route: {name}\n")
        f.write(f"Description: {route['description']}\n")
        f.write(f"URL: {route['start_url']}\n")
        f.write(f"Time: {elapsed:.1f}s\n")
        f.write(f"Screenshots: {len(screenshots)}\n")
        f.write(f"Steps: {len(dom_states)}\n")
        f.write(f"\n{'='*60}\n")
        f.write(f"AGENT DOCUMENTATION:\n")
        f.write(f"{'='*60}\n\n")
        f.write(str(result))

    print(f"\n  ✅ {name} mapped in {elapsed:.1f}s")
    print(f"  📄 Result saved to {result_path}")
    print(f"  📸 {len(screenshots)} screenshots captured")

    return result


async def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Run routes ONE AT A TIME, sequentially
    route_order = [
        "ebay_research",
        "ebay_listing",
        "mercari_research",
        "mercari_listing",
        "facebook_research",
        "facebook_listing",
        "depop_research",
        "depop_listing",
    ]

    results = {}
    for name in route_order:
        route = ROUTES[name]
        result = await map_single_route(name, route)
        results[name] = result
        print(f"\n  ⏳ Pausing 3s before next route...")
        await asyncio.sleep(3)

    # Summary
    print(f"\n\n{'='*60}")
    print(f"  ALL ROUTES MAPPED")
    print(f"  Output: {OUTPUT_DIR}/")
    print(f"{'='*60}")
    for name in route_order:
        route_dir = os.path.join(OUTPUT_DIR, name)
        screenshots = [f for f in os.listdir(route_dir) if f.endswith(".png")]
        print(f"  {name}: {len(screenshots)} screenshots")
    print(f"\n  Next: read the result.txt files to build playbook recipes")


if __name__ == "__main__":
    asyncio.run(main())
