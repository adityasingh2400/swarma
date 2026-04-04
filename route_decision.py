"""Route decision — pure scoring function, no browser, no LLM.
Extracted from v1 backend/agents/route_decider_agent.py:38-45.
Weights: 45% value, 25% confidence, 15% effort, 15% speed."""
from __future__ import annotations

from contracts import RouteDecision
from models.item_card import ItemCard

_EFFORT_SCORES = {"minimal": 1.0, "low": 0.85, "moderate": 0.65, "high": 0.4}
_SPEED_SCORES = {"instant": 1.0, "days": 0.9, "week": 0.7, "weeks": 0.45, "month_plus": 0.2}

# Default assumptions per platform when research doesn't provide these
_PLATFORM_EFFORT = {
    "ebay": "moderate",
    "facebook": "low",
    "mercari": "moderate",
    "depop": "moderate",
}
_PLATFORM_SPEED = {
    "ebay": "week",
    "facebook": "days",
    "mercari": "week",
    "depop": "weeks",
}


def _score_platform(platform: str, research: dict) -> float:
    """Score a single platform from its research results.
    Research dict expected keys: avg_sold_price, listings_found, confidence (optional).
    """
    avg_price = research.get("avg_sold_price", 0.0)
    listings_found = research.get("listings_found", 0)

    # Value: normalize to 0-1 range (cap at $2000 for normalization)
    value_norm = min(avg_price / 2000.0, 1.0) if avg_price > 0 else 0.0

    # Confidence: based on how many comps found
    if listings_found >= 10:
        confidence = 0.95
    elif listings_found >= 5:
        confidence = 0.8
    elif listings_found >= 2:
        confidence = 0.6
    elif listings_found >= 1:
        confidence = 0.4
    else:
        confidence = 0.1

    # Override with explicit confidence if provided
    confidence = research.get("confidence", confidence)

    effort_s = _EFFORT_SCORES.get(_PLATFORM_EFFORT.get(platform, "moderate"), 0.5)
    speed_s = _SPEED_SCORES.get(_PLATFORM_SPEED.get(platform, "week"), 0.5)

    return value_norm * 0.45 + confidence * 0.25 + effort_s * 0.15 + speed_s * 0.15


def route_decision(item: ItemCard, research: dict[str, dict]) -> RouteDecision:
    """Score each platform from parsed research, return top 3-4.

    Args:
        item: The item being routed.
        research: {"ebay": {"avg_sold_price": 799, "listings_found": 12}, ...}

    Returns:
        RouteDecision with ranked platforms, recommended prices, and raw scores.
    """
    scores: dict[str, float] = {}
    prices: dict[str, float] = {}

    for platform, data in research.items():
        if isinstance(data, Exception) or not data:
            continue
        scores[platform] = _score_platform(platform, data)
        prices[platform] = data.get("avg_sold_price", 0.0)

    # Sort by score descending, take top 3-4
    ranked = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
    top_platforms = ranked[:4] if len(ranked) > 3 else ranked

    return RouteDecision(
        item_id=item.item_id,
        platforms=top_platforms,
        prices={p: prices.get(p, 0.0) for p in top_platforms},
        scores={p: scores[p] for p in top_platforms},
    )
