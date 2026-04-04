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

return_proto = Protocol(name="return_evaluator", version="0.1.0")

_RETURN_SIGNALS = frozenset(
    {"sealed", "unopened", "new", "nib", "bnib", "tags", "tag", "shrinkwrap", "mint"}
)


@return_proto.on_message(model=RouteBidRequest, replies={RouteBidResponse})
async def handle_route_bid(ctx: Context, sender: str, msg: RouteBidRequest):
    ctx.logger.info(f"Evaluating return viability for job {msg.job_id}")
    item = ItemCard.model_validate_json(msg.item_card_json)

    condition = item.condition_label.lower()
    searchable = f"{item.name_guess} {item.raw_transcript_segment}".lower()
    has_keywords = any(kw in searchable for kw in _RETURN_SIGNALS)
    is_pristine = condition == "like new" and not item.has_defects

    viable = is_pristine or has_keywords

    if viable:
        confidence = 0.8 if (has_keywords and is_pristine) else 0.5
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.RETURN,
            viable=True,
            estimated_value=0.0,
            effort=EffortLevel.MINIMAL,
            speed=SpeedEstimate.DAYS,
            confidence=confidence,
            explanation="Item appears returnable — unused / new-in-box condition",
            return_window_open=True,
            return_reason=(
                "Item unused / new-in-box" if is_pristine else "Possible open return window"
            ),
        )
    else:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.RETURN,
            viable=False,
            confidence=0.9,
            explanation="Item shows use or damage; return unlikely to succeed",
        )

    await ctx.send(
        sender,
        RouteBidResponse(
            job_id=msg.job_id,
            item_id=item.item_id,
            route_type=RouteType.RETURN.value,
            bid_json=bid.model_dump_json(),
        ),
    )


@return_proto.on_message(model=DelegationRequest, replies={DelegationResponse})
async def handle_delegation(ctx: Context, sender: str, msg: DelegationRequest):
    ctx.logger.info(f"Delegation from {msg.from_agent} for item {msg.item_id}: {msg.reason}")
    item = ItemCard.model_validate_json(msg.payload_json)

    condition = item.condition_label.lower()
    searchable = f"{item.name_guess} {item.raw_transcript_segment}".lower()
    has_keywords = any(kw in searchable for kw in _RETURN_SIGNALS)
    is_pristine = condition == "like new" and not item.has_defects
    viable = is_pristine or has_keywords

    if viable:
        confidence = 0.8 if (has_keywords and is_pristine) else 0.5
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.RETURN,
            viable=True,
            estimated_value=0.0,
            effort=EffortLevel.MINIMAL,
            speed=SpeedEstimate.DAYS,
            confidence=confidence,
            explanation="Item appears returnable — unused / new-in-box condition",
            return_window_open=True,
            return_reason=(
                "Item unused / new-in-box" if is_pristine else "Possible open return window"
            ),
        )
    else:
        bid = RouteBid(
            item_id=item.item_id,
            route_type=RouteType.RETURN,
            viable=False,
            confidence=0.9,
            explanation="Item shows use or damage; return unlikely to succeed",
        )

    await ctx.send(sender, DelegationResponse(
        from_agent="return_agent",
        job_id=msg.job_id,
        item_id=msg.item_id,
        result_json=bid.model_dump_json(),
        confidence=bid.confidence,
    ))


def create_return_agent() -> Agent:
    agent = Agent(
        name="return_agent",
        seed=settings.return_agent_seed,
        port=8102,
        network="testnet",
    )
    agent.include(return_proto)
    return agent
