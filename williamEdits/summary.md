# William's Changes — Playbook & Browser Automation Components

## Scope

William owns: **marketplace playbooks** (`playbooks/`), **CDP screencast streaming** (`backend/streaming.py`), **server.py** scaffolding, demo tooling (`williamEdits/`), and all associated tests. Everything else (orchestrator, intake, frontend, route decision) is built by other team members.

---

## Files Added

### `williamEdits/demo_stream.py`
Standalone demo that validates the full CDP screencast pipeline end-to-end without requiring intake or a real video upload. Launches uvicorn + 4 Playwright pages in the same asyncio event loop, starts CDP screencasting on each, and drives the `_screenshot_push_loop` to deliver frames to any WebSocket client.

Usage:
```
python williamEdits/demo_stream.py
# Then open: williamEdits/mock_frontend.html?job=demo
```

Four demo agents navigate to distinct marketplace URLs (eBay sold search, Facebook Marketplace, Mercari search, Amazon parts search) so each tile shows different live content. Uses `uvicorn.Server` with `install_signal_handlers` patched out so the outer `asyncio.run()` stays in charge of the loop.

### `williamEdits/mock_frontend.html`
Static HTML page that connects to `/ws/{job}/screenshots`, decodes binary frames, and renders one canvas tile per agent. Auto-creates tiles on first frame from each agent — no pre-registration needed.

Frame parsing: reads byte 0 (`0x01` version check), bytes 1–32 (agentId, null-stripped), bytes 33–36 (uint32 BE timestamp, unused for rendering), bytes 37+ (JPEG payload). Uses `createImageBitmap` to decode JPEG off the main thread.

### `run_playbook_tests.py` (project root)
Single-file executable test runner for live playbook testing. Runs research and/or listing agents for all 5 platforms using the same `Agent` / `ChatBrowserUse` pattern the real orchestrator uses.

Usage:
```
python run_playbook_tests.py              # all platforms, research + listing
python run_playbook_tests.py research     # research phase only
python run_playbook_tests.py listing      # listing phase only
python run_playbook_tests.py ebay         # one platform, both phases
python run_playbook_tests.py facebook research
```

Hardcoded presets: **iPhone 13 Pro 256GB** (`ITEM`/`PACKAGE`) for eBay/Facebook/Mercari/Amazon, and **Levi's 501 Jeans 32×32** (`CLOTHING_ITEM`/`CLOTHING_PACKAGE`) for Depop. Uses `ChatBrowserUse` with key from `settings.browser_use_api_key`. Runs headed (headless=False) so agent actions are visible.

### `tests/test_playbooks_live.py`
pytest-compatible live integration tests. Individual test functions per platform/phase:
- `test_ebay_research`, `test_ebay_listing`
- `test_facebook_research`, `test_facebook_listing`
- `test_mercari_research`, `test_mercari_listing`
- `test_depop_research`, `test_depop_listing`
- `test_amazon_research` (research-only; no listing test)
- `test_all_research_parallel` — runs all 5 research agents concurrently via `asyncio.gather`

Listing tests require cookie files. See **Authentication Assumption** below.

---

## Files Modified

### `backend/streaming.py`
Replaced screenshot polling with async CDP screencast. Full rewrite of the capture layer.

**Current design (as of `c0d9660`):**

CDP is configured to scale frames to the configured grid dimensions (`settings.screenshot_grid_width` × `settings.screenshot_grid_height`, default 320×240) before encoding. The server receives pre-scaled JPEG — no PIL processing server-side.

- `FrameData` — dataclass with `jpeg: bytes` (raw CDP JPEG) and `ts: float`. No grid/focus split.
- `frame_store: dict[str, FrameData]` — latest frame per agent. CDP callback writes; `server.py` reads.
- `_cdp_sessions: dict[str, object]` — active sessions for teardown.
- `start_screencast(agent_id, page)` — opens a CDP session via `page.context.new_cdp_session(page)`, calls `Page.startScreencast` with JPEG format, `maxWidth`/`maxHeight` set to grid dimensions, `quality` from `settings.screenshot_grid_quality` (60), and `everyNthFrame` derived from `settings.screenshot_capture_fps` (e.g., fps=2 → everyNthFrame=30). The `Page.screencastFrame` handler decodes base64, stores to `frame_store`, and ACKs immediately with `Page.screencastFrameAck` so the browser doesn't pause.
- `stop_screencast(agent_id)` — sends `Page.stopScreencast`, detaches the CDP session, removes agent from `frame_store`.
- `encode_binary_frame(agent_id, jpeg_bytes)` — packages JPEG into the 37-byte binary WS format.
- `get_frame_for_delivery(agent_id)` — returns `bytes | None` (latest JPEG, or None if no frame yet).
- `get_all_agent_ids()` — returns all agent IDs currently in `frame_store`.

