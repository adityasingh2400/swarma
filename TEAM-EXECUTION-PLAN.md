# Team Execution Plan: ReRoute v2 — 4-Person Hackathon Build

## Context

ReRoute v2 replaces Fetch AI uAgents with Browser-Use for live browser agent swarm visualization. The design doc and eng plan are finalized at `~/.gstack/projects/adityasingh2400-ReRoute/`. 4 people, each with Claude Opus 4.6 instances, building simultaneously tomorrow morning. Goal: maximize parallelism so 4 people = 4x output with minimal merge conflicts and maximum overlap.

## Strategy: Two Pairs, Four Streams, Zero Conflicts

The pipeline splits naturally into two halves with clean file boundaries:

```
VIDEO → [Intake] → [Orchestrator + Playbooks] → [Streaming + Server] → [Frontend]
              ↑              ↑                          ↑                    ↑
           Person 3       Person 1 + 2               Person 3            Person 4
```

**Pair A (Backend Core):** Person 1 + Person 2 — Agent execution layer
**Pair B (Visualization):** Person 3 + Person 4 — Data pipeline + display

Within each pair, people work on overlapping phases but **different files** = zero merge conflicts. Across pairs, the interface is one clean boundary: orchestrator emits events → server relays → frontend renders.

---

## The Four Workstreams

### Person 1 (Aditya): Orchestrator + Scaffold Lead

**Files owned:** `orchestrator.py`, `config.py`, `models/*`, `storage/*`, `run.py`, `.env.example`, `requirements.txt`

This is the brain. Context pool management, agent lifecycle, priority queue, retry logic, event emission. Person 1 also owns the scaffold (Phase 0) and the interface contracts that everyone builds against.

**What to build:**
- Browser context pool: `create_pool()`, `acquire()`, `release()`, `recycle()` — pre-warm N contexts on startup, cookie-inject per platform
- Agent lifecycle: `spawn_agent(item, playbook, phase)` → creates Browser-Use Agent with playbook task string, monitors completion
- Priority queue: research agents before listing agents, item 1 before item 2, max N concurrent
- Event emission: every state change → `AgentEvent` pushed to an asyncio queue that Person 3's server drains
- Retry: on agent failure, retry once after 3s. If retry fails, mark BLOCKED, return context to pool
- Context recycling: after each agent completes, close context, create fresh one

**Success criteria:**
- `Orchestrator.start_pipeline(job_id, items)` spawns research agents for all items, respecting pool size
- Research completion triggers `route_decision()` → listing agent dispatch
- Events emitted for every lifecycle transition
- Tests: `test_orchestrator.py` (queue priority, retry, pool exhaustion)

---

### Person 2: Playbooks + Route Decision

**Files owned:** `playbooks/base.py`, `playbooks/ebay.py`, `playbooks/facebook.py`, `playbooks/mercari.py`, `playbooks/depop.py`, `route_decision.py`, `tests/test_playbooks.py`, `tests/test_route_decision.py`

This is the marketplace intelligence. Each playbook generates the hybrid task string that Browser-Use agents execute. Research playbooks tell agents what to search for. Listing playbooks tell agents exactly how to fill forms. Route decision scores research results and picks platforms.

**What to build:**

**Playbook base class:**
```python
class Playbook(ABC):
    platform: str  # "ebay", "facebook", "mercari", "depop"
    
    @abstractmethod
    def research_task(self, item: ItemCard) -> str:
        """Generate Browser-Use task string for price research."""
    
    @abstractmethod
    def listing_task(self, item: ItemCard, package: ListingPackage) -> str:
        """Generate Browser-Use task string for form-filling."""
    
    @abstractmethod
    def parse_research(self, result: str) -> dict:
        """Extract structured data from agent's research output."""
```

**Per-platform playbooks** (the big work — 4 independent playbooks):
- **eBay** (`ebay.py`): Research = search sold listings on `ebay.com/sch/` with `LH_Complete=1&LH_Sold=1`. Listing = navigate `ebay.com/sell`, fill title (80 char max), search-select category, set condition, upload images via `set_input_files()`, set price, select shipping, click "List it"
- **Facebook** (`facebook.py`): Research = search `facebook.com/marketplace/` for comps. Listing = navigate `facebook.com/marketplace/create/item`, upload photos, fill title/price/category/condition/description
- **Mercari** (`mercari.py`): Research = search `mercari.com/search/` for price comps. Listing = navigate `mercari.com/sell`, upload photos (first = thumbnail), fill title/description, 3-level category selection, brand search-select, condition radio buttons, set price/shipping
- **Depop** (`depop.py`): Research = search `depop.com/search/`. Listing = navigate `depop.com/products/create`, upload photos (max 4), fill description (primary search field, no separate title), category/brand/size/condition/price

