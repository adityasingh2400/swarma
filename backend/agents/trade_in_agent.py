from __future__ import annotations

import hashlib
import logging

from uagents import Agent, Context, Protocol

from backend.config import settings
from backend.models.item_card import ItemCard, ItemCategory
from backend.models.route_bid import (
    EffortLevel,
    RouteBid,
    RouteType,
    SpeedEstimate,
    TradeInQuote,
)
from backend.protocols.messages import (
    DelegationRequest,
    DelegationResponse,
    RouteBidRequest,
    RouteBidResponse,
)
from backend.services.apple_trade_in import get_apple_trade_in

logger = logging.getLogger(__name__)

trade_in_proto = Protocol(name="trade_in_evaluator", version="0.1.0")

# Fallback providers (used when Apple API is unavailable)
_PROVIDERS: dict[str, dict] = {
    "Apple Trade In": {
        "brands": ["apple", "iphone", "ipad", "macbook", "airpods", "apple watch"],
        "multiplier": 0.40,
        "speed": "days",
        "effort": "low",
    },
    "Samsung Trade-In": {
        "brands": ["samsung", "galaxy"],
        "multiplier": 0.35,
        "speed": "days",
        "effort": "low",
    },
    "Best Buy Trade-In": {
        "brands": [],
        "multiplier": 0.30,
        "speed": "instant",
        "effort": "minimal",
    },
    "Decluttr": {
        "brands": [],
        "multiplier": 0.25,
        "speed": "week",
        "effort": "low",
    },
    "Gazelle": {
        "brands": [],
        "multiplier": 0.28,
        "speed": "week",
        "effort": "low",
    },
}

# Other providers expressed as a ratio of Apple's payout
_OTHER_PROVIDER_RATIOS: list[tuple[str, float, str, str]] = [
    ("Best Buy Trade-In", 0.75, "instant", "minimal"),
    ("Decluttr", 0.60, "week", "low"),
    ("Gazelle", 0.70, "week", "low"),
]


def _estimate_retail_price(item: ItemCard) -> float:
    """Deterministic rough retail estimate derived from item identity."""
    seed_val = int(hashlib.md5(item.name_guess.encode()).hexdigest()[:8], 16)
    base = 50 + (seed_val % 950)

    name_lower = item.name_guess.lower()
    if any(kw in name_lower for kw in ("pro", "max", "ultra")):
        base *= 1.5
    if any(kw in name_lower for kw in ("phone", "iphone", "galaxy", "pixel")):
        base = max(base, 200)
    if any(kw in name_lower for kw in ("laptop", "macbook", "notebook")):
        base = max(base, 400)
    if any(kw in name_lower for kw in ("watch", "buds", "earbuds", "airpods")):
        base = max(base, 80)

    return round(base, 2)


def _condition_multiplier(item: ItemCard) -> float:
    if not item.has_defects:
        return 1.0
    major = sum(1 for d in item.all_defects if d.severity == "major")
    return 0.5 if major else 0.75


def _fallback_quotes(item: ItemCard) -> list[TradeInQuote]:
    """Build quotes using the deterministic formula (fallback path)."""
    retail = _estimate_retail_price(item)
    cond_mult = _condition_multiplier(item)
    name_lower = item.name_guess.lower()

    quotes: list[TradeInQuote] = []
    for provider_name, cfg in _PROVIDERS.items():
        brand_match = not cfg["brands"] or any(b in name_lower for b in cfg["brands"])
        if not brand_match:
            continue
        payout = round(retail * cfg["multiplier"] * cond_mult, 2)
        quotes.append(
            TradeInQuote(
                provider=provider_name,
                payout=payout,
                speed=cfg["speed"],
                effort=cfg["effort"],
                confidence=0.7 if brand_match else 0.4,
            )
        )

    if not quotes:
        quotes.append(
            TradeInQuote(
                provider="Decluttr",
                payout=round(retail * 0.20 * cond_mult, 2),
                speed="week",
                effort="low",
                confidence=0.5,
            )
        )
    return quotes


