# William's Changes — Playbook & Browser Automation Components

## Scope

William owns: **marketplace playbooks** (`playbooks/`), **CDP screencast streaming** (`backend/streaming.py`), **server.py** scaffolding, and all associated tests. Everything else (orchestrator, intake, frontend, route decision) is built by other team members.

---

## Files Added

### `run_playbook_tests.py` (project root)
Single-file executable test runner for live playbook testing. Runs research and/or listing agents for all 5 platforms using the same `Agent` / `ChatBrowserUse` pattern the real orchestrator will use.

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

**What changed:**
- `capture_loop(agent_id, get_page_fn)` (timer-driven polling) — **removed**
- `start_screencast(agent_id, page)` — opens a CDP session via `page.context.new_cdp_session(page)`, calls `Page.startScreencast` with JPEG format at `settings.screenshot_focus_quality`, and registers an async `Page.screencastFrame` event handler. Browser pushes frames; no polling loop.
- `stop_screencast(agent_id)` — sends `Page.stopScreencast`, detaches the CDP session, removes the agent from `frame_store`.
- `_cdp_sessions: dict[str, CDPSession]` — tracks active sessions for teardown.
- `_encode_frame(jpeg_bytes)` — replaces old `_encode_and_resize(png_bytes)`. Takes JPEG input (from CDP) instead of PNG; produces `grid` (320×240, q60) and `focus` (1280×960, q80) variants in a thread executor.
- `everyNthFrame` is derived from `settings.screenshot_capture_fps` assuming 60 Hz vsync (e.g., `fps=2 → everyNthFrame=30`). Each frame is ACK'd immediately with `Page.screencastFrameAck` so the browser doesn't pause delivery.
- `encode_binary_frame(agent_id, jpeg_bytes)` — packages a JPEG into the confirmed binary WS format (see Protocol below).
- `get_frame_for_delivery(agent_id)` — returns `(jpeg_bytes, is_focus)` for the latest stored frame.
- `focused_agent_id: str | None` — module-level variable, set by `server.py` when a client sends `focus:request`.

**Binary frame format** (confirmed with Person 4 / frontend):
```
[0x01] [32-byte utf8 agentId, null-padded] [4-byte uint32 BE timestamp] [JPEG payload]
Header total: 37 bytes.
```

### `backend/server.py`
- Imports updated: `start_screencast`, `stop_screencast` imported from `backend.streaming`; `focused_agent_id` accessed via `streaming_mod.focused_agent_id` (module reference, not direct import) to allow mutation.
- `_OrchestratorStub` docstring documents the two exact lines Person 1 (Aditya) must call per agent in the real orchestrator:
  ```python
  await streaming.start_screencast(agent_id, page)  # when browser page is ready
  await streaming.stop_screencast(agent_id)          # when agent completes or is cancelled
  ```
- The stub emits `agent:spawn` events and implements the same interface (`events` queue, `start_pipeline`, `get_agent_states`) that the real orchestrator must match.

### `tests/test_streaming.py`
Updated to match the CDP screencast API:
- `_encode_and_resize` → `_encode_frame` (JPEG input, not PNG); `_make_jpeg()` helper creates synthetic CDP-style JPEG frames.
- `stop_capture` → `stop_screencast` (now async); tests use `@pytest.mark.anyio`.
- `TestStopScreencast` class replaces old `stop_capture` tests; `setup_method` clears `_cdp_sessions` to prevent cross-test contamination.
- `TestBinaryFrameEncoding` tests the 37-byte binary frame protocol.
- `TestJpegEncoding` tests `_encode_frame` output dimensions and types.
- `TestFrameStore` tests `get_frame_for_delivery`, focus mode switching, and `get_all_agent_ids`.

### `tests/test_playbooks.py`
- Removed `from playbooks.apple import ApplePlaybook` and `TestApplePlaybook` class.
- `TestRegistration.test_all_playbooks_registered`: expected set is now `{"ebay", "facebook", "mercari", "depop", "amazon"}` (no `"apple"`).
- `TestAmazonPlaybook` expanded with: `test_research_query_includes_replacement_parts`, `test_research_query_includes_defect_terms`, `test_parse_research_returns_parts`, `test_parse_research_totals_repair_cost`, `test_parse_research_invalid_json`. Amazon is repair-parts research only; assertions reflect that (no `listing_task` test beyond confirming it returns `SKIPPED`).

### `playbooks/__init__.py`
Removed `ApplePlaybook` import and `register_playbook(ApplePlaybook())`. Apple was never implemented and should not exist.

---

## Files Deleted

