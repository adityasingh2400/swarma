# Person 3: Server + Streaming + Intake (Strategy S2 Solidified)

**Author:** Aiden (Person 3)
**Date:** 2026-04-04
**Branch:** feat/native-fps-intake
**Status:** S2 (Flash-Lite + Image Snapshots) solidified as production pipeline. Audio pipeline integrated.

---

## What Was Built

Three core files. The I/O backbone of ReRoute v2: video goes in, screenshots come out.

| File | Purpose |
|------|---------|
| `backend/server.py` | FastAPI app, dual WS endpoints, REST routes, pipeline orchestration |
| `backend/streaming.py` | CDP screenshot capture, JPEG encoding, binary WS framing |
| `backend/intake.py` | Audio pipeline + Strategy S2: segment extraction, OpenCV filter, Flash-Lite analysis, per-item aggregation |
| `backend/config.py` | Updated with v2 settings (screenshot, intake, Browser-Use config) |

Experiment code (`backend/experiments.py`, `backend/templates/`) removed after Strategy S2 was validated as the best approach. Experiment documentation preserved in `AIDEN_PLAN/`.

`run.py:52` references `backend.server:app` and resolves to our v2 code with no changes needed.

---

## Architecture

```
VIDEO INPUT (POST /api/upload)
    |
    v
intake.py (streaming_analysis)
    |  Phase 0: Audio pipeline
    |    ffmpeg extract audio (16kHz mono WAV)
    |    Deepgram Nova-3 transcription
    |    Groq Llama 4 Scout → up to 3 item_ids
    |    (falls back to free-form detection if audio fails)
    |  Phase 1: Preprocess to 1080p30 H.264 (skip if compliant)
    |  Phase 2: 10*N parallel ffmpeg segment seeks
    |  Phase 3: OpenCV Laplacian sharpness filter (best per segment)
    |  Phase 4: Parallel Gemini 3.1 Flash-Lite (item-aware prompts)
    |  Phase 5: Arctic-Embed per-item aggregation
    |  Phase 6: Up to 4 best frames per item (histogram diversity, sharpness-ordered)
    |
    v  ItemCard objects
server.py (_run_pipeline)
    |  emit item:identified events
    |  call orchestrator.start_pipeline(job_id, items)
    |
    +---> _event_drain_loop
    |       reads orchestrator.events queue
    |       broadcasts JSON to /ws/{jobId}/events
    |
    +---> _screenshot_push_loop
            reads streaming.frame_store dict
            encodes binary frames
            broadcasts to /ws/{jobId}/screenshots
            throttles: 1fps grid, 3fps focused agent

streaming.py (capture_loop, per agent)
    |  CDP page.screenshot() at 2 fps
    |  asyncio.to_thread(encode_and_resize) -> grid + focus JPEG
    |  writes to frame_store[agent_id] = FrameData(grid, focus, ts)
```

---

## REST Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/upload` | Accept video (multipart), return `{ job_id, status }`, start pipeline |
| GET | `/api/jobs/{jobId}` | Job status and metadata |
| GET | `/api/jobs/{jobId}/agents` | All agent states (for WS reconnection state rebuild) |
| GET | `/api/jobs/{jobId}/items` | Full ItemCard details for a job |

## WebSocket Endpoints

| Path | Type | Purpose |
|------|------|---------|
| `/ws/{jobId}/events` | JSON text | Agent lifecycle events. Client sends `focus:request`/`focus:release` |
| `/ws/{jobId}/screenshots` | Binary | CDP screenshots. Server push only. |

---

## Binary Screenshot Protocol

Confirmed with Person 4. Exact byte layout:

```
[0x01] [32-byte utf8 agentId null-padded] [4-byte uint32 BE timestamp] [JPEG payload]
 ^            ^                                ^                          ^
 version      padded with \x00                 seconds since epoch        raw JPEG bytes
```

Header total: 37 bytes. Verified with unit test in this session.

---

## WS Event Types (Frozen Contract)

