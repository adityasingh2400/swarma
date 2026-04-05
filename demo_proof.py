"""Proof of concept — agent fills in fields on each marketplace.
Does NOT submit/post anything. Just demonstrates we can interact with the forms."""
import asyncio
import base64
import os
import time

from browser_use import Agent, BrowserProfile, ChatBrowserUse

OUTPUT_DIR = "/tmp/swarma-proof"
os.makedirs(OUTPUT_DIR, exist_ok=True)

DEMOS = [
    {
        "name": "ebay",
        "url": "https://www.ebay.com/sell/create",
        "task": (
            "You are logged into eBay. Do these steps:\n"
            "1. Click 'List an item' if you see it\n"
            "2. In the search field labeled 'Tell us what you're selling', type 'iPhone 15 Pro 256GB' and press Enter\n"
            "3. If you see product suggestions, click the first one that matches iPhone 15 Pro\n"
            "4. If a selection wizard appears (Brand, Model, etc.), fill it out for an iPhone 15 Pro, Unlocked, 256GB, any color, Used condition\n"
            "5. Once you reach the actual listing form with Title/Price/Description fields, STOP. Do NOT click 'List it'.\n"
            "6. Call done and report what fields you see on the listing form."
        ),
    },
    {
        "name": "facebook",
        "url": "https://www.facebook.com/marketplace/create/item",
        "task": (
            "You are logged into Facebook Marketplace's create item page. Do these steps:\n"
            "1. In the 'Title' field, type: 'iPhone 15 Pro 256GB Unlocked'\n"
            "2. In the 'Price' field, type: '475'\n"
            "3. STOP here. Do NOT click 'Next' or submit. Do NOT fill any other fields.\n"
            "4. Call done and confirm you filled Title and Price."
        ),
    },
    {
        "name": "depop",
        "url": "https://www.depop.com/products/create/",
        "task": (
            "You are logged into Depop's create listing page. Do these steps:\n"
            "1. Find the Description text area and type: 'iPhone 15 Pro 256GB Unlocked Like New'\n"
            "2. STOP here. Do NOT click 'Continue' or submit. Do NOT fill other fields.\n"
            "3. Call done and confirm you filled the description."
        ),
    },
]


async def run_demo(demo):
    name = demo["name"]
    print(f"\n{'='*50}")
    print(f"  DEMO: {name.upper()}")
    print(f"{'='*50}")

    def step_cb(state, model_output, step):
        screenshot = getattr(state, "screenshot", None)
        if screenshot:
            fpath = os.path.join(OUTPUT_DIR, f"{name}_step{step}.png")
            with open(fpath, "wb") as f:
                f.write(base64.b64decode(screenshot))
            print(f"  📸 Step {step} screenshot saved")
        if model_output and hasattr(model_output, "current_state"):
            mem = getattr(model_output.current_state, "memory", "")[:100]
            if mem:
                print(f"  🧠 Step {step}: {mem}")

    profile = BrowserProfile(
        cdp_url="http://localhost:9222",
        minimum_wait_page_load_time=0.5,
        wait_between_actions=0.5,
    )

    agent = Agent(
        task=demo["task"],
        llm=ChatBrowserUse(),
        browser_profile=profile,
        flash_mode=False,
        use_vision=True,
        max_steps=20,
        initial_actions=[{"navigate": {"url": demo["url"]}}],
        register_new_step_callback=step_cb,
    )

    start = time.time()
    try:
        history = await agent.run()
        result = history.final_result() if history.is_done() else "No result"
        print(f"\n  ✅ {name} done in {time.time()-start:.1f}s")
        print(f"  📊 {str(result)[:150]}")
    except Exception as e:
        print(f"\n  ❌ {name} failed: {e}")


async def main():
    for demo in DEMOS:
        await run_demo(demo)
        print(f"\n  ⏳ Pausing 3s...")
        await asyncio.sleep(3)

    print(f"\n\n=== ALL DEMOS DONE ===")
    print(f"Screenshots: {OUTPUT_DIR}/")
    screenshots = sorted(os.listdir(OUTPUT_DIR))
    for s in screenshots:
        print(f"  {s}")


if __name__ == "__main__":
    asyncio.run(main())