**Removed in `c0d9660` vs earlier draft:**
- `_encode_frame` (PIL resize + dual grid/focus encoding) — CDP does the resize now.
- `focused_agent_id` module variable — focus switching removed; all agents deliver at the same rate.
- Separate `grid`/`focus` fields in `FrameData`.

**Binary frame format** (confirmed with Person 4 / frontend):
```
[0x01] [32-byte utf8 agentId, null-padded] [4-byte uint32 BE timestamp] [JPEG payload]
Header total: 37 bytes.
```

### `backend/server.py`
- Imports: `encode_binary_frame`, `get_all_agent_ids`, `get_frame_for_delivery` from `backend.streaming`.
- `_OrchestratorStub` — placeholder interface used when `server.py` runs without the real orchestrator. Documents the two CDP hook calls Person 1 must make (see Interface section). The real `orchestrator.py` now implements these hooks — see below.
- `_screenshot_push_loop(job_id)` — runs as a background task. Iterates `get_all_agent_ids()` on every tick. Per-agent rate limiting via `last_sent: dict[str, float]` — each agent's frame is only sent when `now - last_sent[agent_id] >= interval`. Interval = `1.0 / settings.screenshot_grid_delivery_fps` (default 1 fps). Skips agents with no frames. Sends to all screenshot WS clients for the job via `ws_manager.broadcast_screenshot`.
- `_event_drain_loop(job_id)` — awaits `orchestrator.events.get()` in a loop, broadcasts each event as JSON to all events WS clients for the job.
- `ConnectionManager` — manages per-job sets of WebSocket connections for events and screenshots separately. Stale connection detection on send failure.
- WebSocket `/ws/{jobId}/screenshots` — receive loop only (`ws.receive_bytes()` in a while loop to keep the connection alive); sending is done entirely by `_screenshot_push_loop`.

### `tests/test_streaming.py`
Updated to match the current CDP screencast API:
- `FrameData` has only `jpeg` + `ts` (no `grid`/`focus`).
- `stop_screencast` is async; tests use `@pytest.mark.anyio`.
- `TestStopScreencast` class; `setup_method` clears `_cdp_sessions` to prevent cross-test contamination.
- `TestBinaryFrameEncoding` tests the 37-byte binary frame protocol.
- `TestFrameStore` tests `get_frame_for_delivery` and `get_all_agent_ids`.

### `tests/test_playbooks.py`
- Removed `TestApplePlaybook` and `from playbooks.apple import ApplePlaybook`.
- `TestRegistration.test_all_playbooks_registered`: expected set is `{"ebay", "facebook", "mercari", "depop", "amazon"}`.
- `TestAmazonPlaybook` expanded: `test_research_query_includes_replacement_parts`, `test_research_query_includes_defect_terms`, `test_parse_research_returns_parts`, `test_parse_research_totals_repair_cost`, `test_parse_research_invalid_json`. Amazon is research-only; `listing_task` returns `SKIPPED`.

### `playbooks/__init__.py`
Removed `ApplePlaybook` import and `register_playbook(ApplePlaybook())`.

### `playbooks/base.py`
- `_safe_parse_json(result)` — handles escaped-quote JSON (`{\"key\": \"val\"}`) from live test findings. Tries `result.replace(r'\"', '"')` as a fallback before fence-match and brace-match extraction.
- `_parse_price_list_research(result, price_type)` — shared parse for eBay/Facebook/Mercari/Depop. Accepts both `sold_prices`/`prices` key formats and `avg`/computed average. Used by 4 of 5 playbooks.

---

## Files Deleted

### `playbooks/apple.py`
Removed entirely. Apple trade-in lookup is handled by an existing v1 `backend/services/apple_trade_in.py` service, not a Browser-Use playbook. No Apple playbook should be re-created.

---

## Playbooks

Five platform playbooks, all extend `BasePlaybook`:

