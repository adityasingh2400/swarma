# Eng Review: ReRoute v2 — Browser-Use Live Swarm

**Design doc:** `~/.gstack/projects/adityasingh2400-ReRoute/aditya-main-design-20260403-182847.md`
**Branch:** main | **Repo:** adityasingh2400/ReRoute | **Date:** 2026-04-03

## Context

ReRoute v2 replaces Fetch AI uAgents with Browser-Use for all agent research and marketplace posting. New project folder. Live CDP video streaming of 12-15 concurrent browser agents to a React dashboard — each agent's browser is a live video feed, not periodic screenshots. Video input with streaming latency fix. **Browser-Use is a hackathon sponsor** so the product should heavily showcase Browser-Use capabilities.

---

## Architecture Decisions (from review)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Cookie injection** via `context.add_cookies()`, not `user_data_dir` | `user_data_dir` launches a full Chromium process per profile (500-800MB). Cookie injection uses lightweight contexts (200-400MB) sharing one process. |
| 2 | **Split LLMs**: Gemini for video analysis, ChatBrowserUse for agents | Separates rate limit bottleneck. 10 Gemini keys can't sustain 15 concurrent Browser-Use agents. ChatBrowserUse is optimized for browser tasks. |
| 3 | **Two WebSocket endpoints**: `/ws/{jobId}/events` (JSON) + `/ws/{jobId}/screenshots` (binary video stream) | Clean separation. No framing ambiguity. CDP `Page.startScreencast` pushes frames; server delivers all agents uniformly at 5 fps minimum via `/screenshots`. |
| 4 | **Human takeover for CAPTCHAs**: Agent pauses, emits `needs_human`, presenter intervenes in headful browser, agent resumes | Browser-Use agents don't know to wait. Need explicit pause mechanism. Headful mode makes this a demo feature, not a bug. |
| 5 | **Context recycling** after each agent task | Prevents Chromium JS heap accumulation. Adds ~1-2s per context creation. |
| 6 | **Clean module split** from day one | server.py (<200 lines), orchestrator.py, playbooks/, streaming.py, intake.py, route_decision.py |
| 7 | **All-browser approach**: research AND listing agents use Browser-Use | Existing API research is unreliable. Browser-Use is hackathon sponsor. Maximize Browser-Use showcase. |

---

## Revised Architecture

```
VIDEO INPUT
    │
    ▼
┌──────────────────────────────────┐
│  intake.py                        │
│  ffmpeg streaming extraction      │
│  → Gemini batch analysis (3-5     │
│    frames at a time)              │
│  → Items identified as they come  │
└──────────┬───────────────────────┘
           │ ItemCard objects (streamed)
           ▼
┌──────────────────────────────────────────────────┐
│  orchestrator.py                                   │
│                                                    │
│  Browser context pool: 12-15 contexts              │
│  (one Chromium process, cookie-injected)           │
│  Context recycling after each agent task           │
│                                                    │
│  Per item:                                         │
│  ├─ Research Agents (concurrent, Browser-Use +     │
│  │   ChatBrowserUse)                               │
│  │   ├─ eBay sold listings search                  │
│  │   ├─ Facebook Marketplace comps                 │
│  │   ├─ Mercari price check                        │
│  │   ├─ Apple Trade-In lookup                      │
│  │   └─ Amazon parts search                        │
│  │                                                  │
│  ├─ route_decision.py (Gemini call, ~1-2s)         │
│  │                                                  │
│  └─ Listing Agents (concurrent, Browser-Use +      │
│      ChatBrowserUse)                               │
│      ├─ eBay listing (playbooks/ebay.py)           │
│      ├─ Facebook listing (playbooks/facebook.py)   │
│      ├─ Mercari listing (playbooks/mercari.py)     │
│      └─ Depop listing (playbooks/depop.py)         │
│                                                    │
│  Queue: research > listing, item 1 > item 2       │
└──────────┬───────────────────────────────────────┘
           │
    ┌──────┴──────┐
    │             │
    ▼             ▼
streaming.py   server.py
CDP screencast   FastAPI + WS
live video push  (/events + /screenshots)
(event-driven,   binary stream delivery
 no polling)
    │             │
    └──────┬──────┘
           │
           ▼
    React Frontend
    SwarmGrid (all agents live, 5 fps min)
```

## Backend Module Structure

