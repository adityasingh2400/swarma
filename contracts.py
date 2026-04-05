"""Shared types for the v2 pipeline. All 4 people build against these."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from models.item_card import ItemCard
from models.listing_package import ListingPackage


# ---------------------------------------------------------------------------
# Agent lifecycle events (Person 1 emits → Person 3 relays → Person 4 renders)
# ---------------------------------------------------------------------------

class AgentEvent(BaseModel):
    type: str  # "agent:spawn" | "agent:status" | "agent:result" | "agent:complete" | "agent:error" | "decision:made"
    agent_id: str  # "{platform}-{phase}-{item_id}" e.g. "ebay-research-item1"
    timestamp: float = Field(default_factory=time.time)
    data: dict = Field(default_factory=dict)


class AgentState(BaseModel):
    agent_id: str
    item_id: str
    platform: str  # "facebook" | "depop" | "amazon"
    phase: str  # "research" | "listing"
    status: str  # "queued" | "running" | "retrying" | "complete" | "error" | "blocked"
    task: str  # human-readable description
    started_at: float | None = None
    completed_at: float | None = None
    result: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Route decision output
# ---------------------------------------------------------------------------

class RouteDecision(BaseModel):
    item_id: str
    platforms: list[str]  # ["ebay", "facebook"] — top 3-4 by score
    prices: dict[str, float]  # {"ebay": 799.0, "facebook": 750.0, ...}
    scores: dict[str, float] = Field(default_factory=dict)  # raw scores per platform


# ---------------------------------------------------------------------------
# Playbook ABC (Person 2 implements, Person 1 calls)
# ---------------------------------------------------------------------------

class Playbook(ABC):
    platform: str  # "facebook" | "depop" | "amazon"

    @abstractmethod
    def research_task(self, item: ItemCard) -> tuple[str, list[dict]]:
        """Returns (task_string, initial_actions).
        initial_actions pre-navigates to the target URL WITHOUT an LLM call.
        task_string assumes the agent is ALREADY on the page.
        Example:
            return (
                "Extract the prices of the first 5 sold listings and total count.",
                [{"navigate": {"url": "https://ebay.com/sch/..."}}],
            )
        """

    @abstractmethod
    def listing_task(self, item: ItemCard, package: ListingPackage) -> tuple[str, list[dict]]:
        """Returns (task_string, initial_actions) for form-filling.
        initial_actions navigates to the listing creation page.
        task_string has step-by-step form fill instructions.
        """

    @abstractmethod
    def parse_research(self, result: str) -> dict:
        """Extract structured data from agent's research output.
        Must return at minimum: {"avg_sold_price": float, "listings_found": int}
        """