**Route decision** (`route_decision.py`):
- Extract `_score_bid()` from v1's `backend/agents/route_decider_agent.py` as a pure function
- Weighted scoring: 45% value, 25% confidence, 15% effort, 15% speed
- Input: list of research results per platform → Output: ranked platforms + recommended prices
- v1 reference: `_EFFORT_SCORES`, `_SPEED_SCORES` dicts, `_score_bid()` function at line 38

**Success criteria:**
- Each playbook generates valid task strings from an ItemCard
- eBay playbook tested against real eBay (8/10 success target)
- Route decision produces correct rankings from mock research data
- Tests: `test_playbooks.py` (task string validation), `test_route_decision.py` (scoring math)

---

### Person 3: Server + Streaming + Intake

**Files owned:** `server.py`, `streaming.py`, `intake.py`, `services/gemini.py` (adapted from v1), `services/media.py` (copy from v1), `systems/listing_asset_optimization.py` (copy from v1), `tests/test_ws_protocol.py`, `tests/test_intake.py`, `tests/test_image_pipeline.py`, `tests/test_auth.py`

This is the I/O backbone. Video goes in, screenshots come out. Three sub-systems: video intake (ffmpeg + Gemini), CDP screenshot streaming, and the FastAPI server with dual WebSocket endpoints.

**What to build:**

**server.py** (<200 lines):
- FastAPI app with lifespan (init orchestrator, warm context pool)
- REST: `POST /api/upload`, `GET /api/jobs/{jobId}`, `GET /api/jobs/{jobId}/agents`
- WS endpoint 1: `/ws/{jobId}/events` — JSON text frames (agent lifecycle events)
- WS endpoint 2: `/ws/{jobId}/screenshots` — binary frames (CDP screenshots)
- Copy `ConnectionManager` from v1 `backend/server.py:127-159`, extend for dual WS
- Focus mode: client sends `focus:request`/`focus:release` on events WS, server adjusts screenshot delivery rate

**streaming.py** (CDP screenshot capture):
- `ScreenshotStreamer` class: given a browser context, captures CDP screenshots at 2 fps
- Thumbnail generation: grid = 320x240 JPEG q60 (~20KB), focus = 1280x960 JPEG q80 (~100KB)
- Delivery throttling: grid agents at 1 fps, focused agent at 3 fps
- Binary frame format: `[0x01][32-byte agentId utf8-padded][4-byte uint32 timestamp][JPEG payload]`

**intake.py** (video → items):
- Video upload handler: save to `data/uploads/`, start processing
- Streaming ffmpeg extraction: pipe frames out as they're extracted (not batch)
- Gemini batch analysis: send 3-5 frames at a time to Gemini, get ItemCards back
- Image pipeline: select best frames per item, crop to bounding box, resize to marketplace-optimal (1600x1600 eBay, 1080x1080 others), save to `data/listing-images/{item_id}/`
- Adapt `services/gemini.py` from v1: keep `GeminiService` class + round-robin keys + `analyze_video()` + `search_platform()` + `generate_listing()`. Remove all demo caching/snapshot/mock logic.

**Success criteria:**
- Binary WS frame correctly encodes/decodes agent screenshots
- Video upload → first ItemCard emitted within 5-8 seconds
- Screenshot stream visible in browser devtools
- Tests: `test_ws_protocol.py` (binary parsing), `test_intake.py` (Gemini analysis), `test_image_pipeline.py` (JPEG generation), `test_auth.py` (cookie injection)

---

### Person 4: Frontend

**Files owned:** entire `frontend/` directory

This is the spectacle. The live swarm grid, the focus mode drill-in, the pipeline progress bar. Everything the audience sees.

**What to build:**

**Hooks:**
- `useScreenshots.js` (NEW): Connect to binary WS `/ws/{jobId}/screenshots`, parse binary frames (extract agentId + timestamp + JPEG blob), maintain `Map<agentId, latestImageUrl>` via `URL.createObjectURL()`, clean up old blob URLs
- `useJob.js` (adapt from v1): Add agent state tracking for v2 events (`agent:spawn`, `agent:status`, `agent:result`, `agent:complete`, `agent:error`), track pipeline stages (intake → research → decision → listing), track per-agent metadata (platform, phase, task description, elapsed time)
- `useWebSocket.js` (copy from v1 as-is)

