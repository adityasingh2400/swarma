# Eng Review: Streaming Intake + Fanout Server Architecture

**Branch:** main | **Repo:** swarma | **Date:** 2026-04-04
**Focus:** Should `streaming.py`, `server.py`, and `intake.py` share a module? Speed-first analysis.
**Design doc:** `ReRoute-V2-Design-Doc.md` | **Eng plan:** `ReRoute-V2-Eng-Plan.md`

---

## Step 0: Scope Challenge

**What's actually being asked:** The eng plan already splits Person 3's work into three files:
- `server.py` — FastAPI routes + 2 WS endpoints (<200 lines)
- `streaming.py` — CDP screenshot capture loops, binary framing
- `intake.py` — Video upload, streaming ffmpeg, Gemini analysis

The question: should these be one file or three? And more deeply: what's the fastest architecture for the data path from video input to browser screenshot output?

**Complexity check:** 3 files, 0 new classes beyond what's already planned. Well within bounds.

**What already exists:** v1's `ConnectionManager` class (server.py:127-159), `useWebSocket.js` hook, `gemini.py` service, `media.py` service. All reusable.

---

## Decisions Made

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Keep 3 separate modules** | Module boundary = zero runtime cost. Same process, same event loop. Build parallelism for 4-person team. |
| 2 | **Flat in `backend/`** | 6 backend files total. No subdirectory ceremony for a hackathon. |
| 3 | **Ring buffer (dict) instead of asyncio.Queue** for screenshots | Latest frame always wins. No stale accumulation. `frame_store[agent_id] = FrameData(grid, focus, ts)` |
| 4 | **JPEG encode offloaded to thread pool** | `asyncio.to_thread(encode_and_resize, png)`. Event loop coroutine writes to frame_store (not the thread). Recovers 5-12% event loop budget. |
| 5 | **Event loop thread owns frame_store writes** | Thread pool returns encoded bytes. Coroutine writes to dict. Zero race conditions. |
| 6 | **uvloop** in `run.py` | Free ~2x WebSocket throughput. One line. |

## Architecture (Revised)

```
intake.py                                    streaming.py
─────────                                    ────────────
ffmpeg -i video.mp4 -f image2pipe       ┌─→ CDP.Page.captureScreenshot()
  │  (streaming, not batch)             │     every 500ms per agent
  ▼                                     │     │
Gemini analyze(frames[0:5])             │     ▼
  │  (3-5 frames at a time)            │   asyncio.to_thread(encode_and_resize)
  ▼                                     │     │  (thread pool: PIL resize + JPEG encode)
ItemCard emitted                        │     ▼
  │                                     │   frame_store[agent_id] = {
  ▼                                     │     grid: bytes,  # 320x240 q60 ~20KB
orchestrator.spawn_agents(item)         │     focus: bytes,  # 1280x960 q80 ~100KB
  │                                     │     ts: float
  ├─ acquire context from pool          │   }
  ├─ start Browser-Use agent ───────────┘
  ├─ emit AgentEvent to event_queue ──────────────────┐
  │                                                    │
  │                                                    ▼
  │                                              server.py (<200 lines)
  │                                              ─────────
  │                                              /ws/{jobId}/events
  │                                                reads event_queue → JSON text frames
  │                                              /ws/{jobId}/screenshots
  │                                                reads frame_store[agent_id] → binary frames
  │                                                1fps grid, 3fps focused agent
  │
  └─ on complete: recycle context, emit event
```

**Three async loops, three files, one process, one event loop.** Module boundary is invisible at runtime.

## File Hierarchy

```
reroute-v2/
├── backend/
│   ├── server.py         ← FastAPI + 2 WS endpoints (<200 lines)
│   ├── streaming.py      ← CDP capture loop + thread pool JPEG encode
│   ├── intake.py         ← ffmpeg pipe + Gemini batch analysis
│   ├── orchestrator.py   ← Agent lifecycle + context pool
│   ├── route_decision.py ← Scoring algorithm
│   ├── config.py
│   ├── playbooks/        ← Per-platform task generators
│   ├── services/         ← gemini.py, media.py (from v1)
│   ├── systems/          ← listing_asset_optimization.py (from v1)
│   ├── models/           ← ItemCard, Job, etc. (from v1)
│   └── storage/          ← store.py (from v1)
├── frontend/
└── run.py                ← uvloop.install() + uvicorn
```

## What Already Exists (reuse from v1)

| Existing code | Reuse in | Changes needed |
|---|---|---|
| v1 `ConnectionManager` (server.py:127-159) | `server.py` | Extend for dual WS endpoints |
| v1 `gemini.py` | `intake.py` imports | Remove demo caching/mocks |
| v1 `media.py` | `intake.py` imports | None |
| v1 `useWebSocket.js` | Frontend | None |

