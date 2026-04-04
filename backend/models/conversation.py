from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class BuyerSeriousness(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SPAM = "spam"


class ChatMessage(BaseModel):
    sender: str  # "buyer" | "seller" | "system"
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    is_offer: bool = False
    offer_amount: float | None = None


class ConversationThread(BaseModel):
    thread_id: str = ""
    item_id: str = ""
    job_id: str = ""
    platform: str = ""
    platform_listing_id: str = ""
    buyer_id: str = ""
    buyer_handle: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    seriousness_score: BuyerSeriousness = BuyerSeriousness.MEDIUM
    current_offer: float | None = None
    suggested_reply: str = ""
    suggested_counter: float | None = None
    is_winning: bool = False
    resolved: bool = False
