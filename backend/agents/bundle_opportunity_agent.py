from __future__ import annotations

from uagents import Agent, Context, Protocol

from backend.config import settings
from backend.models.item_card import ItemCard
from backend.models.route_bid import EffortLevel, RouteBid, RouteType, SpeedEstimate
from backend.protocols.messages import (
    DelegationRequest,
    DelegationResponse,
    RouteBidRequest,
    RouteBidResponse,
)
from backend.storage.store import store

bundle_proto = Protocol(name="bundle_opportunity", version="0.1.0")

_CATEGORY_AFFINITIES: dict[str, set[str]] = {
    "electronics": {"electronics", "accessories"},
    "clothing": {"clothing", "accessories"},
    "accessories": {"clothing", "electronics", "accessories"},
    "sports": {"sports", "clothing", "accessories"},
    "home": {"home"},
    "toys": {"toys"},
}
_STOPWORDS = frozenset({"the", "a", "an", "and", "or", "for", "with", "in", "of"})
BUNDLE_PREMIUM = 1.15
PER_ITEM_BASE_VALUE = 25.0


def _find_bundle_partners(item: ItemCard, all_items: list[ItemCard]) -> list[ItemCard]:
    affinities = _CATEGORY_AFFINITIES.get(item.category.value, set())
    name_tokens = set(item.name_guess.lower().split()) - _STOPWORDS
    partners: list[ItemCard] = []

    for other in all_items:
        if other.item_id == item.item_id:
            continue
        if other.category.value not in affinities:
            continue
        other_tokens = set(other.name_guess.lower().split()) - _STOPWORDS
        shared = name_tokens & other_tokens
        if shared or other.category.value == item.category.value:
            partners.append(other)

    return partners


@bundle_proto.on_message(model=RouteBidRequest, replies={RouteBidResponse})
async def handle_route_bid(ctx: Context, sender: str, msg: RouteBidRequest):
    ctx.logger.info(f"Evaluating bundle opportunity for job {msg.job_id}")
    item = ItemCard.model_validate_json(msg.item_card_json)

    all_items = store.get_items_for_job(msg.job_id)

    if len(all_items) < 2:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.BUNDLE_THEN_SELL,
            viable=False,
            confidence=0.95,
            explanation="Single item in job — bundling not possible",
        )
        await ctx.send(
            sender,
            RouteBidResponse(
                job_id=msg.job_id,
                item_id=item.item_id,
                route_type=RouteType.BUNDLE_THEN_SELL.value,
                bid_json=bid.model_dump_json(),
            ),
        )
        return

    partners = _find_bundle_partners(item, all_items)

    if not partners:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.BUNDLE_THEN_SELL,
            viable=False,
            confidence=0.8,
            explanation="No complementary items found for bundling",
        )
        await ctx.send(
            sender,
            RouteBidResponse(
                job_id=msg.job_id,
                item_id=item.item_id,
                route_type=RouteType.BUNDLE_THEN_SELL.value,
                bid_json=bid.model_dump_json(),
            ),
        )
        return

    bundled_ids = [item.item_id] + [p.item_id for p in partners]
    separate_total = PER_ITEM_BASE_VALUE * len(bundled_ids)
    combined_value = round(separate_total * BUNDLE_PREMIUM, 2)

    bid = RouteBid(
        item_id=item.item_id,
        route_type=RouteType.BUNDLE_THEN_SELL,
        viable=True,
        estimated_value=combined_value,
        effort=EffortLevel.MODERATE,
        speed=SpeedEstimate.WEEK,
        confidence=0.45,
        explanation=(
            f"Bundle {len(bundled_ids)} items: "
            f"separate ~${separate_total:.2f} vs bundled ~${combined_value:.2f} "
            f"({(BUNDLE_PREMIUM - 1) * 100:.0f}% premium)"
        ),
        bundled_item_ids=bundled_ids,
        separate_value=separate_total,
        combined_value=combined_value,
    )

    await ctx.send(
        sender,
        RouteBidResponse(
            job_id=msg.job_id,
            item_id=item.item_id,
            route_type=RouteType.BUNDLE_THEN_SELL.value,
            bid_json=bid.model_dump_json(),
        ),
    )


@bundle_proto.on_message(model=DelegationRequest, replies={DelegationResponse})
async def handle_delegation(ctx: Context, sender: str, msg: DelegationRequest):
    ctx.logger.info(f"Delegation from {msg.from_agent} for item {msg.item_id}: {msg.reason}")
    item = ItemCard.model_validate_json(msg.payload_json)

    all_items = store.get_items_for_job(msg.job_id)

    if len(all_items) < 2:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.BUNDLE_THEN_SELL,
            viable=False,
            confidence=0.95,
            explanation="Single item in job — bundling not possible",
        )
        await ctx.send(sender, DelegationResponse(
            from_agent="bundle_opportunity_agent",
            job_id=msg.job_id,
            item_id=msg.item_id,
            result_json=bid.model_dump_json(),
            confidence=bid.confidence,
        ))
        return

    partners = _find_bundle_partners(item, all_items)

    if not partners:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.BUNDLE_THEN_SELL,
            viable=False,
            confidence=0.8,
            explanation="No complementary items found for bundling",
        )
        await ctx.send(sender, DelegationResponse(
            from_agent="bundle_opportunity_agent",
            job_id=msg.job_id,
            item_id=msg.item_id,
            result_json=bid.model_dump_json(),
            confidence=bid.confidence,
        ))
        return

    bundled_ids = [item.item_id] + [p.item_id for p in partners]
    separate_total = PER_ITEM_BASE_VALUE * len(bundled_ids)
    combined_value = round(separate_total * BUNDLE_PREMIUM, 2)

    bid = RouteBid(
        item_id=item.item_id,
        route_type=RouteType.BUNDLE_THEN_SELL,
        viable=True,
        estimated_value=combined_value,
        effort=EffortLevel.MODERATE,
        speed=SpeedEstimate.WEEK,
        confidence=0.45,
        explanation=(
            f"Bundle {len(bundled_ids)} items: "
            f"separate ~${separate_total:.2f} vs bundled ~${combined_value:.2f} "
            f"({(BUNDLE_PREMIUM - 1) * 100:.0f}% premium)"
        ),
        bundled_item_ids=bundled_ids,
        separate_value=separate_total,
        combined_value=combined_value,
    )

    await ctx.send(sender, DelegationResponse(
        from_agent="bundle_opportunity_agent",
        job_id=msg.job_id,
        item_id=msg.item_id,
        result_json=bid.model_dump_json(),
        confidence=bid.confidence,
    ))


def create_bundle_opportunity_agent() -> Agent:
    agent = Agent(
        name="bundle_opportunity_agent",
        seed=settings.bundle_opportunity_agent_seed,
        port=8106,
        network="testnet",
    )
    agent.include(bundle_proto)
    return agent