## NOT in Scope

- Multi-process architecture (single process is correct for hackathon)
- WebSocket authentication (localhost demo)
- WebSocket backpressure / send timeout (accepted risk for hackathon, 1-2 clients)
- Top-level catch-all exception handlers (relying on per-module error handling)
- Redis pub/sub for horizontal scaling (single machine)

## Speed-Critical Path Timing

| Step | Time | Bottleneck |
|---|---|---|
| ffmpeg first frame extraction | ~500ms | Disk I/O + codec init |
| Gemini first batch (3-5 frames) | ~2-3s | Network to Gemini API |
| First agent spawn | ~1-2s | Browser context acquire + navigate |
| First CDP screenshot | ~500ms | Page render + capture |
| Screenshot encode + resize | ~3-5ms | CPU (in thread pool) |
| Ring buffer write + read | ~0.001ms | In-memory dict |
| WebSocket binary send | ~1-2ms | Network (localhost) |
| **Total: video → first screenshot** | **~5-8s** | Gemini API dominates |

## Outside Voice Summary

Independent Claude subagent reviewed the architecture. 8 findings:
- Points 1, 3, 5, 7, 8: Already addressed by eng plan (Step 0 benchmarking, Gemini error handling, marketplace playbooks, CAPTCHA strategy)
- Point 2 (frame_store thread safety): Resolved by decision #5 above (event loop thread writes)
- Point 4 (WS backpressure): User chose to skip for hackathon
- Point 6 (crash isolation): User chose to rely on per-module error handling

No cross-model tension remaining.

## Completion Summary

- Step 0: Scope Challenge — scope accepted as-is (3 modules, well within complexity bounds)
- Architecture Review: 3 issues found, all resolved (module split, ring buffer, thread pool)
- Code Quality Review: 1 issue found, resolved (JPEG encode blocking event loop)
- Test Review: 21 paths identified, 8 covered by planned tests. Thread safety pattern documented.
- Performance Review: 1 optimization added (uvloop). Gemini API is 1000x the bottleneck vs module overhead.
- Outside voice: ran (Claude subagent), 2 tension points presented, user chose to skip both
- NOT in scope: written (5 items deferred)
- What already exists: written (4 v1 files reusable)

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR (PLAN) | 4 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |
| Outside Voice | `/plan-eng-review` | Independent plan challenge | 1 | issues_found (claude) | 8 findings, 2 presented, 0 accepted |

**VERDICT:** ENG CLEARED — ready to implement.

## Resolved Interface Agreements (2026-04-04)

The following interface conflicts from the conflict map are now resolved. Person 1 (Aditya) and Person 4 (Frontend) confirmed exact specs.

### Agreement 1: Orchestrator ↔ Server Interface — RESOLVED

Person 1 confirmed the interface. Two naming changes from original proposal:

```python
# CONFIRMED interface (from Person 1):
orchestrator.events          # asyncio.Queue[AgentEvent] — was "event_queue"
orchestrator.get_browser(agent_id)  # Returns Browser-Use Browser instance — was "get_context"
await orchestrator.start_pipeline(job_id, items)  # Direct method call, unchanged

# AgentEvent and AgentState already in contracts.py on feat/orchestrator branch.
# Fields match proposal plus:
#   - "agent:result" event type added
#   - "retrying" status added to AgentState
```

**Key difference:** `get_browser()` returns a Browser-Use Browser instance, NOT a Playwright BrowserContext. Running on Browser-Use Cloud (remote browsers). Person 3 needs CDP access from the Browser object (via its CDP URL).

**Drain pattern confirmed:**
```python
while True:
    event = await orchestrator.events.get()
    await ws_manager.broadcast_json(event)
```

### Agreement 2: Binary Screenshot Protocol — RESOLVED

Person 4 confirmed exact byte layout. Parser already built in `useScreenshots.js`:

```
Frame: [0x01][32-byte utf8 agentId null-padded][4-byte uint32 BE timestamp][JPEG bytes]
Header total: 37 bytes
```

Frontend parsing (confirmed working):
- `DataView` + `TextDecoder` + `Uint8Array` slicing
- Version byte ≠ 0x01 → dropped
- Buffer < 37 bytes → dropped
- Empty JPEG payload → dropped
- Out-of-order → latest wins (Map keyed by agent ID, previous blob URL revoked)
- Garbage JPEG → `<img>` shows pulse placeholder until valid frame arrives

Person 4 requests a reference test frame (Node script emitting a hardcoded frame with known agentId + small JPEG) for end-to-end decoder validation.

### Agreement 3: WS Event Type Strings — RESOLVED

Person 4 confirmed all events with exact `data` field usage:

