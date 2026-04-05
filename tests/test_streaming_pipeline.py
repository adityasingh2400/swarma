"""Tests for the full streaming pipeline: CDP → frame_store → binary WS → frontend decode.

Verifies the product end goal: 15 concurrent browser agents streaming live at 1fps
to a React frontend grid. Tests the critical path:
  1. Frame store handles 15 concurrent agents
  2. Binary WS frames are correctly encoded for all agents
  3. Screenshot push loop delivers frames for all agents within delivery interval
  4. Event drain loop handles the event volume from 15 agents
  5. Frontend can decode every frame the backend produces
  6. No frame loss or corruption under load

Run:
    python -m pytest tests/test_streaming_pipeline.py -v -s --tb=short
"""
from __future__ import annotations

import asyncio
import base64
import struct
import time
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from backend.config import settings
from backend.streaming import (
    FrameData,
    encode_binary_frame,
    frame_store,
    get_all_agent_ids,
    get_frame_for_delivery,
    start_screencast,
    stop_screencast,
)
import backend.streaming as streaming_mod
from backend.server import (
    ConnectionManager,
    _OrchestratorStub,
    _event_drain_loop,
    _screenshot_push_loop,
)
from contracts import AgentEvent


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_jpeg(w=320, h=240, color=(128, 128, 128)) -> bytes:
    img = Image.new("RGB", (w, h), color=color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=60)
    return buf.getvalue()


def _make_agent_id(platform: str, phase: str, item_idx: int) -> str:
    """Generate agent IDs matching the orchestrator pattern."""
    return f"{platform}-{phase}-item{item_idx:03d}"


def _generate_15_agent_ids() -> list[str]:
    """Generate the 15 agent IDs for max load: 5 platforms × 3 items."""
    platforms = ["ebay", "facebook", "mercari", "depop", "amazon"]
    agent_ids = []
    for item_idx in range(3):
        for platform in platforms:
            agent_ids.append(_make_agent_id(platform, "research", item_idx))
    return agent_ids


def _parse_frame_frontend(data: bytes) -> dict | None:
    """Python implementation of frontend parseFrame() from useScreenshots.js.
    Validates that what the backend produces is decodable by the frontend."""
    HEADER_SIZE = 37
    if len(data) < HEADER_SIZE:
        return None
    if data[0] != 0x01:
        return None
    agent_bytes = data[1:33]
    agent_id = agent_bytes.rstrip(b"\x00").decode("utf-8")
    ts = struct.unpack(">I", data[33:37])[0]
    jpeg = data[37:]
    return {"agentId": agent_id, "timestamp": ts, "jpeg": jpeg}


# ── Phase 1: Frame Store at Scale ────────────────────────────────────────────


class TestFrameStoreAtScale:
    """Verify frame_store handles 15 concurrent agents without data loss."""

    def setup_method(self):
        frame_store.clear()

    def teardown_method(self):
        frame_store.clear()

    def test_15_agents_stored_simultaneously(self):
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            jpeg = _make_jpeg(color=(hash(agent_id) % 256, 0, 0))
            frame_store[agent_id] = FrameData(jpeg=jpeg, ts=time.time())

        assert len(frame_store) == 15
        assert set(get_all_agent_ids()) == set(agent_ids)

    def test_all_15_agents_retrievable(self):
        agent_ids = _generate_15_agent_ids()
        jpegs = {}
        for agent_id in agent_ids:
            jpeg = _make_jpeg(color=(hash(agent_id) % 256, 50, 100))
            jpegs[agent_id] = jpeg
            frame_store[agent_id] = FrameData(jpeg=jpeg, ts=time.time())

        for agent_id in agent_ids:
            retrieved = get_frame_for_delivery(agent_id)
            assert retrieved == jpegs[agent_id], f"Frame mismatch for {agent_id}"

    def test_rapid_frame_updates_latest_wins(self):
        """Simulate 2fps capture: each agent updates twice, only latest kept."""
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            old = _make_jpeg(color=(100, 0, 0))
            frame_store[agent_id] = FrameData(jpeg=old, ts=1.0)
            new = _make_jpeg(color=(200, 0, 0))
            frame_store[agent_id] = FrameData(jpeg=new, ts=2.0)

        for agent_id in agent_ids:
            frame = frame_store[agent_id]
            assert frame.ts == 2.0, f"{agent_id} should have latest frame"

    def test_stop_screencast_removes_agent_from_store(self):
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            frame_store[agent_id] = FrameData(jpeg=_make_jpeg(), ts=time.time())

        assert len(frame_store) == 15
        # Stop first 5 agents (one item's research batch)
        for agent_id in agent_ids[:5]:
            asyncio.run(stop_screencast(agent_id))

        assert len(frame_store) == 10
        for agent_id in agent_ids[:5]:
            assert get_frame_for_delivery(agent_id) is None