| Platform | Research | Listing | Notes |
|----------|----------|---------|-------|
| eBay | Sold listings, `LH_Complete=1&LH_Sold=1` | 10-step posting flow | No CONDITION_MAP; LLM picks closest tile |
| Facebook | Active Marketplace prices | Create item flow | CONDITION_MAP: Like New / Good / Fair |
| Mercari | Sold listings, `status=sold_out` | Tile-based condition selection | CONDITION_MAP includes `(NWOT)` label |
| Depop | Active prices | Clothing-only listing | 4 images max; `_is_clothing` guard |
| Amazon | Replacement parts research only | Returns `SKIPPED` immediately | `parse_research` sums `part_price` → `total_repair_cost` |

All research tasks navigate via `initial_actions` (no LLM call for navigation). Research tasks target `max_steps=5`; listing tasks target `max_steps=30`.

---

## Interface With Other Components

### Orchestrator → streaming.py (real orchestrator in `orchestrator.py`)
The real `Orchestrator.run_agent` already calls the streaming hooks. In `run_agent`:

```python
# On the agent's first step (browser page is ready):
async def _screencast_on_first_step(state, model_output, step):
    if sc_started[0]:
        return
    sc_started[0] = True
    page = await agent_box[0].browser_session.get_current_page()
    await streaming.start_screencast(agent_id, page)

# ... passed as step_prehook to _build_agent

# In the finally block (agent complete or cancelled):
await streaming.stop_screencast(agent_id)
```

`agent_id` format: `"{platform}-{phase}-{item_id}"` (e.g., `"ebay-research-abc123"`).

If the stub is replaced with this real orchestrator, `server.py` requires no changes as long as `orchestrator.events` and `orchestrator.start_pipeline` are honored.

### `_OrchestratorStub` in `server.py` (still present)
Used when `server.py` runs standalone (e.g., with `uvicorn backend.server:app`). Emits stub `agent:spawn` events but does not launch real agents or call CDP hooks. Replace `orchestrator = _OrchestratorStub()` with the real import when integrating.

### streaming.py → server.py (internal)
`server.py` reads from `streaming.frame_store` only via `get_frame_for_delivery` and `get_all_agent_ids`. No direct dict access. `encode_binary_frame` is also imported for WS framing.

### server.py → intake.py (Person 2)
`server.py` calls `await streaming_analysis(video_path, job_id)` from `backend.intake` inside `_run_pipeline`. Lazy import to avoid circular imports. Expects `(items: list[ItemCard], timings: dict, best_frames: dict)`.

### Playbooks → Orchestrator (Person 1)
```python
task_str, initial_actions = playbook.research_task(item)       # research phase
task_str, initial_actions = playbook.listing_task(item, pkg)   # listing phase
parsed = playbook.parse_research(history.final_result())       # after agent.run()
```
`initial_actions` is a list of Browser-Use action dicts (e.g., `[{"navigate": {"url": "..."}}]`). `parse_research` returns a dict with at minimum `avg_sold_price` and `listings_found` (or `parts` + `total_repair_cost` for Amazon).

---

## Assumptions & Stubs

### `settings.storage_state_map` (authentication for live tests)
Live tests reference `settings.storage_state_map.get(platform)` to load pre-saved Playwright storage state (cookies). The real `Orchestrator` in `orchestrator.py` uses `self.profiles: dict[str, str | None] = settings.storage_state_map`. This property exists in `config.py` (set via env or JSON). Listing tests hit login walls without valid cookie files in the map.

### `./data/test_images/` for live tests
Live tests reference image paths under `./data/test_images/` (hero.jpg, defect.jpg, etc.). These files are not committed. Listing agents fail image upload steps if missing. Research-only tests are unaffected.

### Apple Trade-In Research
Apple trade-in research is **not a Browser-Use playbook**. The v1 `backend/services/apple_trade_in.py` service handles it via API. The orchestrator wires that service directly.

### Retry behavior (orchestrator.py)
`run_agent` retries once on exception with a 3-second sleep. The retry does NOT set up a new `_screencast_on_first_step` callback, so CDP screencasting is not started on retry. This is a known gap — if the first run failed before the browser was ready, the retry won't stream either.

---

## Live Test Findings (from initial run)

- **Depop research** — returned clean parseable JSON (`avg=$22.95`, 1020 listings).
- **eBay/Facebook/Mercari/Amazon research** — agents extracted correct prices but returned JSON with escaped quotes (`{\"key\": ...}`), causing `_safe_parse_json` in `base.py` to fail on the first parse attempt. Fixed: `_safe_parse_json` now tries an unescape pass before fence/brace extraction.
- **All listing tests** — hit login walls; need cookie files per platform in `settings.storage_state_map`.
- **eBay listing without auth** — agent entered eBay's simplified phone-seller flow and ran 30 steps without completing.