```
reroute-v2/
├── backend/
│   ├── server.py              ← FastAPI routes + 2 WS endpoints (<200 lines)
│   ├── orchestrator.py        ← Agent lifecycle, context pool, queue
│   ├── intake.py              ← Video upload, streaming ffmpeg, Gemini analysis
│   ├── streaming.py           ← CDP live video stream (screencast push), binary WS framing
│   ├── route_decision.py      ← Scoring algorithm (extracted from v1)
│   ├── playbooks/
│   │   ├── base.py            ← Abstract playbook interface
│   │   ├── ebay.py            ← eBay listing task generator
│   │   ├── facebook.py        ← Facebook Marketplace task generator
│   │   ├── mercari.py         ← Mercari task generator
│   │   └── depop.py           ← Depop task generator
│   ├── services/
│   │   ├── media.py           ← COPIED from v1 (100% reusable)
│   │   └── gemini.py          ← COPIED from v1, remove uAgents refs
│   ├── systems/
│   │   └── listing_asset_optimization.py  ← COPIED from v1 (100%)
│   ├── models/                ← COPIED from v1 (100%, all 5 files)
│   ├── storage/
│   │   └── store.py           ← COPIED from v1, minor renames
│   └── config.py              ← COPIED from v1, add Browser-Use config
├── frontend/
│   ├── src/
│   │   ├── App.jsx            ← Adapted from v1
│   │   ├── hooks/
│   │   │   ├── useWebSocket.js     ← COPIED from v1 (100%)
│   │   │   ├── useJob.js           ← Adapted from v1 (new state fields)
│   │   │   └── useScreenshots.js   ← NEW: binary WS screenshot handler
│   │   ├── components/
│   │   │   ├── Layout.jsx          ← Adapted from v1
│   │   │   ├── SwarmGrid.jsx       ← NEW: all-agent live video grid (5 fps min)
│   │   │   ├── BrowserFeed.jsx     ← NEW: single-agent live video stream tile
│   │   │   ├── PipelineHeader.jsx  ← NEW: stage progress bar
│   │   │   └── shared/             ← COPIED from v1
│   │   └── index.css               ← New design system
│   └── package.json
├── tests/
│   ├── test_playbooks.py
│   ├── test_orchestrator.py
│   ├── test_route_decision.py
│   ├── test_intake.py
│   ├── test_image_pipeline.py
│   ├── test_auth.py
│   └── test_ws_protocol.py
├── data/                      ← Runtime: uploads, frames, listing-images, jobs
├── requirements.txt
├── .env.example
└── run.py
```

## What Already Exists (v1 code to copy)

| v1 File | v2 Location | Changes |
|---------|-------------|---------|
| `backend/services/media.py` | `backend/services/media.py` | None |
| `backend/systems/listing_asset_optimization.py` | `backend/systems/listing_asset_optimization.py` | None |
| `backend/models/*.py` (5 files) | `backend/models/*.py` | None |
| `backend/storage/store.py` | `backend/storage/store.py` | Rename agent → browser_task in comments |
| `backend/config.py` | `backend/config.py` | Delete agent seeds, add BROWSER_USE_API_KEY, CONTEXT_POOL_SIZE |
| `backend/services/gemini.py` | `backend/services/gemini.py` | Remove `precompute_demo_pipeline()` agent refs |
| `backend/agents/route_decider_agent.py` | `backend/route_decision.py` | Extract `_score_bid()`, constants, decision logic as pure functions |
| `backend/server.py:127-159` | `backend/server.py` | Copy ConnectionManager class |
| `frontend/mac/src/hooks/useWebSocket.js` | `frontend/src/hooks/useWebSocket.js` | None |
| `frontend/mac/src/components/shared/` | `frontend/src/components/shared/` | None |

## NOT in Scope

- Production deployment (Cloud, stealth, scaling)
- WebSocket authentication (localhost demo only)
- Crash recovery / persistent state (restart server if crash)
- Automated CAPTCHA solving (manual headful mode for demo)
- Design system finalization (run /design-consultation separately)
- Horizontal scaling (single machine)
- Session re-authentication (keep demo under 30 min)

## Build Order