| Event | Fields read from `data` | UI behavior |
|---|---|---|
| `agent:spawn` | `agentId`, `platform`, `phase`, `task` | New card animates in (spring, 0.02s stagger) |
| `agent:status` | `agentId`, `status`, `detail` (optional) | Card updates status label. Active = accent glow |
| `agent:error` | `agentId`, `error` (string) | Red glow, AlertCircle icon, error in FocusMode |
| `agent:complete` | `agentId` | Card stays with "Complete" label. Glow stops |
| `agent:result` | `agentId`, `data` (arbitrary) | Stored in agent.result, not rendered on grid |
| `item:identified` | `itemId`, `name`, `confidence` | Already handled |

**Additional events Person 4 requests (nice-to-have):**
1. `job:progress` — overall pipeline percentage or stage name
2. `state:snapshot` — full state dump on WS reconnect: `{ v2Agents: { [agentId]: AgentState }, pipelineStage: string }`

**Frozen contract (exact payload shapes):**
```js
// Server → Client events
{ type: "agent:spawn",     data: { agentId: string, platform: string, phase: string, task: string } }
{ type: "agent:status",    data: { agentId: string, status: string, detail?: string } }
{ type: "agent:error",     data: { agentId: string, error: string } }
{ type: "agent:complete",  data: { agentId: string } }
{ type: "agent:result",    data: { agentId: string, data: any } }
{ type: "item:identified", data: { itemId: string, name: string, confidence: number } }

// Client → Server events
{ type: "focus:request",  agent_id: string }
{ type: "focus:release",  agent_id: string }
```

### Agreement 4: Gemini Service Signatures — UNCHANGED

Frozen signatures still hold. No changes from Person 1 or Person 4.

### Agreement 5: Config Fields — RESOLVED

Person 1 confirmed `browser_use_api_key` and `max_concurrent_agents` already in config.py. Screenshot configs (`screenshot_fps`, `screenshot_grid_quality`, `screenshot_focus_quality`) are Person 3's to add directly — no conflict.

### Focus Mode Protocol — CONFIRMED

- Trigger: Click any SwarmGrid card
- Client → Server: `{ type: "focus:request", agent_id: "xxx" }` on enter
- Client → Server: `{ type: "focus:release", agent_id: "xxx" }` on close (ESC or backdrop)
- No server ACK needed (Person 4 shows panel optimistically)
- FPS: 5-10 during focus, 1-2 per agent during grid mode
- Display: Single large screenshot overlay, grid dims to 0.3 opacity, FLIP animation via Framer Motion `layoutId`

### REST API Shape — CONFIRMED

v2 endpoint `GET /api/jobs/{jobId}/agents`:
```json
{
  "agents": {
    "ebay-research-0": {
      "agent_id": "ebay-research-0",
      "platform": "ebay",
      "phase": "research",
      "status": "running",
      "task": "Searching for iPhone 15 Pro listings",
      "started_at": 1712345678.0,
      "completed_at": null,
      "result": null,
      "error": null
    }
  }
}
```

Upload flow: `POST /api/upload` (multipart, field: `video`) → `{ "job_id": "xxx", "status": "processing" }` → WS connect to `/ws/{jobId}`. No max file size enforced on frontend.

### Reconnection Strategy — CONFIRMED (Option C)

1. On WS disconnect → auto-reconnect with 2s delay
2. On reconnect → `GET /api/jobs/{jobId}` to rebuild full state
3. Backend sends `initial_state` event on WS connect
4. Resume receiving live events
5. `state:snapshot` event on reconnect (ideal v2 path) would be cleanest

---

## Conflict Resolution Summary

All 5 Phase 0 agreements from the interface conflict map are now resolved:

| Agreement | Status | Key Changes from Original Spec |
|-----------|--------|-------------------------------|
| 1. Orchestrator ↔ Server | RESOLVED | `event_queue` → `events`, `get_context` → `get_browser` (Browser not BrowserContext) |
| 2. Binary Screenshot Protocol | RESOLVED | Exact match. Person 4 parser already built. |
| 3. WS Event Types | RESOLVED | All confirmed. Person 4 requests `job:progress` + `state:snapshot` additions. |
| 4. Gemini Signatures | UNCHANGED | Frozen as proposed. |
| 5. Config Fields | RESOLVED | `browser_use_api_key` + `max_concurrent_agents` exist. Screenshot configs are Person 3's. |

**Interface conflict map (`interface-conflict-map.md`) deleted — all conflicts resolved.**

---

## Verification

1. After building, benchmark `streaming.py` in isolation: 12 concurrent capture loops, measure actual fps and memory
2. Verify frame_store reads in server.py always get latest frame (not stale)
3. Verify JPEG encode doesn't block event loop (check event loop slow callback warnings with `PYTHONASYNCIODEBUG=1`)
4. Full pipeline: video upload → first screenshot in browser devtools within 8s
