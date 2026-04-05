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
    hero_frame_paths: list[str] = Field(default_factory=list)
    all_frame_paths: list[str] = Field(default_factory=list)
    listing_image_paths: list[str] = Field(default_factory=list)
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

    @property
    def condition_label(self) -> str:
        if not self.has_defects:
            return "Like New"
        severe = [d for d in self.all_defects if d.severity == "major"]
        if severe:
            return "Fair"
        return "Good"
