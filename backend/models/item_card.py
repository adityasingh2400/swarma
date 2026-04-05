from __future__ import annotations

import enum
import uuid

from pydantic import BaseModel, Field


class DefectSignal(BaseModel):
    description: str
    source: str  # "visual" | "spoken" | "both"
    severity: str = "moderate"  # "minor" | "moderate" | "major"


class ItemCategory(str, enum.Enum):
    ELECTRONICS = "electronics"
    CLOTHING = "clothing"
    ACCESSORIES = "accessories"
    HOME = "home"
    SPORTS = "sports"
    TOYS = "toys"
    BOOKS = "books"
    TOOLS = "tools"
    AUTOMOTIVE = "automotive"
    OTHER = "other"


class ItemCard(BaseModel):
    item_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    job_id: str = ""
    name_guess: str = ""
    category: ItemCategory = ItemCategory.OTHER
    likely_specs: dict[str, str] = Field(default_factory=dict)
    visible_defects: list[DefectSignal] = Field(default_factory=list)
    spoken_defects: list[DefectSignal] = Field(default_factory=list)
    accessories_included: list[str] = Field(default_factory=list)
    accessories_missing: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    condition: str = ""
    hero_frame_paths: list[str] = Field(default_factory=list)
    all_frame_paths: list[str] = Field(default_factory=list)
    segment_start_sec: float = 0.0
    segment_end_sec: float = 0.0
    evidence_references: list[str] = Field(default_factory=list)
    raw_transcript_segment: str = ""
    hero_frame_indices_raw: list[int] = Field(default_factory=list, exclude=True)

    # v2: attached by orchestrator after route decision
    listing_package: object | None = Field(default=None, exclude=True)

    @property
    def all_defects(self) -> list[DefectSignal]:
        return self.visible_defects + self.spoken_defects

    @property
    def has_defects(self) -> bool:
        return len(self.all_defects) > 0

    @property
    def is_electronics(self) -> bool:
        return self.category == ItemCategory.ELECTRONICS

    _CONDITION_DISPLAY = {
        "new": "New",
        "like_new": "Like New",
        "good": "Good",
        "fair": "Fair",
        "poor": "Poor",
    }

    @property
    def condition_label(self) -> str:
        if self.condition:
            return self._CONDITION_DISPLAY.get(self.condition, self.condition.replace("_", " ").title())
        spoken_severe = [d for d in self.spoken_defects if d.severity == "major"]
        if spoken_severe:
            return "Fair"
        if self.spoken_defects:
            return "Good"
        severe = [d for d in self.visible_defects if d.severity == "major"]
        if severe:
            return "Fair"
        if self.visible_defects:
            return "Good"
        return "Like New"