**Components:**
- `SwarmGrid.jsx` (NEW): Responsive 3x4 or 4x4 grid. Each cell = one agent card showing: platform icon, phase badge (research/listing), status text, live browser thumbnail from `useScreenshots`. Click any card → FocusMode. Spawn animation when new agent appears. Red border + error icon on failure. "Queued" state for waiting agents.
- `BrowserFeed.jsx` (NEW): Renders a single agent's screenshot stream as an `<img>` tag with src from useScreenshots blob URL. Smooth transition between frames. Loading state before first frame arrives.
- `FocusMode.jsx` (NEW): Full-screen overlay triggered by clicking a SwarmGrid card. Shows large BrowserFeed (1280x960), agent task description, elapsed time, platform. ESC or click outside to close. Sends `focus:request`/`focus:release` over events WS to get higher FPS.
- `PipelineHeader.jsx` (NEW): Horizontal progress bar: Video → Analysis → Research → Decision → Listing. Each stage lights up as the pipeline progresses. Shows counts (e.g., "3/5 research agents done").
- `Layout.jsx` (adapt from v1): Top = PipelineHeader, Center = SwarmGrid (fills most of screen), FocusMode as overlay
- Copy from v1: `components/shared/*` (AnimatedValue, Badge, Card, ProgressRing)

