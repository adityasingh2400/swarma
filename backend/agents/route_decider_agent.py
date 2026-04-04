from __future__ import annotations

import json

from uagents import Agent, Context, Protocol

from backend.config import settings
from backend.models.route_bid import BestRouteDecision, RouteBid, RouteType
from backend.protocols.messages import (
    DelegationRequest,
    DelegationResponse,
    RouteDecisionRequest,
    RouteDecisionResponse,
)

decider_proto = Protocol(name="route_decider", version="0.1.0")

_ROUTE_TO_AGENT_NAME = {
    RouteType.RETURN: "return_agent",
    RouteType.TRADE_IN: "trade_in_agent",
    RouteType.SELL_AS_IS: "marketplace_resale_agent",
    RouteType.REPAIR_THEN_SELL: "repair_roi_advisor_agent",
    RouteType.BUNDLE_THEN_SELL: "bundle_opportunity_agent",
}

LOW_CONFIDENCE_THRESHOLD = 0.3

_EFFORT_SCORES = {"minimal": 1.0, "low": 0.85, "moderate": 0.65, "high": 0.4}
_SPEED_SCORES = {
    "instant": 1.0,
    "days": 0.9,
    "week": 0.7,
    "weeks": 0.45,
    "month_plus": 0.2,
}


def _score_bid(bid: RouteBid) -> float:
    """Weighted composite: 45% value, 25% confidence, 15% effort, 15% speed."""
    if not bid.viable:
        return -1.0
    value_norm = bid.estimated_value / 100.0
    effort_s = _EFFORT_SCORES.get(bid.effort.value, 0.5)
    speed_s = _SPEED_SCORES.get(bid.speed.value, 0.5)
    return value_norm * 0.45 + bid.confidence * 0.25 + effort_s * 0.15 + speed_s * 0.15


@decider_proto.on_message(
    model=RouteDecisionRequest, replies={RouteDecisionResponse, DelegationRequest}
)
async def handle_route_decision(ctx: Context, sender: str, msg: RouteDecisionRequest):
    ctx.logger.info(f"Deciding best route for item {msg.item_id}")
    bids = [RouteBid.model_validate(b) for b in json.loads(msg.bids_json)]

    viable = [b for b in bids if b.viable]

    if not viable:
        decision = BestRouteDecision(
            item_id=msg.item_id,
            best_route=RouteType.NO_ACTION,
            route_reason="No viable routes found",
            route_explanation_short="None of the evaluated routes are viable for this item",
            route_explanation_detailed=(
                f"Evaluated {len(bids)} routes — none viable. "
                "Consider recycling or donating."
            ),
            alternatives=[],
        )
    else:
        ranked = sorted(viable, key=_score_bid, reverse=True)
        winner = ranked[0]
        alternatives = ranked[1:]

        low_conf = [b for b in viable if b.confidence < LOW_CONFIDENCE_THRESHOLD]
        for bid in low_conf:
            agent_name = _ROUTE_TO_AGENT_NAME.get(bid.route_type)
            if not agent_name:
                continue
            ctx.logger.warning(
                f"Low confidence ({bid.confidence:.2f}) on {bid.route_type.value} "
                f"— requesting delegation to {agent_name}"
            )
            try:
                from backend.agents import bureau as _bureau

                target = getattr(_bureau, agent_name, None)
                if target:
                    await ctx.send(
                        target.address,
                        DelegationRequest(
                            from_agent="route_decider",
                            to_agent=agent_name,
                            reason=(
                                f"Low confidence ({bid.confidence:.2f}) "
                                f"on {bid.route_type.value}"
                            ),
                            job_id=msg.job_id,
                            item_id=msg.item_id,
                            payload_json=bid.model_dump_json(),
                        ),
                    )
            except Exception as e:
                ctx.logger.error(f"Delegation to {agent_name} failed: {e}")

        alt_summary = (
            f"Alternatives: {', '.join(b.route_type.value for b in alternatives)}."
            if alternatives
            else "No alternatives."
        )
        decision = BestRouteDecision(
            item_id=msg.item_id,
            best_route=winner.route_type,
            estimated_best_value=winner.estimated_value,
            effort=winner.effort,
            speed=winner.speed,
            route_reason=f"Highest composite score among {len(viable)} viable routes",
            route_explanation_short=winner.explanation,
            route_explanation_detailed=(
                f"Selected {winner.route_type.value} "
                f"(${winner.estimated_value:.2f}, "
                f"confidence {winner.confidence:.0%}). "
                f"Evaluated {len(bids)} routes, {len(viable)} viable. "
                f"{alt_summary}"
            ),
            alternatives=alternatives,
            winning_bid=winner,
        )

    ctx.logger.info(f"Decision for {msg.item_id}: {decision.best_route.value}")
    await ctx.send(
        sender,
        RouteDecisionResponse(
            job_id=msg.job_id,
            item_id=msg.item_id,
            decision_json=decision.model_dump_json(),
        ),
    )


@decider_proto.on_message(model=DelegationResponse)
async def handle_delegation_response(ctx: Context, sender: str, msg: DelegationResponse):
    ctx.logger.info(
        f"Delegation response from {msg.from_agent} for item {msg.item_id} "
        f"(confidence={msg.confidence:.2f})"
    )
    if msg.confidence > LOW_CONFIDENCE_THRESHOLD:
        ctx.logger.info(
            f"Delegation improved confidence for item {msg.item_id} — "
            f"updated estimate available via store"
        )


def create_route_decider_agent() -> Agent:
    agent = Agent(
        name="route_decider_agent",
        seed=settings.route_decider_agent_seed,
        port=8107,
        network="testnet",
    )
    agent.include(decider_proto)
    return agent
