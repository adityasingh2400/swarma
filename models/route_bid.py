from __future__ import annotations

import enum

from pydantic import BaseModel, Field


class RouteType(str, enum.Enum):
    RETURN = "return"
    TRADE_IN = "trade_in"
    SELL_AS_IS = "sell_as_is"
    REPAIR_THEN_SELL = "repair_then_sell"
    BUNDLE_THEN_SELL = "bundle_then_sell"
    RECYCLE = "recycle"
    NO_ACTION = "no_action"


class EffortLevel(str, enum.Enum):
    MINIMAL = "minimal"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class SpeedEstimate(str, enum.Enum):
    INSTANT = "instant"
    DAYS = "days"
    WEEK = "week"
    WEEKS = "weeks"
    MONTH_PLUS = "month_plus"


class ComparableListing(BaseModel):
    platform: str = ""
    title: str = ""
    price: float = 0.0
    shipping: str = ""
    condition: str = ""
    image_url: str = ""
    url: str = ""
    match_score: float = 0.0


class TradeInQuote(BaseModel):
    provider: str = ""
    payout: float = 0.0
    speed: str = ""
    effort: str = ""
    confidence: float = 0.0
    url: str = ""


class RepairCandidate(BaseModel):
    part_name: str = ""
    part_query: str = ""
    part_price: float = 0.0
    part_url: str = ""
    part_image_url: str = ""
    source: str = "amazon"


class RouteBid(BaseModel):
    item_id: str
    route_type: RouteType
    viable: bool = True
    estimated_value: float = 0.0
    effort: EffortLevel = EffortLevel.MODERATE
    speed: SpeedEstimate = SpeedEstimate.WEEK
    confidence: float = 0.0
    explanation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)

    comparable_listings: list[ComparableListing] = Field(default_factory=list)
    trade_in_quotes: list[TradeInQuote] = Field(default_factory=list)
    repair_candidates: list[RepairCandidate] = Field(default_factory=list)
    as_is_value: float = 0.0
    post_repair_value: float = 0.0
    repair_cost: float = 0.0
    net_gain_unlocked: float = 0.0

    bundled_item_ids: list[str] = Field(default_factory=list)
    separate_value: float = 0.0
    combined_value: float = 0.0

    return_window_open: bool = False
    return_reason: str = ""


class BestRouteDecision(BaseModel):
    item_id: str
    best_route: RouteType
    estimated_best_value: float = 0.0
    effort: EffortLevel = EffortLevel.MODERATE
    speed: SpeedEstimate = SpeedEstimate.WEEK
    route_reason: str = ""
    route_explanation_short: str = ""
    route_explanation_detailed: str = ""
    alternatives: list[RouteBid] = Field(default_factory=list)
    winning_bid: RouteBid | None = None
