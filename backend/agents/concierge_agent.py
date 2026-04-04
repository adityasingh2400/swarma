from __future__ import annotations

import uuid
from datetime import datetime

import httpx
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

from backend.config import settings
from backend.storage.store import store

ASI_ONE_URL = "https://api.asi1.ai/v1/chat/completions"
ASI_ONE_MODEL = "asi1-mini"

SYSTEM_PROMPT = (
    "You are ReRoute Concierge, an expert assistant that helps users understand "
    "what to do with their returned, unused, or unwanted items. You analyze items "
    "via video, evaluate multiple disposition routes (return, trade-in, resell, "
    "repair-then-sell, bundle), and recommend the best path to maximize recovery "
    "value.\n\n"
    "Be concise, friendly, and specific. Reference actual item names, prices, and "
    "route decisions when available. If asked why a route was chosen, explain the "
    "trade-offs between value, effort, speed, and confidence."
)


def _build_context() -> str:
    jobs = store.list_jobs()
    if not jobs:
        return "No jobs have been processed yet."

    parts: list[str] = []
    for job in jobs[:3]:
        items = store.get_items_for_job(job.job_id)
        parts.append(
            f"Job {job.job_id} ({job.status.value}): {len(items)} item(s)"
        )
        for item in items:
            decision = store.get_decision(item.item_id)
            bids = store.get_bids(item.item_id)
            line = f"  • {item.name_guess} [{item.condition_label}]"
            if decision:
                line += (
                    f" → {decision.best_route.value} "
                    f"(${decision.estimated_best_value:.2f})"
                )
            parts.append(line)
            for bid in bids:
                if bid.viable:
                    parts.append(
                        f"    Bid {bid.route_type.value}: "
                        f"${bid.estimated_value:.2f} "
                        f"(conf {bid.confidence:.0%}) — {bid.explanation}"
                    )
    return "\n".join(parts)


def _extract_text(msg) -> str:
    text_parts: list[str] = []
    content = getattr(msg, "content", None) or []
    for block in content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    return " ".join(text_parts).strip() or "Hello"


def _fallback_response(user_text: str) -> str:
    jobs = store.list_jobs()
    if not jobs:
        return "No items have been processed yet. Upload a video to get started!"

    latest = jobs[0]
    items = store.get_items_for_job(latest.job_id)
    if not items:
        return f"Job {latest.job_id} is {latest.status.value}. No items identified yet."

    lines = [f"Here's your latest batch ({len(items)} items):"]
    for item in items:
        decision = store.get_decision(item.item_id)
        if decision:
            lines.append(
                f"• {item.name_guess}: {decision.best_route.value} "
                f"(~${decision.estimated_best_value:.2f})"
            )
        else:
            lines.append(f"• {item.name_guess}: still evaluating routes")
    return "\n".join(lines)


def _create_chat_protocol() -> Protocol:
    try:
        proto = Protocol(spec=chat_protocol_spec)

        @proto.on_message(ChatMessage)
        async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
            await _handle_chat_impl(ctx, sender, msg)

        @proto.on_message(ChatAcknowledgement)
        async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
            pass

        return proto
    except Exception:
        proto = Protocol(name="AgentChatProtocol", version="0.3.0")

        @proto.on_message(ChatMessage)
        async def handle_chat_fallback(ctx: Context, sender: str, msg: ChatMessage):
            await _handle_chat_impl(ctx, sender, msg)

        @proto.on_message(ChatAcknowledgement)
        async def handle_ack_fallback(ctx: Context, sender: str, msg: ChatAcknowledgement):
            pass

        return proto


async def _handle_chat_impl(ctx: Context, sender: str, msg) -> None:
    ctx.logger.info(f"Chat from {sender}")

    try:
        ack_kwargs: dict = {}
        if hasattr(ChatAcknowledgement, "model_fields"):
            fields = ChatAcknowledgement.model_fields
            if "timestamp" in fields:
                ack_kwargs["timestamp"] = datetime.utcnow().isoformat()
            if "acknowledged_msg_id" in fields and hasattr(msg, "msg_id"):
                ack_kwargs["acknowledged_msg_id"] = msg.msg_id
        await ctx.send(sender, ChatAcknowledgement(**ack_kwargs))
    except Exception as e:
        ctx.logger.warning(f"Ack send failed: {e}")

    user_text = _extract_text(msg)
    context = _build_context()

    reply_text = ""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                ASI_ONE_URL,
                headers={
                    "Authorization": f"Bearer {settings.asi_one_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": ASI_ONE_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": f"{SYSTEM_PROMPT}\n\nCurrent State:\n{context}",
                        },
                        {"role": "user", "content": user_text},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            reply_text = data["choices"][0]["message"]["content"]
    except Exception as e:
        ctx.logger.error(f"ASI:One API call failed: {e}")
        reply_text = _fallback_response(user_text)

    try:
        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.utcnow().isoformat(),
                msg_id=uuid.uuid4().hex,
                content=[TextContent(text=reply_text), EndSessionContent()],
            ),
        )
    except Exception as e:
        ctx.logger.error(f"Chat reply failed: {e}")


chat_proto = _create_chat_protocol()


def create_concierge_agent() -> Agent:
    agent = Agent(
        name="concierge_agent",
        seed=settings.concierge_agent_seed,
        port=8108,
        network="testnet",
        mailbox=True,
        publish_agent_details=True,
    )
    agent.include(chat_proto, publish_manifest=True)
    return agent