**Design system** (`index.css`):
- Start with a clean dark theme (placeholder — refine in Phase 3)
- Grid layout with CSS Grid for SwarmGrid
- Glass-morphism cards (v1's Card component already has this)

**Success criteria:**
- SwarmGrid renders 12 agent cards with placeholder data
- Binary WS screenshots appear as live thumbnails
- Click card → FocusMode with larger feed
- PipelineHeader reflects current stage
- Works with mock data before backend is ready

---

## Interface Contracts (Define in Phase 0)

These go in a shared `contracts.py` (backend) and `contracts.js` (frontend) so everyone builds against the same types:

### Agent Events (Person 1 emits → Person 3 relays → Person 4 renders)
```python
# backend/contracts.py
class AgentEvent(BaseModel):
    type: str  # "agent:spawn" | "agent:status" | "agent:result" | "agent:complete" | "agent:error"
    agent_id: str
    timestamp: float
    data: dict

class AgentState(BaseModel):
    agent_id: str
    item_id: str
    platform: str  # "ebay" | "facebook" | "mercari" | "depop"
    phase: str  # "research" | "listing"
    status: str  # "queued" | "running" | "navigating" | "filling" | "complete" | "error" | "blocked"
    task: str  # human-readable description
    started_at: float | None
    completed_at: float | None
    result: dict | None
    error: str | None
```

### Binary Screenshot Protocol (Person 3 encodes → Person 4 decodes)
```
Frame: [1 byte: 0x01] [32 bytes: agentId utf8 padded] [4 bytes: timestamp uint32 BE] [rest: JPEG]
```

### Orchestrator → Server Interface (Person 1 produces → Person 3 consumes)
```python
# Orchestrator exposes an asyncio.Queue[AgentEvent] that server.py drains
# Orchestrator exposes get_context(agent_id) → BrowserContext for screenshot capture
```

### Playbook Interface (Person 2 implements → Person 1 calls)
```python
class Playbook(ABC):
    platform: str
    def research_task(self, item: ItemCard) -> str
    def listing_task(self, item: ItemCard, package: ListingPackage) -> str
    def parse_research(self, result: str) -> dict
```

---

## Phased Timeline

### Phase 0: Scaffold + Contracts (30 min) — Person 1 leads

**Person 1 (Aditya):**
- Create new `reroute-v2/` project folder (or new branch/directory in current repo)
- Copy v1 reusable code: `models/*`, `storage/store.py`, `services/media.py`, `systems/listing_asset_optimization.py`
- Set up `requirements.txt` (browser-use, playwright, fastapi, uvicorn, google-genai, Pillow, ffmpeg-python)
- Set up `frontend/package.json` (react 19, framer-motion, lucide-react, vite)
- Write `contracts.py` with all shared types (AgentEvent, AgentState, Playbook ABC)
- Write `.env.example` with all required keys
- Push to repo

**Everyone else:**
- Clone, `pip install -r requirements.txt`, `cd frontend && npm install`
- Read design doc + this plan
- Review the interface contracts in `contracts.py`

### Phase 1: Parallel Build (2.5 hours) — All 4 simultaneous

All 4 people build their workstream against the agreed contracts. **Each person gives their Claude Opus instance the full design doc + their workstream section from this plan.** Claude builds the code, person reviews + tests.

**What each Claude instance should be told:**
- Person 1's Claude: "Build orchestrator.py. Here's the design doc [paste]. Here's the contracts [paste]. Build context pool, agent lifecycle, priority queue, event emission. Here are the v1 models to reference [paste item_card.py, route_bid.py]."
- Person 2's Claude: "Build all 4 marketplace playbooks + route_decision.py. Here's the design doc section on playbooks [paste]. Here's the base class [paste contracts.py]. Here's the v1 route_decider_agent.py to extract scoring from [paste]. Build eBay, Facebook, Mercari, Depop playbooks with hybrid structured task strings."
- Person 3's Claude: "Build server.py + streaming.py + intake.py. Here's the design doc [paste]. Here's the WS protocol [paste]. Here's v1 server.py ConnectionManager to copy [paste]. Here's v1 gemini.py to adapt [paste]. Build FastAPI server with dual WS, CDP screenshot capture, video intake pipeline."
- Person 4's Claude: "Build the React frontend. Here's the design doc frontend section [paste]. Here's the WS protocol [paste]. Here's v1 useWebSocket.js to copy [paste], useJob.js to adapt [paste], shared components to copy [paste]. Build SwarmGrid, BrowserFeed, FocusMode, PipelineHeader, useScreenshots hook."

### Phase 2: Integration (1.5 hours) — Pair up

**Pair A (Person 1 + 2): Orchestrator ↔ Playbooks**
- Wire `orchestrator.spawn_agent()` to call `playbook.research_task()` / `listing_task()`
- Wire research completion → `route_decision.decide()` → listing dispatch
- Test: ItemCard → 5 research agents spawn → results → route decision → 3 listing agents spawn
- Fix any interface mismatches

**Pair B (Person 3 + 4): Server ↔ Frontend**
- Frontend connects to both WS endpoints
- SwarmGrid receives agent events + screenshot frames
- Test: mock agent in backend → screenshots visible in grid → click → focus mode works
- Fix any protocol mismatches

### Phase 3: Full Pipeline + Polish (1.5 hours)

**Person 1 + 3: End-to-end pipeline**
- Wire intake → orchestrator → streaming → server
- Scale to 12+ concurrent agents, tune memory/FPS
- Full flow: video upload → items identified → agents visible → research → decision → listing

**Person 2 + 4: Polish + reliability**
- Design system (run `/design-consultation` or apply a clean dark theme)
- Animations: agent spawn effects, pipeline transitions, focus mode zoom
- Playbook reliability: test each platform, tune task strings, add error recovery
- PipelineHeader accuracy: make stage transitions match real pipeline state

### Phase 4: Demo Prep (30 min) — All 4

- Pre-authenticate marketplace accounts (eBay, Facebook, Mercari, Depop) — export cookies
- Full pipeline test 5x with real video
- Identify flaky platforms, prepare graceful degradation order
- Record backup demo video (insurance)

---

## Git Strategy

**Option A (simpler):** Everyone works on `main`, different files = no conflicts. Pull before push.

**Option B (safer):** 4 feature branches:
- `feat/orchestrator` (Person 1)
- `feat/playbooks` (Person 2)
- `feat/server-streaming` (Person 3)
- `feat/frontend` (Person 4)

Merge into `main` at Phase 2 start. Since files don't overlap, merges will be clean.

**Recommendation:** Option A. It's a hackathon, speed > process. The file boundaries are clean enough.

---

## v1 Files Reference (for copying)

| v1 File | Copy to | Changes |
|---------|---------|---------|
| `backend/models/item_card.py` | `models/item_card.py` | None |
| `backend/models/job.py` | `models/job.py` | None |
| `backend/models/listing_package.py` | `models/listing_package.py` | None |
| `backend/models/route_bid.py` | `models/route_bid.py` | None |
| `backend/models/conversation.py` | `models/conversation.py` | None |
| `backend/storage/store.py` | `storage/store.py` | Minor renames |
| `backend/services/media.py` | `services/media.py` | None |
| `backend/systems/listing_asset_optimization.py` | `systems/listing_asset_optimization.py` | None |
| `backend/config.py` | `config.py` | Remove agent seeds, add BROWSER_USE_API_KEY, CONTEXT_POOL_SIZE |
| `backend/services/gemini.py` | `services/gemini.py` | Remove demo caching/snapshots/mocks |
| `backend/agents/route_decider_agent.py:38-45` | `route_decision.py` | Extract `_score_bid()` as pure function |
| `backend/server.py:127-159` | `server.py` | Copy ConnectionManager class |
| `frontend/mac/src/hooks/useWebSocket.js` | `frontend/src/hooks/useWebSocket.js` | None |
| `frontend/mac/src/hooks/useJob.js` | `frontend/src/hooks/useJob.js` | Adapt for v2 agent states |
| `frontend/mac/src/components/shared/*` | `frontend/src/components/shared/*` | None |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Browser-Use agent unreliable on marketplace forms | Person 2 starts with eBay (most reliable), gets 8/10 before moving to others |
| 12-15 contexts exceeds memory on demo hardware | Person 1 benchmarks in first 15 min of Phase 1, adjusts pool size |
| WS binary protocol mismatch between Person 3 and 4 | Contract defined upfront, both test with same sample frame |
| Gemini rate limiting with 10+ concurrent agents | Split LLMs: Gemini for video analysis, ChatBrowserUse for agents (per design doc) |
| Integration breaks at Phase 2 | Contracts defined in Phase 0 catch 90% of issues. Pairs debug together. |