| Step | What | Depends on | Module | Success criteria |
|------|------|------------|--------|-----------------|
| 0 | **Benchmark**: launch 5/10/15 Playwright contexts on 18GB M3 Pro, measure memory. Test one Browser-Use agent + ChatBrowserUse filling eBay form. | — | — | Real context ceiling established. Agent success rate measured. |
| 1 | **Scaffold**: new project folder, copy reusable v1 code, install deps | Step 0 | all | `pip install browser-use` + `npm install` works. Copied v1 code imports clean. |
| 2 | **eBay listing agent**: one reliable Browser-Use agent filling eBay form with hybrid task string | Step 1 | `playbooks/ebay.py`, `orchestrator.py` | 8/10 success rate. Listing URL confirmed live. |
| 3 | **CDP live video streaming**: subscribe to `Page.startScreencast` per agent context, push binary video frames via WebSocket | Step 2 | `streaming.py`, `server.py` | Live video feed visible in browser devtools/test page. Event-driven, no polling. |
| 4 | **Video intake**: streaming ffmpeg → Gemini batches → agent dispatch | Step 1 | `intake.py` | Video → item identified → agent spawned within 8s. |
| 5 | **SwarmGrid**: React component for all-agent live video grid | Step 3 | `SwarmGrid.jsx`, `BrowserFeed.jsx`, `useScreenshots.js` | All agents visible simultaneously at 5 fps minimum. |
| 6 | **Facebook + Mercari agents**: additional platform playbooks | Step 2 | `playbooks/facebook.py`, `playbooks/mercari.py` | 7/10 success rate per platform. |
| 7 | **Scale**: concurrent agents, context pool, queue | Steps 2-6 | `orchestrator.py` | 12+ agents running simultaneously. Memory within budget. |
| 8 | **Design system**: new visual identity | — | CSS | /design-consultation output applied. |
| 9 | **Polish**: animations, transitions, spawn effects | Steps 5, 8 | frontend | Visually impressive pipeline. |
| 10 | **Integration test**: full pipeline 5x | All | all | Video → listings on 3 platforms in <2 min. At least 3/5 runs succeed. |

## Critical Tests (8)

1. eBay playbook generates valid task string from ItemCard
2. Orchestrator spawns + queues agents correctly with priority
3. Route decision scoring matches v1 weighted algorithm
4. Binary WebSocket video stream frame parsing (frontend — `[0x01][32B agentId][4B ts][JPEG]`)
5. Cookie injection authenticates marketplace sessions
6. Gemini streaming analysis returns ItemCards from frame batches
7. Image extraction produces listing-ready JPEG files
8. Agent retry on failure + context return to pool

## Failure Modes

| Component | Failure | Test? | Error handling? | User sees? |
|-----------|---------|-------|-----------------|------------|
| Gemini analysis | 429 rate limit | No (deferred) | Skip batch, continue | Delayed item identification |
| Browser-Use agent | Task fails mid-form | Test #8 | Retry once, mark BLOCKED | Red border in grid |
| CAPTCHA | Marketplace challenge | No | needs_human event + pause | Presenter solves live |
| Context pool | All exhausted | Test #2 | Queue with priority | Agents show "queued" state |
| WebSocket | Disconnect during video stream | No | Auto-reconnect (v1 code) | Brief video feed pause, resumes on reconnect |
| CDP screencast | Session teardown before stop | No | try/except in stop_screencast | Frame store cleared, feed stops |
| Session cookie | Expired | No | Agent hits login page, fails | BLOCKED state |
| ffmpeg | Unsupported codec | No | Empty frame list | "No items found" message |

**Critical gaps (no test + no handling + silent failure):** None. All failure modes either have tests, error handling, or visible feedback.

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| 2: eBay agent | playbooks/, orchestrator.py | Step 1 |
| 3: CDP streaming | streaming.py, server.py | Step 2 |
| 4: Video intake | intake.py, services/ | Step 1 |
| 5: SwarmGrid component | frontend/src/ | Step 3 |

**Parallel lanes:**
- **Lane A:** Step 2 (eBay agent) → Step 3 (CDP streaming) → Step 7 (scale) — sequential, shared orchestrator
- **Lane B:** Step 4 (video intake) — independent, only touches intake.py + services/
- **Lane C:** Step 5 (frontend) — depends on Step 3 for WebSocket protocol, but can stub it

**Execution:** Launch A + B in parallel after Step 1. C starts once Step 3 defines the WebSocket protocol. Steps 6, 8, 9 are sequential polish.

## Completion Summary

- Step 0: Scope Challenge — scope accepted as-is (greenfield, no reduction needed)
- Architecture Review: 4 issues resolved (cookie injection, split LLMs, two WS endpoints, CAPTCHA flow)
- Code Quality Review: 1 issue resolved (clean module split)
- Test Review: diagram produced, 35 gaps, 8 critical tests planned
- Performance Review: 1 issue resolved (context recycling)
- NOT in scope: written (7 items deferred)
- What already exists: written (10 files reusable)
- TODOS.md updates: 0 items (new project, no existing TODOS)
- Failure modes: 0 critical gaps
- Outside voice: ran (Claude subagent), 3 tension points resolved
- Parallelization: 3 lanes, 2 parallel / 1 dependent
- Lake Score: 6/7 recommendations chose complete option

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | STALE (v1) | 7 proposals, 4 accepted (v1 design) |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR | 6 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0 across all reviews
**VERDICT:** ENG CLEARED. CEO review is stale (v1 design). Run `/plan-ceo-review` for v2 product strategy, `/design-consultation` for visual identity.
