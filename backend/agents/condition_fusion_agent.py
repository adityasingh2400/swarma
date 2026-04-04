from __future__ import annotations

import json

from uagents import Agent, Context, Protocol

from backend.config import settings
from backend.models.item_card import ItemCard
from backend.models.job import JobStatus
from backend.models.route_bid import BestRouteDecision, RouteBid
from backend.protocols.messages import (
    ItemAnalysisRequest,
    ItemAnalysisResponse,
    RouteBidRequest,
    RouteBidResponse,
    RouteDecisionRequest,
    RouteDecisionResponse,
)
from backend.storage.store import store

# item_id -> {"expected": int, "received": int, "job_id": str}
_bid_tracker: dict[str, dict] = {}

fusion_proto = Protocol(name="condition_fusion", version="0.1.0")


@fusion_proto.on_message(
    model=ItemAnalysisRequest, replies={ItemAnalysisResponse, RouteBidRequest}
)
async def handle_item_analysis(ctx: Context, sender: str, msg: ItemAnalysisRequest):
    ctx.logger.info(f"Analyzing job {msg.job_id}: {len(msg.frame_paths)} frames")
    try:
        from backend.services.gemini import GeminiService

        gemini_svc = GeminiService()
        item_cards: list[ItemCard] = await gemini_svc.analyze_video(
            video_path=msg.video_path,
            transcript=msg.transcript,
            frame_paths=msg.frame_paths,
        )

        if not item_cards:
            ctx.logger.info(f"No items detected in job {msg.job_id}")
            await store.update_job_status(
                msg.job_id, JobStatus.COMPLETED, total_recovered_value=0.0
            )
            await ctx.send(
                sender,
                ItemAnalysisResponse(
                    job_id=msg.job_id, item_cards_json="[]", count=0
                ),
            )
            return

        from backend.agents.bureau import STAGE2_AGENTS

        for card in item_cards:
            card.job_id = msg.job_id
            await store.add_item(card)

            num_bidders = len(STAGE2_AGENTS)
            _bid_tracker[card.item_id] = {
                "expected": num_bidders,
                "received": 0,
                "job_id": msg.job_id,
            }

            card_json = card.model_dump_json()
            for stage2 in STAGE2_AGENTS:
                await ctx.send(
                    stage2.address,
                    RouteBidRequest(job_id=msg.job_id, item_card_json=card_json),
                )

        await store.update_job_status(msg.job_id, JobStatus.ROUTING)

        cards_payload = json.dumps([c.model_dump(mode="json") for c in item_cards])
        await ctx.send(
            sender,
            ItemAnalysisResponse(
                job_id=msg.job_id,
                item_cards_json=cards_payload,
                count=len(item_cards),
            ),
        )
    except Exception as e:
        ctx.logger.error(f"Analysis failed for job {msg.job_id}: {e}")
        await store.update_job_status(msg.job_id, JobStatus.FAILED, error=str(e))
        await ctx.send(
            sender,
            ItemAnalysisResponse(job_id=msg.job_id, item_cards_json="[]", count=0),
        )


@fusion_proto.on_message(model=RouteBidResponse, replies={RouteDecisionRequest})
async def handle_bid_response(ctx: Context, sender: str, msg: RouteBidResponse):
    ctx.logger.info(f"Bid received: {msg.route_type} for item {msg.item_id}")
    try:
        bid = RouteBid.model_validate_json(msg.bid_json)
        await store.add_bid(bid)

        tracker = _bid_tracker.get(msg.item_id)
        if not tracker:
            ctx.logger.warning(f"No bid tracker for item {msg.item_id}")
            return

        tracker["received"] += 1
        ctx.logger.info(
            f"Item {msg.item_id}: {tracker['received']}/{tracker['expected']} bids"
        )

        if tracker["received"] >= tracker["expected"]:
            all_bids = store.get_bids(msg.item_id)
            bids_json = json.dumps([b.model_dump(mode="json") for b in all_bids])

            from backend.agents.bureau import route_decider_agent

            await ctx.send(
                route_decider_agent.address,
                RouteDecisionRequest(
                    job_id=tracker["job_id"],
                    item_id=msg.item_id,
                    bids_json=bids_json,
                ),
            )
            del _bid_tracker[msg.item_id]
    except Exception as e:
        ctx.logger.error(f"Error processing bid response: {e}")


@fusion_proto.on_message(model=RouteDecisionResponse)
async def handle_route_decision(ctx: Context, sender: str, msg: RouteDecisionResponse):
    ctx.logger.info(f"Decision for item {msg.item_id} in job {msg.job_id}")
    try:
        decision = BestRouteDecision.model_validate_json(msg.decision_json)
        await store.set_decision(decision)

        job = store.get_job(msg.job_id)
        if not job:
            return

        items = store.get_items_for_job(msg.job_id)
        all_decided = all(store.get_decision(i.item_id) is not None for i in items)
        if all_decided:
            total_value = sum(
                d.estimated_best_value
                for i in items
                if (d := store.get_decision(i.item_id))
            )
            await store.update_job_status(
                msg.job_id, JobStatus.COMPLETED, total_recovered_value=total_value
            )
            ctx.logger.info(
                f"Job {msg.job_id} complete — total value: ${total_value:.2f}"
            )
    except Exception as e:
        ctx.logger.error(f"Error processing route decision: {e}")


def create_condition_fusion_agent() -> Agent:
    agent = Agent(
        name="condition_fusion_agent",
        seed=settings.condition_fusion_agent_seed,
        port=8101,
        network="testnet",
    )
    agent.include(fusion_proto)
    return agent