Server -> Client:
```json
{ "type": "agent:spawn",     "data": { "agentId", "platform", "phase", "task" } }
{ "type": "agent:status",    "data": { "agentId", "status", "detail?" } }
{ "type": "agent:error",     "data": { "agentId", "error" } }
{ "type": "agent:complete",  "data": { "agentId" } }
{ "type": "agent:result",    "data": { "agentId", "data" } }
{ "type": "item:identified", "data": { "itemId", "name", "confidence" } }
{ "type": "job:progress",    "data": { "stage", "detail" } }
{ "type": "initial_state",   "data": { "job", "agents" } }
```

Client -> Server (on events WS only):
```json
{ "type": "focus:request",  "agent_id": "xxx" }
{ "type": "focus:release",  "agent_id": "xxx" }
```

---

## Error Handling Decisions

All reviewed via `/plan-eng-review`.

### 1. Gemini API failures (intake.py)
- Retry once with 2s delay using a DIFFERENT round-robin key
- If retry fails, skip that frame batch and continue
- Log as warning, never block the pipeline
- If Gemini returns no items from a batch, that's normal, continue

### 2. WebSocket send failures (server.py)
- **Decision: Log warning + remove stale connection**
- `logger.warning()` with job_id for debuggability, then discard stale connection
- v1 pattern was silent removal, upgraded to include logging

### 3. Top-level pipeline guard (server.py `_run_pipeline`)
- **Decision: try/except that catches, logs, sets job FAILED, emits error event, does NOT re-raise**
- Server stays up after pipeline crash. Job shows FAILED in frontend.
- Background loops (event drain, screenshot push) are cancelled in `finally` block.

### 4. Insufficient frames (intake.py)
- **Decision: If < 3 frames extracted, fail the entire job**
- Raises `ValueError`, caught by pipeline guard, surfaces as FAILED job
- 3 is configurable via `settings.intake_min_frames_required`

