"""
uAgents protocol message models for inter-agent communication.
All messages inherit from uagents.Model for wire compatibility.
"""
from __future__ import annotations

from uagents import Model


# ── Intake ────────────────────────────────────────────────────────────────────

class StartJobRequest(Model):
    job_id: str
    video_path: str
    session_id: str = ""


class StartJobResponse(Model):
    job_id: str
    status: str
    message: str = ""


# ── Item Analysis ─────────────────────────────────────────────────────────────

class ItemAnalysisRequest(Model):
    job_id: str
    transcript: str
    frame_paths: list[str]
    video_path: str = ""


class ItemAnalysisResponse(Model):
    job_id: str
    item_cards_json: str  # JSON-serialized list[ItemCard]
    count: int = 0


# ── Research (per-platform listing research) ─────────────────────────────────

class RouteBidRequest(Model):
    job_id: str
    item_card_json: str  # JSON-serialized ItemCard
    as_is_value: float = 0.0  # passed to repair agent


class RouteBidResponse(Model):
    job_id: str
    item_id: str
    route_type: str
    bid_json: str  # JSON-serialized RouteBid


# ── Route Decision ────────────────────────────────────────────────────────────

class RouteDecisionRequest(Model):
    job_id: str
    item_id: str
    bids_json: str  # JSON-serialized list[RouteBid]


class RouteDecisionResponse(Model):
    job_id: str
    item_id: str
    decision_json: str  # JSON-serialized BestRouteDecision


# ── Execution ─────────────────────────────────────────────────────────────────

class ExecutionRequest(Model):
    job_id: str
    item_id: str
    listing_package_json: str  # JSON-serialized ListingPackage
    platforms: list[str]


class ExecutionResponse(Model):
    job_id: str
    item_id: str
    platform: str
    status: str
    listing_id: str = ""
    url: str = ""
    error: str = ""


# ── Confidence-Driven Delegation ──────────────────────────────────────────────

class DelegationRequest(Model):
    from_agent: str
    to_agent: str
    reason: str
    job_id: str
    item_id: str
    payload_json: str


class DelegationResponse(Model):
    from_agent: str
    job_id: str
    item_id: str
    result_json: str
    confidence: float = 0.0
