from __future__ import annotations

import asyncio
import logging

from backend.config import settings
from backend.models.job import JobStatus
from backend.services.gemini import GeminiService
from backend.services.media import MediaService
from backend.storage.store import store

logger = logging.getLogger(__name__)


class TranscriptAndFrameExtractionSystem:
    def __init__(
        self,
        media: MediaService | None = None,
        gemini: GeminiService | None = None,
    ) -> None:
        self.media = media or MediaService()
        self.gemini = gemini or GeminiService()

    async def process(
        self,
        job_id: str,
        video_path: str,
    ) -> tuple[str, list[str]]:
        await store.update_job_status(job_id, JobStatus.EXTRACTING)

        try:
            frame_paths, transcript = await asyncio.gather(
                self.media.extract_frames(video_path),
                self.gemini.transcribe_from_video(video_path),
            )
            logger.info("Extracted %d frames for job %s", len(frame_paths), job_id)
            logger.info(
                "Transcript extracted for job %s (%d chars)",
                job_id,
                len(transcript),
            )

            await store.update_job_status(
                job_id,
                JobStatus.EXTRACTING,
                transcript_text=transcript,
                frame_paths=frame_paths,
            )

            return transcript, frame_paths

        except Exception:
            logger.exception("Extraction failed for job %s", job_id)
            await store.update_job_status(
                job_id,
                JobStatus.FAILED,
                error="Frame/transcript extraction failed",
            )
            raise