### 5. ffmpeg failures (intake.py)
- If ffmpeg exits with error, log warning with last 500 chars of stderr
- Continue with whatever frames were extracted (may be 0, which triggers #4)

### 6. Video duration limit (intake.py)
- **Decision: Reject videos longer than 60 seconds**
- `ffprobe` checks duration before any frame extraction begins
- Raises `ValueError` with clear message ("Video is X.Xs, maximum allowed is 60s")
- Caught by pipeline guard, surfaces as FAILED job
- Limit is hardcoded as `MAX_VIDEO_DURATION_SEC = 60` in intake.py

---

## Assumptions and Stubs

### A1: Orchestrator Interface (STUBBED)
Person 1 (Aditya) builds the real orchestrator. Server builds against this interface:

```python
orchestrator.events                          # asyncio.Queue[dict]
orchestrator.get_browser(agent_id)           # -> Browser-Use Browser instance
await orchestrator.start_pipeline(job_id, items)  # kicks off agent spawning
orchestrator.get_agent_states(job_id)        # -> dict[agent_id, state]
```

The stub (`_OrchestratorStub` in server.py) emits fake `agent:spawn` events for 5 research agents per item. This is enough to test the WS pipeline end-to-end without the real orchestrator.

### A2: CDP Page Access (STUBBED)
`streaming.py:capture_loop()` takes a `get_page_fn` callable that returns a Playwright `Page`. How to extract this from Browser-Use's `Browser` object is not yet confirmed. The streaming-server-intake-review.md notes `get_browser()` returns a Browser-Use Browser, not a Playwright BrowserContext.

**Action needed:** Person 1 must confirm how to get a CDP-capable Page from a Browser-Use Browser. The stub accepts any async callable returning a Page or None.

### A3: Gemini Model Name
Strategy S2 uses a single model: `gemini-3.1-flash-lite-preview` (configurable via `settings.gemini_image_model`). The multi-model config (`gemini_detection_model`, `gemini_detail_model`) was removed when S2 was solidified as the sole strategy.

### A4: Gemini Rate Limits Are Per-Project
Per `gemini-pipeline-optimization.md`, round-robin across keys from the SAME GCP project gives zero additional throughput. The code round-robins across whatever keys are configured. **The actual rate limit benefit depends on keys being from separate GCP projects.** This is a deployment concern, not a code concern.

### A5: No Demo Caching in intake.py
The v1 `gemini.py` has elaborate demo caching (snapshot persistence, pre-computed results). The v2 intake pipeline is a fresh streaming architecture. Demo caching from v1 is not ported to `intake.py`. The v1 `gemini.py` and its snapshot logic remain untouched in the repo for backwards compatibility.

### A6: No Mock/Fallback Logic
All code paths hit real APIs. There is no `demo_mode` fallback in the new modules. If Gemini keys are not configured, the pipeline raises a clear error. This is intentional for a first draft. Mock data for demo reliability can be added later.

### A7: Single-Job Simplification
The in-memory job store (`_jobs` dict in server.py) has no persistence and no cleanup. Jobs accumulate in memory until server restart. Acceptable for a hackathon demo with a single user running a few pipelines.

### A8: Focus Mode is Global
`streaming_mod.focused_agent_id` is a single module-level variable. Only one agent can be focused at a time, and focus state is global across all WS clients. This matches the design doc's single-focus-mode behavior.

### A9: ffmpeg and ffprobe Must Be on PATH
`intake.py` shells out to `ffmpeg` (frame extraction) and `ffprobe` (duration check) via `asyncio.create_subprocess_exec`. Both must be installed and on the system PATH. No fallback if either is missing.

### A10: Gemini Key Alignment with .env
The .env defines `GEMINI_API_KEY` through `GEMINI_API_KEY_9` (9 keys total). `intake.py`'s `_GeminiPool` reads exactly these 9 keys. The v1 `gemini_api_key_10` field was removed from `config.py` during S2 solidification.

---

## Config Fields Added to `backend/config.py`

| Field | Default | Purpose |
|-------|---------|---------|
| `browser_use_api_key` | `""` | Browser-Use Cloud API key (for future use) |
| `max_concurrent_agents` | `12` | Max simultaneous browser agents |
| `context_pool_size` | `12` | Pre-warmed browser contexts |
| `screenshot_capture_fps` | `2.0` | CDP capture rate per agent |
| `screenshot_grid_quality` | `60` | JPEG quality for grid thumbnails |
| `screenshot_grid_width` | `320` | Grid thumbnail width |
| `screenshot_grid_height` | `240` | Grid thumbnail height |
| `screenshot_focus_quality` | `80` | JPEG quality for focus mode |
| `screenshot_focus_width` | `1280` | Focus mode width |
| `screenshot_focus_height` | `960` | Focus mode height |
| `screenshot_grid_delivery_fps` | `1.0` | WS delivery rate for grid agents |
| `screenshot_focus_delivery_fps` | `3.0` | WS delivery rate for focused agent |
| `intake_batch_size` | `5` | Frames per Gemini analysis batch |
| `intake_ffmpeg_fps` | `1.0` | ffmpeg frame extraction rate |
| `intake_min_frames_required` | `3` | Minimum frames before failing job |
| `gemini_image_model` | `gemini-3.1-flash-lite-preview` | Gemini model for S2 image analysis |

---

## What's NOT Here

- **Orchestrator** (Person 1): context pool, agent lifecycle, priority queue, retry
- **Playbooks** (Person 2): per-platform task string generators, route decision
- **Frontend** (Person 4): SwarmGrid, BrowserFeed, FocusMode, PipelineHeader
- **Tests**: No test files written. Test plan exists in the eng review.
- **Detail-tier Gemini calls**: intake.py only uses Flash-Lite for detection. The Flash-tier detail generation (title, description, pricing per item) is not implemented. This would run after detection, before listing agents.
- **Auth/cookie injection**: No browser profile or cookie management
- **Video strategies (S1/S3/S4)**: Removed after experiments showed S2 (Flash-Lite + images) was the most effective. Experiment documentation preserved in `AIDEN_PLAN/experiment-strategies.md` and `AIDEN_PLAN/experiments.md`.

---

## Integration Checklist

When Person 1's orchestrator is ready, wire up:

1. **Replace `_OrchestratorStub`** in server.py with the real orchestrator import
2. **Wire `capture_loop()`** in streaming.py to real Browser-Use browser pages via `orchestrator.get_browser(agent_id)`. Need to resolve how to get a Playwright Page from a Browser-Use Browser.
3. **Connect `start_pipeline()`** to the real orchestrator's agent spawning

When Person 2's playbooks are ready:
5. The orchestrator calls playbooks internally. No direct dependency from server/streaming/intake.

When Person 4's frontend connects:
6. Frontend connects to `/ws/{jobId}/events` and `/ws/{jobId}/screenshots`
7. Person 4's `useScreenshots.js` parser matches the binary protocol (confirmed)
8. Focus mode: frontend sends `focus:request`/`focus:release` on events WS

---

## .env Alignment

Person 3 modules read the following vars from `.env` (via `backend/config.py`):

| .env Variable | Config Field | Used By |
|---------------|-------------|---------|
| `BROWSER_USE_API_KEY` | `browser_use_api_key` | server.py (passed to orchestrator) |
| `MAX_CONCURRENT_AGENTS` | `max_concurrent_agents` | server.py (orchestrator pool size) |
| `GEMINI_API_KEY` | `gemini_api_key` | intake.py (`_GeminiPool` key 1) |
| `GEMINI_API_KEY_2` through `_9` | `gemini_api_key_2` ... `_9` | intake.py (`_GeminiPool` keys 2-9) |
| `DEEPGRAM_API_KEY` | `deepgram_api_key` | intake.py (audio transcription via Nova-3) |
| `GROQ_API_KEY` | `groq_api_key` | intake.py (Llama 4 Scout item parsing) |
| `API_HOST` | `api_host` | server.py (FastAPI bind address) |
| `API_PORT` | `api_port` | server.py (FastAPI bind port) |

Not consumed by Person 3 (out of scope):
- `USE_CLOUD` — orchestrator config (Person 1)
- `USE_CHAT_BROWSER_USE` — agent LLM selection (Person 1)
- `EBAY_COOKIES`, `FACEBOOK_COOKIES`, `MERCARI_COOKIES`, `DEPOP_COOKIES` — browser auth (Person 1/2)

Note: `config.py` retains `gemini_api_key_10` for v1 `services/gemini.py` compat. Our intake code reads keys 1-9 only, matching the .env.

---

## Considerations

- **Model warmup at startup**: Arctic-Embed and Gemini pool must be initialized during server lifespan startup (not lazily on first request). Cold-start latency on the first pipeline run is unacceptable for a demo — move `_gemini_pool._ensure_init()` and `_embed_pool._ensure_init()` into the FastAPI lifespan handler.
- **Gemini prompt tuning**: The current `_build_item_prompt` and `DETECTION_PROMPT` are functional but not optimized. The item-aware prompt in particular should be tested and iterated on for: condition assessment accuracy, bounding box tightness, spec extraction completeness, and null-return calibration (too aggressive = missed items, too lenient = noisy detections). The prompt is also padded to >=1024 tokens to activate Gemini's implicit context caching (per `gemini-pipeline-optimization.md`), so any edits must preserve that minimum length.
- **MUST: Add `DEEPGRAM_API_KEY` and `GROQ_API_KEY` to `.env`**. The audio pipeline (Deepgram Nova-3 transcription + Groq Llama 4 Scout item parsing) will fail without these keys. They are already in `.env.example` but must be populated with real values before running the pipeline. Without them, every request falls back to the free-form `DETECTION_PROMPT` (no item-aware prompts, no per-item aggregation).

---

## Verification Done

- All modified files pass Python AST syntax validation
- All imports resolve (config, models, streaming modules)
- `backend.server:app` import works, `run.py:52` resolves to v2 code
- Binary protocol encode/decode verified: version byte, 32-byte padded agent ID, uint32 BE timestamp, JPEG payload
- FastAPI app registers 4 REST routes + 2 WS endpoints (experiment/debug endpoints removed)
- .env variable alignment confirmed: intake.py reads Gemini keys 1-9, Deepgram key, Groq key
- No references to removed code (`gemini_detection_model`, `run_video_strategy`, `experiments`) remain in backend/
- Audio pipeline integrated into `streaming_analysis` with fallback logging when audio fails
- Frame selection is per-item (up to 4 diverse frames each, ordered by sharpness descending) — each ItemCard gets its own hero_frame_paths