async def _build_quotes(item: ItemCard) -> tuple[list[TradeInQuote], str]:
    """Build trade-in quotes, using Apple's live API when possible.

    Returns (quotes, explanation).
    """
    apple = await get_apple_trade_in(item.name_guess, item.condition_label)

    if apple:
        apple_payout = apple["estimated_payout"]
        matched = apple["matched_model"]
        condition = apple["condition"]
        url = apple["url"]

        quotes = [
            TradeInQuote(
                provider="Apple Trade In",
                payout=apple_payout,
                speed="days",
                effort="low",
                confidence=0.92,
                url=url,
            ),
        ]
        # Scale other providers relative to Apple's real value
        for name, ratio, speed, effort in _OTHER_PROVIDER_RATIOS:
            quotes.append(
                TradeInQuote(
                    provider=name,
                    payout=round(apple_payout * ratio, 2),
                    speed=speed,
                    effort=effort,
                    confidence=0.60,
                )
            )

        explanation = (
            f"Apple Trade In: ${apple_payout:.2f} for {matched} "
            f"({condition} condition) — live quote"
        )
        logger.info("Apple Trade-In API hit: %s → $%.2f", matched, apple_payout)
        return quotes, explanation

    # Fallback to deterministic formula
    logger.info(
        "Apple Trade-In API miss for '%s', using fallback formula",
        item.name_guess,
    )
    quotes = _fallback_quotes(item)
    best = max(quotes, key=lambda q: q.payout)
    explanation = f"Best trade-in: {best.provider} @ ${best.payout:.2f}"
    return quotes, explanation


def _bid_from_quotes(
    item: ItemCard, quotes: list[TradeInQuote], explanation: str
) -> RouteBid:
    best_quote = max(quotes, key=lambda q: q.payout)
    return RouteBid(
        item_id=item.item_id,
        route_type=RouteType.TRADE_IN,
        viable=True,
        estimated_value=best_quote.payout,
        effort=EffortLevel.LOW,
        speed=SpeedEstimate.DAYS,
        confidence=best_quote.confidence,
        explanation=explanation,
        trade_in_quotes=quotes,
    )


def _not_applicable_bid(item: ItemCard) -> RouteBid:
    return RouteBid(
        item_id=item.item_id,
        route_type=RouteType.TRADE_IN,
        viable=False,
        confidence=0.95,
        explanation=f"Trade-in not applicable for {item.category.value} items",
    )


@trade_in_proto.on_message(model=RouteBidRequest, replies={RouteBidResponse})
async def handle_route_bid(ctx: Context, sender: str, msg: RouteBidRequest):
    ctx.logger.info(f"Evaluating trade-in for job {msg.job_id}")
    item = ItemCard.model_validate_json(msg.item_card_json)

    if not item.is_electronics:
        bid = _not_applicable_bid(item)
    else:
        quotes, explanation = await _build_quotes(item)
        bid = _bid_from_quotes(item, quotes, explanation)

    await ctx.send(
        sender,
        RouteBidResponse(
            job_id=msg.job_id,
            item_id=item.item_id,
            route_type=RouteType.TRADE_IN.value,
            bid_json=bid.model_dump_json(),
        ),
    )


@trade_in_proto.on_message(model=DelegationRequest, replies={DelegationResponse})
async def handle_delegation(ctx: Context, sender: str, msg: DelegationRequest):
    ctx.logger.info(f"Delegation from {msg.from_agent} for item {msg.item_id}: {msg.reason}")
    item = ItemCard.model_validate_json(msg.payload_json)

    if not item.is_electronics:
        bid = _not_applicable_bid(item)
    else:
        quotes, explanation = await _build_quotes(item)
        bid = _bid_from_quotes(item, quotes, explanation)

    await ctx.send(sender, DelegationResponse(
        from_agent="trade_in_agent",
        job_id=msg.job_id,
        item_id=msg.item_id,
        result_json=bid.model_dump_json(),
        confidence=bid.confidence,
    ))


def create_trade_in_agent() -> Agent:
    agent = Agent(
        name="trade_in_agent",
        seed=settings.trade_in_agent_seed,
        port=8103,
        network="testnet",
    )
    agent.include(trade_in_proto)
    return agent
