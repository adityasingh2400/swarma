from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class JobStatus(str, enum.Enum):
    CREATED = "created"
    UPLOADING = "uploading"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    ROUTING = "routing"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: JobStatus = JobStatus.CREATED
    video_path: str | None = None
    transcript_path: str | None = None
    transcript_text: str | None = None
    frame_paths: list[str] = Field(default_factory=list)
    item_ids: list[str] = Field(default_factory=list)
    total_recovered_value: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    error: str | None = None

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()
