"""Custom extraction tools — platform-specific JavaScript that replaces the LLM extract tool.
Each function runs JS directly on the page DOM. ~100ms vs ~3s for an LLM extraction call.

Usage: register these on a Tools instance and pass to Agent.
The agent calls extract_prices in one step instead of using the slow extract tool."""
from __future__ import annotations

from browser_use import Tools, ActionResult, BrowserSession

# JavaScript snippets per marketplace that extract prices from the DOM
EBAY_SOLD_JS = """
(() => {
    const items = document.querySelectorAll('.s-item');
    const prices = [];
    for (let i = 0; i < Math.min(items.length, 10); i++) {
        const el = items[i];
        const priceEl = el.querySelector('.s-item__price .POSITIVE, .s-item__price span');
        if (priceEl) {
            const text = priceEl.textContent.replace(/[^0-9.]/g, '');
            const price = parseFloat(text);
            if (price > 0) prices.push(price);
        }
    }
    const totalEl = document.querySelector('.srp-controls__count-heading span, h1.srp-controls__count-heading');
    let total = 0;
    if (totalEl) {
        const m = totalEl.textContent.replace(/,/g, '').match(/([0-9]+)/);
        if (m) total = parseInt(m[1]);
    }
    const avg = prices.length > 0 ? prices.reduce((a,b) => a+b, 0) / prices.length : 0;
    return JSON.stringify({prices, avg: Math.round(avg * 100) / 100, count: prices.length, total_listings: total});
})()
"""

MERCARI_JS = """
(() => {
    const items = document.querySelectorAll('[data-testid="ItemCell"], [class*="ItemCell"]');
    const prices = [];
    // Try multiple selectors for price elements
    const allPriceEls = document.querySelectorAll('[data-testid="ItemPrice"], [class*="price"], [class*="Price"]');
    for (const el of allPriceEls) {
        const text = el.textContent.replace(/[^0-9.]/g, '');
        const price = parseFloat(text);
        if (price > 10 && price < 10000 && prices.length < 10) prices.push(price);
    }
    // Deduplicate (some elements may have both original and discounted price)
    const unique = [...new Set(prices)].slice(0, 10);
    const avg = unique.length > 0 ? unique.reduce((a,b) => a+b, 0) / unique.length : 0;
    return JSON.stringify({prices: unique, avg: Math.round(avg * 100) / 100, count: unique.length, total_listings: 0});
})()
"""

FACEBOOK_JS = """
(() => {
    const items = document.querySelectorAll('[class*="x1lliihq"]');
    const prices = [];
    // FB Marketplace uses spans with price text like "$400"
    const spans = document.querySelectorAll('span');
    for (const span of spans) {
        const text = span.textContent.trim();
        if (/^\\$[0-9,]+(\\.\\d{2})?$/.test(text) && prices.length < 10) {
            const price = parseFloat(text.replace(/[$,]/g, ''));
            if (price > 10 && price < 10000) prices.push(price);
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
    "ebay": EBAY_SOLD_JS,
    "mercari": MERCARI_JS,
    "facebook": FACEBOOK_JS,
    "depop": DEPOP_JS,
}


def get_extraction_js(platform: str) -> str:
    """Return the JavaScript extraction code for a platform."""
    return PLATFORM_JS.get(platform, FACEBOOK_JS)


def make_initial_actions(platform: str, search_url: str) -> list[dict]:
    """Build initial_actions that navigate AND extract prices — zero LLM calls.

    Flow:
    1. Navigate to search URL (no LLM)
    2. Run JavaScript to extract prices (no LLM)
    3. Agent starts with extraction results already available via evaluate
    """
    return [
        {"navigate": {"url": search_url}},
    ]


def make_research_tools(platform: str) -> Tools | None:
    """No custom tools needed — we use the built-in evaluate action.
    Returns None so the agent uses default tools only."""
    return None
