from __future__ import annotations

import hashlib

from uagents import Agent, Context, Protocol

from backend.config import settings
from backend.models.item_card import ItemCard
from backend.models.route_bid import (
    EffortLevel,
    RepairCandidate,
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

repair_proto = Protocol(name="repair_roi_advisor", version="0.1.0")


def _estimate_as_is_value(item: ItemCard) -> float:
    seed_val = int(hashlib.md5(item.name_guess.encode()).hexdigest()[:8], 16)
    base = 30 + (seed_val % 470)

    major = sum(1 for d in item.all_defects if d.severity == "major")
    moderate = sum(1 for d in item.all_defects if d.severity == "moderate")
    discount = 1.0 - (major * 0.25 + moderate * 0.10)
    return round(max(base * max(discount, 0.2), 10), 2)


def _estimate_post_repair_value(item: ItemCard, as_is: float) -> float:
    if not item.has_defects:
        return as_is
    has_major = any(d.severity == "major" for d in item.all_defects)
    boost = 1.6 if has_major else 1.35
    return round(as_is * boost, 2)


@repair_proto.on_message(model=RouteBidRequest, replies={RouteBidResponse})
async def handle_route_bid(ctx: Context, sender: str, msg: RouteBidRequest):
    ctx.logger.info(f"Evaluating repair ROI for job {msg.job_id}")
    item = ItemCard.model_validate_json(msg.item_card_json)

    if not item.has_defects:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.REPAIR_THEN_SELL,
            viable=False,
            confidence=0.95,
            explanation="No defects detected — repair not applicable",
        )
        await ctx.send(
            sender,
            RouteBidResponse(
                job_id=msg.job_id,
                item_id=item.item_id,
                route_type=RouteType.REPAIR_THEN_SELL.value,
                bid_json=bid.model_dump_json(),
            ),
        )
        return

    repair_parts: list[RepairCandidate] = []
    try:
        from backend.services.amazon_api import AmazonService

        amazon_svc = AmazonService()
        for defect in item.all_defects:
            query = f"{item.name_guess} {defect.description} replacement part"
            parts = await amazon_svc.search_parts(query)
            repair_parts.extend(parts)
    except Exception as e:
        ctx.logger.warning(f"Amazon parts search failed: {e}")

    repair_cost = sum(p.part_price for p in repair_parts) if repair_parts else 15.0
    as_is_val = msg.as_is_value if msg.as_is_value > 0 else _estimate_as_is_value(item)
    post_repair_val = _estimate_post_repair_value(item, as_is_val)
    net_gain = post_repair_val - as_is_val - repair_cost

    viable = net_gain > 10.0
    has_major = any(d.severity == "major" for d in item.all_defects)
    effort = EffortLevel.HIGH if has_major else EffortLevel.MODERATE

    bid = RouteBid(
        item_id=item.item_id,
        route_type=RouteType.REPAIR_THEN_SELL,
        viable=viable,
        estimated_value=post_repair_val,
        effort=effort,
        speed=SpeedEstimate.WEEKS,
        confidence=0.55 if repair_parts else 0.3,
        explanation=(
            f"Repair ${repair_cost:.2f} | as-is ${as_is_val:.2f} → "
            f"post-repair ${post_repair_val:.2f} | net gain ${net_gain:.2f}"
        ),
        repair_candidates=repair_parts,
        as_is_value=as_is_val,
        post_repair_value=post_repair_val,
        repair_cost=repair_cost,
        net_gain_unlocked=net_gain,
    )

    await ctx.send(
        sender,
        RouteBidResponse(
            job_id=msg.job_id,
            item_id=item.item_id,
            route_type=RouteType.REPAIR_THEN_SELL.value,
            bid_json=bid.model_dump_json(),
        ),
    )


@repair_proto.on_message(model=DelegationRequest, replies={DelegationResponse})
async def handle_delegation(ctx: Context, sender: str, msg: DelegationRequest):
    ctx.logger.info(f"Delegation from {msg.from_agent} for item {msg.item_id}: {msg.reason}")
    item = ItemCard.model_validate_json(msg.payload_json)

    if not item.has_defects:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.REPAIR_THEN_SELL,
            viable=False,
            confidence=0.95,
            explanation="No defects detected — repair not applicable",
        )
        await ctx.send(sender, DelegationResponse(
            from_agent="repair_roi_advisor_agent",
            job_id=msg.job_id,
            item_id=msg.item_id,
            result_json=bid.model_dump_json(),
            confidence=bid.confidence,
        ))
        return

    repair_parts: list[RepairCandidate] = []
    try:
        from backend.services.amazon_api import AmazonService
        amazon_svc = AmazonService()
        for defect in item.all_defects:
            query = f"{item.name_guess} {defect.description} replacement part"
            parts = await amazon_svc.search_parts(query)
            repair_parts.extend(parts)
    except Exception as e:
        ctx.logger.warning(f"Amazon parts search failed: {e}")

    repair_cost = sum(p.part_price for p in repair_parts) if repair_parts else 15.0
    as_is_val = _estimate_as_is_value(item)
    post_repair_val = _estimate_post_repair_value(item, as_is_val)
    net_gain = post_repair_val - as_is_val - repair_cost

    viable = net_gain > 10.0
    has_major = any(d.severity == "major" for d in item.all_defects)
    effort = EffortLevel.HIGH if has_major else EffortLevel.MODERATE

    bid = RouteBid(
        item_id=item.item_id,
        route_type=RouteType.REPAIR_THEN_SELL,
        viable=viable,
        estimated_value=post_repair_val,
        effort=effort,
        speed=SpeedEstimate.WEEKS,
        confidence=0.55 if repair_parts else 0.3,
        explanation=(
            f"Repair ${repair_cost:.2f} | as-is ${as_is_val:.2f} → "
            f"post-repair ${post_repair_val:.2f} | net gain ${net_gain:.2f}"
        ),
        repair_candidates=repair_parts,
        as_is_value=as_is_val,
        post_repair_value=post_repair_val,
        repair_cost=repair_cost,
        net_gain_unlocked=net_gain,
    )

    await ctx.send(sender, DelegationResponse(
        from_agent="repair_roi_advisor_agent",
        job_id=msg.job_id,
        item_id=msg.item_id,
        result_json=bid.model_dump_json(),
        confidence=bid.confidence,
    ))


def create_repair_roi_advisor_agent() -> Agent:
    agent = Agent(
        name="repair_roi_advisor_agent",
        seed=settings.repair_roi_agent_seed,
        port=8105,
        network="testnet",
    )
    agent.include(repair_proto)
    return agent
