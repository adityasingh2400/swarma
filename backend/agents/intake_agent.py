from __future__ import annotations

from uagents import Agent, Context, Protocol

from backend.config import settings
from backend.models.job import JobStatus
from backend.protocols.messages import (
    ItemAnalysisRequest,
    ItemAnalysisResponse,
    StartJobRequest,
    StartJobResponse,
)
from backend.storage.store import store

intake_proto = Protocol(name="intake", version="0.1.0")


@intake_proto.on_message(model=StartJobRequest, replies={StartJobResponse})
async def handle_start_job(ctx: Context, sender: str, msg: StartJobRequest):
    ctx.logger.info(f"Starting job for video: {msg.video_path}")
    job = None
    try:
        job = store.get_job(msg.job_id) if msg.job_id else None
        if not job:
            job = await store.create_job(msg.video_path)

        await store.update_job_status(job.job_id, JobStatus.EXTRACTING)

        from backend.services.media import MediaService

        media_svc = MediaService()
        transcript = await media_svc.extract_transcript(msg.video_path)
        frames = await media_svc.extract_frames(msg.video_path)

        await store.update_job_status(
            job.job_id,
            JobStatus.ANALYZING,
            transcript_text=transcript,
            frame_paths=frames,
        )

        from backend.agents.bureau import condition_fusion_agent

        await ctx.send(
            condition_fusion_agent.address,
            ItemAnalysisRequest(
                job_id=job.job_id,
                transcript=transcript,
                frame_paths=frames,
                video_path=msg.video_path,
            ),
        )

        await ctx.send(
            sender,
            StartJobResponse(
                job_id=job.job_id,
                status=JobStatus.ANALYZING.value,
                message=f"Extracted {len(frames)} frames, forwarding to analysis",
            ),
        )
    except Exception as e:
        ctx.logger.error(f"Intake failed: {e}")
        error_id = job.job_id if job else msg.job_id
        if error_id:
            try:
                await store.update_job_status(error_id, JobStatus.FAILED, error=str(e))
            except Exception:
                pass
        await ctx.send(
            sender,
            StartJobResponse(job_id=error_id or "", status="failed", message=str(e)),
        )


@intake_proto.on_message(model=ItemAnalysisResponse)
async def handle_analysis_done(ctx: Context, sender: str, msg: ItemAnalysisResponse):
    ctx.logger.info(f"Analysis complete for job {msg.job_id}: {msg.count} items found")


def create_intake_agent() -> Agent:
    agent = Agent(
        name="intake_agent",
        seed=settings.intake_agent_seed,
        port=8100,
        network="testnet",
    )
    agent.include(intake_proto)
    return agent