### `playbooks/apple.py`
Removed entirely. Apple trade-in lookup is handled by an existing v1 `backend/services/apple_trade_in.py` service, not a Browser-Use playbook. No Apple playbook should be re-created.

---

## Interface With Other Components

### Orchestrator → streaming.py (Person 1 / Aditya)
The real orchestrator must call exactly:
```python
import backend.streaming as streaming

# When the agent's Playwright Page object is available:
await streaming.start_screencast(agent_id, page)

# When the agent finishes or is cancelled:
await streaming.stop_screencast(agent_id)
```
`page` is a Playwright `Page` object obtained from Browser-Use's `browser.get_current_page()` or equivalent. `agent_id` must be a stable unique string (e.g., `"ebay-research-abc123"`); it is used as the key in `frame_store` and embedded in every binary WS frame.

The orchestrator must also expose:
- `orchestrator.events: asyncio.Queue` — `server.py`'s `_event_drain_loop` drains this and broadcasts to WebSocket clients.
- `await orchestrator.start_pipeline(job_id, items)` — called by `server.py` after intake identifies items.
- `orchestrator.get_agent_states(job_id) -> dict` — called by `GET /api/jobs/{jobId}/agents`.

### streaming.py → server.py (internal, same repo)
`server.py` reads from `streaming.frame_store` (via `get_frame_for_delivery` and `get_all_agent_ids`) in its `_screenshot_push_loop`. No direct coupling beyond these public functions and the `focused_agent_id` module variable.

### server.py → intake.py (Person 2)
`server.py` calls `await streaming_analysis(video_path, job_id)` from `backend.intake`, expecting a return of `(items: list[ItemCard], timings: dict, best_frames: dict)`. This is imported lazily inside `_run_pipeline` to avoid circular imports.

### Playbooks → Orchestrator (Person 1)
The orchestrator calls playbooks via:
```python
task_str, initial_actions = playbook.research_task(item)   # research phase
task_str, initial_actions = playbook.listing_task(item, pkg)  # listing phase
```
`initial_actions` is a list of Browser-Use action dicts (e.g., `[{"navigate": {"url": "..."}}]`). The orchestrator passes `task_str` and `initial_actions` directly to the `Agent(...)` constructor.

After the agent completes, the orchestrator calls:
```python
parsed = playbook.parse_research(history.final_result())
```
`parse_research` returns a dict with at minimum `avg_sold_price` and `listings_found` (or `parts` + `total_repair_cost` for Amazon).

---

## Assumptions & Stubs

### `_OrchestratorStub` in `server.py`
The real orchestrator is not yet integrated. `_OrchestratorStub` provides a matching interface so `server.py` can be developed and tested independently. It emits stub `agent:spawn` events on `start_pipeline` but does not actually launch browser agents or call screencast hooks.

**When Person 1 delivers the real orchestrator**, `orchestrator = _OrchestratorStub()` in `server.py` should be replaced with the real import. The rest of `server.py` should require no changes if the interface contract is honored.

### `settings.storage_state_map` (authentication for live tests)
The live test files (`test_playbooks_live.py`, `run_playbook_tests.py`) reference `settings.storage_state_map.get(platform)` to load pre-saved Playwright storage state (cookies) for each platform. **This property is not yet in `backend/config.py`.**

To enable listing tests, add to `Settings`:
```python
storage_state_map: dict[str, str] = {}
# Populated at runtime from env or a JSON file, e.g.:
# {"ebay": "./auth/ebay.json", "facebook": "./auth/facebook.json", ...}
```
Until then, `storage_state_map.get(platform)` returns `None`, and agents run without authentication — listing tests will hit login walls.

### `./data/test_images/` for live tests
Live tests reference image paths under `./data/test_images/` (hero.jpg, defect.jpg, etc.). These files are not committed. Listing agents will fail image upload steps if these files don't exist. For research-only tests this has no effect.

### Apple Trade-In Research
Apple trade-in research (referenced in design doc as one of the 5 research agents) is **not implemented as a Browser-Use playbook**. The v1 `backend/services/apple_trade_in.py` service handles this via API. Person 1's orchestrator should wire that service directly rather than expecting an `ApplePlaybook`.

---

## Live Test Findings (from initial run)

- **Depop research** — returned clean parseable JSON (`avg=$22.95`, 1020 listings).
- **eBay/Facebook/Mercari/Amazon research** — agents extracted correct prices but returned JSON with escaped quotes (`{\"key\": ...}`), causing `_safe_parse_json` in `base.py` to fail. Needs a pre-parse unescape step in `_safe_parse_json`.
- **All listing tests** — hit login walls; need cookie files in `./auth/` per platform.
- **eBay listing without auth** — agent entered eBay's simplified phone-seller flow and ran 30 steps without completing.