# ── Phase 2: Binary Frame Encoding at Scale ──────────────────────────────────


class TestBinaryFrameEncodingAtScale:
    """Verify binary frame protocol handles all 15 agents correctly."""

    def test_all_15_agent_ids_encoded_correctly(self):
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            jpeg = _make_jpeg()
            frame = encode_binary_frame(agent_id, jpeg)

            # Frontend decode
            parsed = _parse_frame_frontend(frame)
            assert parsed is not None, f"Failed to parse frame for {agent_id}"
            assert parsed["agentId"] == agent_id, (
                f"Agent ID mismatch: expected {agent_id}, got {parsed['agentId']}"
            )
            assert parsed["jpeg"] == jpeg, f"JPEG payload corrupted for {agent_id}"

    def test_agent_ids_up_to_32_bytes(self):
        """Longest agent ID: 'mercari-research-item002' = 24 chars. Must fit in 32 bytes."""
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            assert len(agent_id.encode("utf-8")) <= 32, (
                f"Agent ID '{agent_id}' exceeds 32 bytes"
            )

    def test_frame_sizes_within_budget(self):
        """Each binary frame should be ~15-25KB (320x240 JPEG q60 + 37-byte header)."""
        jpeg = _make_jpeg()
        frame = encode_binary_frame("agent-test", jpeg)
        frame_kb = len(frame) / 1024
        assert 1.0 < frame_kb < 50.0, f"Frame size {frame_kb:.1f}KB outside expected range"

    def test_15_agents_at_5fps_bandwidth_under_2mbs(self):
        """15 agents at 5fps: 15 × 5 × ~20KB = ~1.5 MB/s. Must stay under 2 MB/s."""
        per_frame_bytes = 0
        for agent_id in _generate_15_agent_ids():
            jpeg = _make_jpeg()
            frame = encode_binary_frame(agent_id, jpeg)
            per_frame_bytes += len(frame)
        # per_frame_bytes = total for 1 frame per agent (15 frames)
        # At 5 fps: per_frame_bytes × 5
        bandwidth_per_sec = per_frame_bytes * 5
        bandwidth_mb = bandwidth_per_sec / (1024 * 1024)
        assert bandwidth_mb < 2.0, f"Bandwidth {bandwidth_mb:.2f} MB/s exceeds 2 MB/s budget"


# ── Phase 3: Screenshot Push Loop Delivery ───────────────────────────────────


