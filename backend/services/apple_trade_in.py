"""Apple Trade-In value lookup service.

Uses Apple's trade-in module API to get real-time trade-in values for
iPhones, and the static overlay pages for Macs and Watches.
Results are cached for 1 hour to avoid redundant requests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.request

logger = logging.getLogger(__name__)

_CACHE_TTL = 3600  # 1 hour

_caches: dict[str, dict] = {
    "iphone": {"data": None, "ts": 0},
    "mac": {"data": None, "ts": 0},
    "watch": {"data": None, "ts": 0},
}

# Apple's max value is for devices in "good condition" (powers on, works).
# We scale down for items with detected defects.
_CONDITION_MULT = {"Like New": 1.0, "Good": 0.85, "Fair": 0.50}

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "iphone": ["iphone"],
    "mac": ["macbook", "imac", "mac mini", "mac studio", "mac pro"],
    "watch": ["apple watch", "watch series", "watch ultra", "watch se"],
}

_APPLE_TRADE_IN_URL = "https://www.apple.com/shop/trade-in"


def _parse_price(s: str) -> float | None:
    m = re.search(r"\$[\d,]+", s)
    if m:
        return float(m.group().replace("$", "").replace(",", ""))
    return None


def _http_get(url: str, timeout: int = 8) -> str:
    """Blocking HTTP GET — called via asyncio.to_thread."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/html"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


# ── Fetchers ─────────────────────────────────────────────────────────


async def _load_iphone_values() -> dict[str, float]:
    """Fetch all iPhone models + max trade-in values from Apple's JSON API."""
    url = (
        "https://www.apple.com/shop/tradein-module"
        "?fae=true&cat=smartphone&bid=1&module=model"
    )
    try:
        raw = await asyncio.to_thread(_http_get, url)
        data = json.loads(raw)

        dims = (
            data.get("body", {})
            .get("moduleData", {})
            .get("dictionaries", {})
            .get("dimensions", {})
            .get("model", {})
        )
        models: dict[str, float] = {}
        for _key, info in dims.items():
            name = info.get("modelName") or info.get("text", "")
            max_val = info.get("maxValue", "")
            if name and max_val:
                price = _parse_price(max_val)
                if price:
                    models[name] = price
        logger.info("Loaded %d iPhone trade-in values from Apple", len(models))
        return models
    except Exception as e:
        logger.warning("Failed to fetch iPhone trade-in values: %s", e)
        return {}


async def _load_overlay_values(category: str) -> dict[str, float]:
    """Fetch trade-in values from Apple's static HTML overlay tables."""
    url = (
        f"https://www.apple.com/shop/browse/overlay"
        f"/tradein_landing/{category}_values"
    )
    try:
        html = await asyncio.to_thread(_http_get, url)

        models: dict[str, float] = {}
        rows = re.findall(
            r"<tr>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>",
            html,
            re.DOTALL,
        )
        for name_html, val_html in rows:
            name = re.sub(r"<[^>]+>", "", name_html).replace("&nbsp;", " ").strip()
            price = _parse_price(val_html)
            if name and price:
                models[name] = price
        logger.info(
            "Loaded %d %s trade-in values from Apple overlay", len(models), category
        )
        return models
    except Exception as e:
        logger.warning("Failed to fetch %s overlay values: %s", category, e)
        return {}


# ── Cache layer ──────────────────────────────────────────────────────


async def _get_cached(category: str) -> dict[str, float]:
    cache = _caches.get(category)
    if not cache:
        return {}
    now = time.time()
    if cache["data"] is None or (now - cache["ts"]) > _CACHE_TTL:
        if category == "iphone":
            cache["data"] = await _load_iphone_values()
        else:
            cache["data"] = await _load_overlay_values(category)
        cache["ts"] = now
    return cache["data"] or {}


# ── Matching ─────────────────────────────────────────────────────────


def _detect_category(item_name: str) -> str | None:
    lower = item_name.lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return cat
    return None


def _best_match(
    item_name: str, models: dict[str, float]
) -> tuple[str, float] | None:
    """Find the best matching Apple model by token overlap + containment."""
    lower = item_name.lower()
    best: tuple[str, float, float] | None = None

    for model_name, price in models.items():
        model_lower = model_name.lower()

        if model_lower in lower:
            # Full model name found inside the item name — strong match.
            # Prefer longer (more specific) model names.
            score = 1.0 + len(model_lower) / 100.0
        elif lower in model_lower:
            score = 0.8 + len(lower) / 100.0
        else:
            item_tokens = set(lower.split())
            model_tokens = set(model_lower.split())
            if not model_tokens:
                continue
            overlap = item_tokens & model_tokens
            score = len(overlap) / len(model_tokens)

        if best is None or score > best[2]:
            best = (model_name, price, score)

    if best and best[2] >= 0.5:
        return (best[0], best[1])
    return None


# ── Public API ───────────────────────────────────────────────────────


async def get_apple_trade_in(
    item_name: str,
    condition_label: str = "Like New",
) -> dict | None:
    """Look up Apple trade-in value for an item.

    Returns dict with keys:
        matched_model, max_value, estimated_payout, condition, category, url
    or None if the item isn't eligible for Apple Trade In.
    """
    category = _detect_category(item_name)
    if not category:
        return None

    models = await _get_cached(category)
    if not models:
        return None

    match = _best_match(item_name, models)
    if not match:
        return None

    matched_model, max_value = match
    cond_mult = _CONDITION_MULT.get(condition_label, 0.85)
    payout = round(max_value * cond_mult, 2)

    return {
        "matched_model": matched_model,
        "max_value": max_value,
        "estimated_payout": payout,
        "condition": condition_label,
        "category": category,
        "url": _APPLE_TRADE_IN_URL,
    }
