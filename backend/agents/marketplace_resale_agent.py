from __future__ import annotations

import statistics

from uagents import Agent, Context, Protocol

from backend.config import settings
from backend.models.item_card import ItemCard
from backend.models.route_bid import (
    ComparableListing,
    EffortLevel,
    RouteBid,
    RouteType,
    SpeedEstimate,
)
from backend.protocols.messages import (
    DelegationRequest,
    DelegationResponse,
    RouteBidRequest,
    RouteBidResponse,
)

resale_proto = Protocol(name="marketplace_resale", version="0.1.0")

EBAY_FVF_RATE = 0.1312
SHIPPING_ESTIMATE = 8.50
CONDITION_DISCOUNTS = {"Like New": 1.0, "Good": 0.85, "Fair": 0.65}


def _build_search_query(item: ItemCard) -> str:
    parts = []
    if "brand" in item.likely_specs:
        parts.append(item.likely_specs["brand"])
    parts.append(item.name_guess)
    if "model" in item.likely_specs:
        parts.append(item.likely_specs["model"])
    return " ".join(parts).strip()


def _estimate_speed(item: ItemCard, avg_price: float) -> SpeedEstimate:
    if avg_price < 20:
        return SpeedEstimate.WEEKS
    fast_categories = {"electronics", "clothing", "accessories"}
    if item.category.value in fast_categories:
        return SpeedEstimate.WEEK
    return SpeedEstimate.WEEKS


@resale_proto.on_message(model=RouteBidRequest, replies={RouteBidResponse})
async def handle_route_bid(ctx: Context, sender: str, msg: RouteBidRequest):
    ctx.logger.info(f"Evaluating marketplace resale for job {msg.job_id}")
    item = ItemCard.model_validate_json(msg.item_card_json)

    query = _build_search_query(item)
    ctx.logger.info(f"Comp search query: {query}")

    comps: list[ComparableListing] = []

    try:
        from backend.services.gemini import GeminiService
        gemini_svc = GeminiService()
        comps = await gemini_svc.search_live_comps(
            item_name=query, category=item.category.value, condition=item.condition_label,
        )
    except Exception as e:
        ctx.logger.warning(f"Live comp search failed: {e}")

    prices = [c.price for c in comps if c.price > 0]
    if prices:
        prices.sort()
        if len(prices) >= 4:
            q1_idx = len(prices) // 4
            q3_idx = 3 * len(prices) // 4
            q1, q3 = prices[q1_idx], prices[q3_idx]
            iqr = q3 - q1
            prices = [p for p in prices if (q1 - 1.5 * iqr) <= p <= (q3 + 1.5 * iqr)]
        avg_price = statistics.mean(prices) if prices else 0.0
        median_price = statistics.median(prices) if prices else 0.0
        low_price = min(prices) if prices else 0.0
        high_price = max(prices) if prices else 0.0
    else:
        avg_price = median_price = low_price = high_price = 0.0

    cond_mult = CONDITION_DISCOUNTS.get(item.condition_label, 0.75)
    suggested_price = round(median_price * cond_mult, 2) if median_price else 0.0
    net_payout = round(
        max(suggested_price * (1 - EBAY_FVF_RATE) - SHIPPING_ESTIMATE, 0.0), 2
    )

    platforms_found = list({c.platform for c in comps})
    speed = _estimate_speed(item, avg_price) if comps else SpeedEstimate.WEEKS
    confidence = min(0.9, 0.3 + len(comps) * 0.1) if comps else 0.2
    viable = net_payout > 5.0

    bid = RouteBid(
        item_id=item.item_id,
        route_type=RouteType.SELL_AS_IS,
        viable=viable,
        estimated_value=net_payout,
        effort=EffortLevel.MODERATE,
        speed=speed,
        confidence=confidence,
        explanation=(
            f"Live search across {', '.join(platforms_found)}: "
            f"${suggested_price:.2f} → net ${net_payout:.2f} after fees. "
            f"{len(comps)} comps (median ${median_price:.2f}, "
            f"range ${low_price:.2f}–${high_price:.2f}). "
            f"Condition: {item.condition_label}."
        ),
        comparable_listings=comps,
        as_is_value=net_payout,
    )

    await ctx.send(
        sender,
        RouteBidResponse(
            job_id=msg.job_id,
            item_id=item.item_id,
            route_type=RouteType.SELL_AS_IS.value,
            bid_json=bid.model_dump_json(),
        ),
    )


@resale_proto.on_message(model=DelegationRequest, replies={DelegationResponse})
async def handle_delegation(ctx: Context, sender: str, msg: DelegationRequest):
    ctx.logger.info(f"Delegation from {msg.from_agent} for item {msg.item_id}: {msg.reason}")
    item = ItemCard.model_validate_json(msg.payload_json)

    query = _build_search_query(item)
    comps: list[ComparableListing] = []
    try:
        from backend.services.gemini import GeminiService
        gemini_svc = GeminiService()
        comps = await gemini_svc.search_live_comps(item_name=query, category=item.category.value)
    except Exception as e:
        ctx.logger.warning(f"Live comp search failed during delegation: {e}")

    prices = [c.price for c in comps if c.price > 0]
    if prices:
        prices.sort()
        if len(prices) >= 4:
            q1_idx = len(prices) // 4
            q3_idx = 3 * len(prices) // 4
            q1, q3 = prices[q1_idx], prices[q3_idx]
            iqr = q3 - q1
            prices = [p for p in prices if (q1 - 1.5 * iqr) <= p <= (q3 + 1.5 * iqr)]
        avg_price = statistics.mean(prices) if prices else 0.0
        median_price = statistics.median(prices) if prices else 0.0
    else:
        avg_price = median_price = 0.0

    cond_mult = CONDITION_DISCOUNTS.get(item.condition_label, 0.75)
    suggested_price = round(median_price * cond_mult, 2) if median_price else 0.0
    net_payout = round(
        max(suggested_price * (1 - EBAY_FVF_RATE) - SHIPPING_ESTIMATE, 0.0), 2
    )
    confidence = min(0.9, 0.3 + len(comps) * 0.1) if comps else 0.2

    bid = RouteBid(
        item_id=item.item_id,
        route_type=RouteType.SELL_AS_IS,
        viable=net_payout > 5.0,
        estimated_value=net_payout,
        effort=EffortLevel.MODERATE,
        speed=_estimate_speed(item, avg_price) if comps else SpeedEstimate.WEEKS,
        confidence=confidence,
        explanation=f"Live resale estimate: ${net_payout:.2f} net after fees ({len(comps)} comps)",
        comparable_listings=comps,
        as_is_value=net_payout,
    )

    await ctx.send(sender, DelegationResponse(
        from_agent="marketplace_resale_agent",
        job_id=msg.job_id,
        item_id=msg.item_id,
        result_json=bid.model_dump_json(),
        confidence=bid.confidence,
    ))


def create_marketplace_resale_agent() -> Agent:
    agent = Agent(
        name="marketplace_resale_agent",
        seed=settings.marketplace_resale_agent_seed,
        port=8104,
        network="testnet",
    )
    agent.include(resale_proto)
    return agent