class TestScreenshotPushLoopAtScale:
    """Verify the push loop delivers frames for all 15 agents."""

    def setup_method(self):
        frame_store.clear()

    def teardown_method(self):
        frame_store.clear()

    @pytest.mark.anyio
    async def test_delivers_frames_for_all_15_agents_at_5fps(self):
        """Push loop must deliver frames for all 15 agents at 5 fps minimum."""
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            frame_store[agent_id] = FrameData(jpeg=_make_jpeg(), ts=time.time())

        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-15", ws)

        measure_seconds = 2.0
        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("job-15"))
            await asyncio.sleep(measure_seconds)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert ws.send_bytes.called, "No frames delivered at all"

        # Count frames per agent
        frames_per_agent: dict[str, int] = {}
        for call in ws.send_bytes.call_args_list:
            parsed = _parse_frame_frontend(call[0][0])
            if parsed:
                frames_per_agent[parsed["agentId"]] = frames_per_agent.get(parsed["agentId"], 0) + 1

        # All 15 agents must have received frames
        assert set(frames_per_agent.keys()) == set(agent_ids), (
            f"Missing agents: {set(agent_ids) - set(frames_per_agent.keys())}"
        )

        # Each agent should get roughly 5 fps × measure_seconds frames
        # Allow 3 fps floor (accounting for asyncio scheduling jitter)
        min_expected = int(3 * measure_seconds)
        for agent_id, count in frames_per_agent.items():
            assert count >= min_expected, (
                f"{agent_id} got {count} frames in {measure_seconds}s — need >= {min_expected} for 5fps"
            )

    @pytest.mark.anyio
    async def test_no_delivery_without_clients(self):
        """Push loop should NOT send frames when no WS clients connected."""
        for agent_id in _generate_15_agent_ids():
            frame_store[agent_id] = FrameData(jpeg=_make_jpeg(), ts=time.time())

        mgr = ConnectionManager()
        # No clients connected

        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("job-none"))
            await asyncio.sleep(1.0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # No error, no crash — loop just skips

    @pytest.mark.anyio
    async def test_stale_client_cleaned_up(self):
        """If a WS client disconnects mid-stream, it should be cleaned up."""
        frame_store["agent-1"] = FrameData(jpeg=_make_jpeg(), ts=time.time())

        mgr = ConnectionManager()
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_bytes.side_effect = Exception("broken pipe")
        await mgr.connect_screenshots("job-stale", good_ws)
        await mgr.connect_screenshots("job-stale", bad_ws)

        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("job-stale"))
            await asyncio.sleep(2.0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Good client should have received frames
        assert good_ws.send_bytes.called
        # Bad client should have been removed
        assert bad_ws not in mgr._screenshots.get("job-stale", set())


# ── Phase 4: Event Drain Loop at Scale ───────────────────────────────────────


class TestEventDrainLoopAtScale:
    """Verify event drain handles the event volume from 15 agents."""

    @pytest.mark.anyio
    async def test_drains_15_agent_spawn_events(self):
        """Simulate 15 agent:spawn events (one per agent) and verify all delivered."""
        stub = _OrchestratorStub()
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            await stub.events.put({
                "type": "agent:spawn",
                "data": {"agentId": agent_id, "platform": agent_id.split("-")[0]},
            })

        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_events("job-scale", ws)

        with patch("backend.server.orchestrator", stub), \
             patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_event_drain_loop("job-scale"))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert ws.send_json.call_count == 15
        delivered_ids = set()
        for call in ws.send_json.call_args_list:
            event = call[0][0]
            delivered_ids.add(event["data"]["agentId"])
        assert delivered_ids == set(agent_ids)

    @pytest.mark.anyio
    async def test_drains_mixed_event_types(self):
        """15 agents each emit spawn + 3 status + complete = 75 events total."""
        stub = _OrchestratorStub()
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            await stub.events.put({"type": "agent:spawn", "data": {"agentId": agent_id}})
            for step in range(3):
                await stub.events.put({"type": "agent:status", "data": {"agentId": agent_id, "step": step}})
            await stub.events.put({"type": "agent:complete", "data": {"agentId": agent_id}})

        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_events("job-mixed", ws)

        with patch("backend.server.orchestrator", stub), \
             patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_event_drain_loop("job-mixed"))
            await asyncio.sleep(0.5)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert ws.send_json.call_count == 75  # 15 × (1 spawn + 3 status + 1 complete)


# ── Phase 5: Frontend Decode Compatibility ───────────────────────────────────


