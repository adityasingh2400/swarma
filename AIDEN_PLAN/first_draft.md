# Person 3 First Draft: Server + Streaming + Intake

**Author:** Aiden (Person 3)
**Date:** 2026-04-04
**Branch:** main
**Status:** First draft, builds against stubs

---

## What Was Built

Four files, 1,314 lines total. The I/O backbone of ReRoute v2: video goes in, screenshots come out.

| File | Lines | Purpose |
|------|-------|---------|
| `backend/server.py` | 490 | FastAPI app, dual WS endpoints, REST routes, pipeline orchestration |
| `backend/streaming.py` | 194 | CDP screenshot capture, JPEG encoding, binary WS framing |
| `backend/intake.py` | 555 | Streaming ffmpeg extraction, Gemini batch analysis, image pipeline, video duration validation |
| `backend/config.py` | 109 | Updated with v2 settings (screenshot, intake, Browser-Use config) |

Replaces the v1 `server.py` (which was already deleted from the working tree). `run.py:52` references `backend.server:app` and resolves to our v2 code with no changes needed.

---

## Architecture

```
VIDEO INPUT (POST /api/upload)
    |
    v
intake.py
    |  ffprobe duration check (reject >31s)
    |  ffmpeg -f image2pipe (streaming, 1 fps)
    |  -> collect 5-frame batches
    |  -> fan-out to Gemini Flash-Lite (parallel, round-robin keys)
    |  -> deduplicate items across batches
    |  -> crop/resize listing images
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
- **Decision: Reject videos longer than 31 seconds**
- `ffprobe` checks duration before any frame extraction begins
- Raises `ValueError` with clear message ("Video is X.Xs, maximum allowed is 31s")
- Caught by pipeline guard, surfaces as FAILED job
- Limit is hardcoded as `MAX_VIDEO_DURATION_SEC = 31` in intake.py

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

### A3: Gemini Model Names
Using model IDs from the design doc as defaults:
- Detection: `gemini-2.5-flash-lite-preview-06-17`
- Detail: `gemini-2.5-flash-preview-05-20`

These are configurable via `settings.gemini_detection_model` and `settings.gemini_detail_model`. If the preview model IDs change or aren't available, update `.env`.

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
The .env defines `GEMINI_API_KEY` through `GEMINI_API_KEY_9` (9 keys total). `intake.py`'s `_GeminiPool` reads exactly these 9 keys. `config.py` retains a `gemini_api_key_10` field for v1 `services/gemini.py` backwards compatibility, but our v2 intake code does not reference it.

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
| `gemini_detection_model` | `gemini-2.5-flash-lite-preview-06-17` | Model for frame batch analysis |
| `gemini_detail_model` | `gemini-2.5-flash-preview-05-20` | Model for item detail generation |

---

## What's NOT Here

- **Orchestrator** (Person 1): context pool, agent lifecycle, priority queue, retry
- **Playbooks** (Person 2): per-platform task string generators, route decision
- **Frontend** (Person 4): SwarmGrid, BrowserFeed, FocusMode, PipelineHeader
- **Tests**: No test files written. Test plan exists in the eng review.
- **Detail-tier Gemini calls**: intake.py only uses Flash-Lite for detection. The Flash-tier detail generation (title, description, pricing per item) is not implemented. This would run after detection, before listing agents.
- **Auth/cookie injection**: No browser profile or cookie management
- **Transcript extraction**: v1's audio transcript pipeline is not ported. The v2 detection prompt analyzes frames only (no audio).

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
| `API_HOST` | `api_host` | server.py (FastAPI bind address) |
| `API_PORT` | `api_port` | server.py (FastAPI bind port) |

Not consumed by Person 3 (out of scope):
- `USE_CLOUD` — orchestrator config (Person 1)
- `USE_CHAT_BROWSER_USE` — agent LLM selection (Person 1)
- `EBAY_COOKIES`, `FACEBOOK_COOKIES`, `MERCARI_COOKIES`, `DEPOP_COOKIES` — browser auth (Person 1/2)

Note: `config.py` retains `gemini_api_key_10` for v1 `services/gemini.py` compat. Our intake code reads keys 1-9 only, matching the .env.

---

## Verification Done

- All 4 files pass Python AST syntax validation
- All imports resolve (config, models, streaming modules)
- `backend.server:app` import works, `run.py:52` resolves to v2 code
- Binary protocol encode/decode verified: version byte, 32-byte padded agent ID, uint32 BE timestamp, JPEG payload
- FastAPI app registers all 5 REST routes + 2 WS endpoints correctly (9 total with OpenAPI)
- .env variable alignment confirmed: intake.py reads keys 1-9, config retains key_10 for v1 compat only
