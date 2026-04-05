"""Custom extraction tools — platform-specific JavaScript that replaces the LLM extract tool.
Each function runs JS directly on the page DOM. ~100ms vs ~3s for an LLM extraction call.

Usage: register these on a Tools instance and pass to Agent.
The agent calls extract_prices in one step instead of using the slow extract tool."""
from __future__ import annotations

from browser_use import Tools, ActionResult, BrowserSession

# JavaScript snippets per marketplace that extract prices from the DOM

FACEBOOK_JS = """
(() => {
    const prices = [];
    // Scope to listing card links to avoid nav/ad price noise
    const listingLinks = document.querySelectorAll('a[href*="/marketplace/item/"]');
    for (const link of listingLinks) {
        for (const span of link.querySelectorAll('span')) {
            const text = span.textContent.trim();
            if (/^\\$[0-9,]+(\\.\\d{2})?$/.test(text)) {
                const price = parseFloat(text.replace(/[$,]/g, ''));
                if (price > 10 && price < 10000) { prices.push(price); break; }
            }
        }
    }
    // Fallback: if no listing links matched, scan all spans
    if (prices.length === 0) {
        for (const span of document.querySelectorAll('span')) {
            const text = span.textContent.trim();
            if (/^\\$[0-9,]+(\\.\\d{2})?$/.test(text) && prices.length < 15) {
                const price = parseFloat(text.replace(/[$,]/g, ''));
                if (price > 10 && price < 10000) prices.push(price);
            }
        }
    }
    const unique = [...new Set(prices)].slice(0, 10);
    const avg = unique.length > 0 ? unique.reduce((a,b) => a+b, 0) / unique.length : 0;
    return JSON.stringify({prices: unique, avg: Math.round(avg * 100) / 100, count: unique.length, total_listings: 0});
})()
"""

DEPOP_JS = """
(() => {
    const prices = [];
    const spans = document.querySelectorAll('span, p');
    for (const el of spans) {
        const text = el.textContent.trim();
        if (/^\\$[0-9,]+(\\.\\d{2})?$/.test(text) && prices.length < 10) {
            const price = parseFloat(text.replace(/[$,]/g, ''));
            if (price > 5 && price < 10000) prices.push(price);
        }
    }
    const unique = [...new Set(prices)].slice(0, 10);
    const avg = unique.length > 0 ? unique.reduce((a,b) => a+b, 0) / unique.length : 0;
    return JSON.stringify({prices: unique, avg: Math.round(avg * 100) / 100, count: unique.length, total_listings: 0});
})()
"""

PLATFORM_JS = {
    "facebook": FACEBOOK_JS,
    "depop": DEPOP_JS,
}


def get_extraction_js(platform: str) -> str | None:
    """Return the JavaScript extraction code for a platform, or None if unsupported."""
    return PLATFORM_JS.get(platform)


def make_initial_actions(platform: str, search_url: str) -> list[dict]:
    """Build initial_actions that navigate AND extract prices — zero LLM calls.

    Flow:
    1. Navigate to search URL (no LLM)
    2. Wait for DOM to settle (no LLM)
    3. Run JavaScript to extract prices (no LLM)
    Agent starts with extraction results already in page context.
    """
    js = PLATFORM_JS.get(platform)
    actions = [
        {"navigate": {"url": search_url}},
        {"wait": {"seconds": 2}},
    ]
    if js:
        actions.append({"evaluate": {"code": js}})
    return actions


def make_research_tools(platform: str) -> Tools | None:
    """No custom tools needed — we use the built-in evaluate action.
    Returns None so the agent uses default tools only."""
    return None