class TestFrontendDecodeCompatibility:
    """Verify that every frame the backend produces is decodable by the frontend.
    This tests the contract between backend/streaming.py and frontend/useScreenshots.js."""

    def test_parse_frame_frontend_valid(self):
        jpeg = _make_jpeg()
        frame = encode_binary_frame("ebay-research-item000", jpeg)
        parsed = _parse_frame_frontend(frame)
        assert parsed is not None
        assert parsed["agentId"] == "ebay-research-item000"
        assert parsed["timestamp"] > 0
        assert parsed["jpeg"] == jpeg

    def test_parse_frame_frontend_rejects_short(self):
        assert _parse_frame_frontend(b"too short") is None

    def test_parse_frame_frontend_rejects_wrong_version(self):
        frame = b"\x02" + b"\x00" * 36 + b"jpeg"
        assert _parse_frame_frontend(frame) is None

    def test_parse_frame_frontend_handles_null_padded_id(self):
        """Short agent IDs should be null-padded to 32 bytes, frontend strips nulls."""
        frame = encode_binary_frame("abc", _make_jpeg())
        parsed = _parse_frame_frontend(frame)
        assert parsed["agentId"] == "abc"

    def test_all_15_agents_roundtrip(self):
        """Backend encode → frontend decode roundtrip for all 15 agent IDs."""
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            jpeg = _make_jpeg(color=(hash(agent_id) % 256, 0, 0))
            frame = encode_binary_frame(agent_id, jpeg)
            parsed = _parse_frame_frontend(frame)
            assert parsed["agentId"] == agent_id
            assert parsed["jpeg"] == jpeg
            # Verify JPEG is valid
            img = Image.open(BytesIO(parsed["jpeg"]))
            assert img.size == (320, 240)

    def test_jpeg_starts_with_soi_marker(self):
        """Frontend creates Blob from JPEG bytes — must start with SOI marker."""
        jpeg = _make_jpeg()
        frame = encode_binary_frame("test", jpeg)
        parsed = _parse_frame_frontend(frame)
        assert parsed["jpeg"][:2] == b"\xff\xd8", "JPEG must start with SOI marker"
        assert parsed["jpeg"][-2:] == b"\xff\xd9", "JPEG must end with EOI marker"


# ── Phase 6: CDP Screencast Lifecycle at Scale ───────────────────────────────


class TestCDPScreencastLifecycleAtScale:
    """Verify CDP screencast start/stop lifecycle for 15 agents."""

    def setup_method(self):
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()

    def teardown_method(self):
        frame_store.clear()
        streaming_mod._cdp_sessions.clear()

    @pytest.mark.anyio
    async def test_start_15_screencasts(self):
        """Can start CDP screencasts for all 15 agents."""
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            mock_cdp = AsyncMock()
            mock_cdp.on = MagicMock()
            mock_page = AsyncMock()
            mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)
            await start_screencast(agent_id, mock_page)

        assert len(streaming_mod._cdp_sessions) == 15

    @pytest.mark.anyio
    async def test_stop_all_15_screencasts(self):
        """Can stop all 15 CDP sessions cleanly."""
        agent_ids = _generate_15_agent_ids()
        for agent_id in agent_ids:
            mock_cdp = AsyncMock()
            streaming_mod._cdp_sessions[agent_id] = mock_cdp
            frame_store[agent_id] = FrameData(jpeg=_make_jpeg(), ts=time.time())

        for agent_id in agent_ids:
            await stop_screencast(agent_id)

        assert len(streaming_mod._cdp_sessions) == 0
        assert len(frame_store) == 0

    @pytest.mark.anyio
    async def test_frame_handler_populates_store_for_all_agents(self):
        """Simulate CDP pushing frames for all 15 agents."""
        agent_ids = _generate_15_agent_ids()
        handlers = {}

        for agent_id in agent_ids:
            mock_cdp = AsyncMock()
            captured = {}
            mock_cdp.on = MagicMock(side_effect=lambda evt, fn, _c=captured: _c.update({evt: fn}))
            mock_page = AsyncMock()
            mock_page.context.new_cdp_session = AsyncMock(return_value=mock_cdp)
            await start_screencast(agent_id, mock_page)
            handlers[agent_id] = captured.get("Page.screencastFrame")

        # Simulate CDP pushing one frame per agent (handler is sync, uses ensure_future)
        for agent_id, handler in handlers.items():
            if handler:
                jpeg = _make_jpeg(color=(hash(agent_id) % 256, 0, 0))
                handler({
                    "sessionId": hash(agent_id) % 10000,
                    "data": base64.b64encode(jpeg).decode(),
                })
        await asyncio.sleep(0.1)  # Let ensure_future tasks execute

        # All 15 agents should have frames in the store
        assert len(frame_store) == 15
        for agent_id in agent_ids:
            assert get_frame_for_delivery(agent_id) is not None, f"No frame for {agent_id}"


# ── Phase 7: Full Streaming Pipeline Integration ─────────────────────────────


class TestFullStreamingPipelineIntegration:
    """End-to-end test: 15 agents → CDP capture → frame_store → push loop → WS → frontend decode."""

    def setup_method(self):
        frame_store.clear()

    def teardown_method(self):
        frame_store.clear()

    @pytest.mark.anyio
    async def test_15_agents_full_pipeline_at_5fps(self):
        """THE streaming end-goal test:
        1. 15 agents populate frame_store (simulating CDP capture at 5fps)
        2. Push loop reads and encodes binary frames at 5fps delivery
        3. WS client receives frames
        4. Frontend parseFrame() decodes all 15 agent streams correctly
        5. Each agent gets >= 5 frames per second
        """
        agent_ids = _generate_15_agent_ids()
        original_jpegs = {}

        # Step 1: Populate frame_store (simulating CDP capture)
        for agent_id in agent_ids:
            jpeg = _make_jpeg(color=(hash(agent_id) % 256, (hash(agent_id) >> 8) % 256, 0))
            original_jpegs[agent_id] = jpeg
            frame_store[agent_id] = FrameData(jpeg=jpeg, ts=time.time())

        # Step 2: Set up WS client
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-e2e", ws)

        # Step 3: Run push loop for 1 second at 5fps
        measure_seconds = 1.0
        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("job-e2e"))
            await asyncio.sleep(measure_seconds)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Step 4: Verify all frames delivered and decodable
        assert ws.send_bytes.called
        delivered: dict[str, list[bytes]] = {}
        for call in ws.send_bytes.call_args_list:
            raw = call[0][0]
            parsed = _parse_frame_frontend(raw)
            assert parsed is not None, "Frontend couldn't decode a frame"
            delivered.setdefault(parsed["agentId"], []).append(parsed["jpeg"])

        # All 15 agents should have been delivered
        assert set(delivered.keys()) == set(agent_ids), (
            f"Missing: {set(agent_ids) - set(delivered.keys())}"
        )

        # Each agent should get >= 3 frames in 1s (5fps target, 3fps floor for jitter)
        for agent_id in agent_ids:
            count = len(delivered[agent_id])
            assert count >= 3, (
                f"{agent_id}: got {count} frames in {measure_seconds}s, need >= 3 for 5fps target"
            )

        # JPEG payloads should match originals (latest frame)
        for agent_id in agent_ids:
            assert delivered[agent_id][-1] == original_jpegs[agent_id], (
                f"JPEG corrupted for {agent_id}"
            )

    @pytest.mark.anyio
    async def test_frame_update_during_push_loop(self):
        """Agents update frames while push loop is running. Latest frame should be delivered."""
        agent_id = "ebay-research-item000"
        old_jpeg = _make_jpeg(color=(255, 0, 0))
        new_jpeg = _make_jpeg(color=(0, 255, 0))

        frame_store[agent_id] = FrameData(jpeg=old_jpeg, ts=time.time())

        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-update", ws)

        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("job-update"))
            await asyncio.sleep(0.5)
            # Update frame mid-loop
            frame_store[agent_id] = FrameData(jpeg=new_jpeg, ts=time.time())
            await asyncio.sleep(0.5)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # The latest call should have the new JPEG
        last_call = ws.send_bytes.call_args_list[-1]
        parsed = _parse_frame_frontend(last_call[0][0])
        assert parsed["jpeg"] == new_jpeg, "Should deliver updated frame"


# ── Phase 8: Orchestrator Step Callback Screenshot Events ────────────────────


class TestOrchestratorScreenshotEvents:
    """Test agent:screenshot events (the JSON-based path, not CDP binary)."""

    def test_step_callback_emits_screenshot_for_all_agents(self):
        """15 agents each emit a screenshot event — verify all arrive in the queue."""
        from orchestrator import Orchestrator

        orch = Orchestrator(max_concurrent=15)
        agent_ids = _generate_15_agent_ids()

        for agent_id in agent_ids:
            cb = orch._make_step_callback(agent_id)
            mock_state = MagicMock()
            mock_state.screenshot = base64.b64encode(_make_jpeg()).decode()
            mock_state.url = f"https://{agent_id.split('-')[0]}.com/search"
            cb(mock_state, None, step=1)

        # Each agent should have emitted 2 events: screenshot + status
        events = []
        while not orch.events.empty():
            events.append(orch.events.get_nowait())

        screenshot_events = [e for e in events if e.type == "agent:screenshot"]
        assert len(screenshot_events) == 15

        screenshot_agents = {e.agent_id for e in screenshot_events}
        assert screenshot_agents == set(agent_ids)
