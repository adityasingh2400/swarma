"""Tests for backend/server.py — REST endpoints, WS protocol, pipeline orchestration."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.server import (
    app,
    _jobs,
    _job_items,
    ws_manager,
    ConnectionManager,
    _OrchestratorStub,
    _event_drain_loop,
    _screenshot_push_loop,
)
from backend.models.job import Job, JobStatus
from backend.models.item_card import ItemCard
from backend.streaming import FrameData
import backend.streaming as streaming_mod


@pytest.fixture(autouse=True)
def clean_state():
    """Clear in-memory stores between tests."""
    _jobs.clear()
    _job_items.clear()
    yield
    _jobs.clear()
    _job_items.clear()


@pytest.fixture
def client():
    return TestClient(app)


# ── REST Endpoints ───────────────────────────────────────────────────────────


class TestUploadEndpoint:
    def test_upload_returns_job_id(self, client, test_video):
        with open(test_video, "rb") as f:
            resp = client.post("/api/upload", files={"video": ("test.mp4", f, "video/mp4")})
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "processing"

    def test_upload_creates_job_in_store(self, client, test_video):
        with open(test_video, "rb") as f:
            resp = client.post("/api/upload", files={"video": ("test.mp4", f, "video/mp4")})
        job_id = resp.json()["job_id"]
        assert job_id in _jobs


class TestGetJobEndpoint:
    def test_returns_job(self, client):
        job = Job(job_id="test-123", status=JobStatus.ANALYZING)
        _jobs["test-123"] = job
        resp = client.get("/api/jobs/test-123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "test-123"
        assert data["status"] == "analyzing"

    def test_404_for_unknown_job(self, client):
        resp = client.get("/api/jobs/nonexistent")
        assert resp.status_code == 404


class TestGetAgentsEndpoint:
    def test_returns_agents_dict(self, client):
        _jobs["j1"] = Job(job_id="j1")
        resp = client.get("/api/jobs/j1/agents")
        assert resp.status_code == 200
        assert "agents" in resp.json()

    def test_404_for_unknown_job(self, client):
        resp = client.get("/api/jobs/nonexistent/agents")
        assert resp.status_code == 404


class TestGetItemsEndpoint:
    def test_returns_items(self, client):
        _jobs["j1"] = Job(job_id="j1")
        _job_items["j1"] = [
            ItemCard(job_id="j1", name_guess="Phone", confidence=0.9),
        ]
        resp = client.get("/api/jobs/j1/items")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["name_guess"] == "Phone"

    def test_404_when_no_items(self, client):
        resp = client.get("/api/jobs/nonexistent/items")
        assert resp.status_code == 404


# ── Experiment Endpoints Removed ─────────────────────────────────────────────


class TestExperimentEndpointsRemoved:
    def test_no_experiment_run_endpoint(self, client):
        resp = client.post("/api/experiments/run", json={"video_path": "x"})
        assert resp.status_code == 404 or resp.status_code == 405

    def test_no_experiment_get_endpoint(self, client):
        resp = client.get("/api/experiments/test123")
        assert resp.status_code == 404

    def test_no_debug_endpoint(self, client):
        resp = client.get("/debug/test123")
        assert resp.status_code == 404


    # NOTE: WebSocket integration tests require async test infrastructure
    # (httpx + anyio) due to the bidirectional nature of the WS endpoints.
    # Binary frame encoding/decoding is covered in test_streaming.py.
    # The WS contract (event types, frame format) is verified by protocol tests.


# ── ConnectionManager ────────────────────────────────────────────────────────


class TestConnectionManager:
    def test_has_screenshot_clients_false_when_empty(self):
        mgr = ConnectionManager()
        assert mgr.has_screenshot_clients("job-1") is False

    def test_disconnect_noop_for_unknown(self):
        mgr = ConnectionManager()
        # Should not raise
        mgr.disconnect_events("job-1", None)
        mgr.disconnect_screenshots("job-1", None)

    @pytest.mark.anyio
    async def test_connect_events_accepts_ws(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_events("job-1", ws)
        ws.accept.assert_called_once()

    @pytest.mark.anyio
    async def test_connect_screenshots_accepts_ws(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-1", ws)
        ws.accept.assert_called_once()

    @pytest.mark.anyio
    async def test_broadcast_event_sends_to_all_clients(self):
        mgr = ConnectionManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        await mgr.connect_events("job-1", ws1)
        await mgr.connect_events("job-1", ws2)

        await mgr.broadcast_event("job-1", {"type": "test"})
        ws1.send_json.assert_called_once_with({"type": "test"})
        ws2.send_json.assert_called_once_with({"type": "test"})

    @pytest.mark.anyio
    async def test_broadcast_event_removes_stale_connection(self):
        mgr = ConnectionManager()
        good_ws, bad_ws = AsyncMock(), AsyncMock()
        bad_ws.send_json.side_effect = Exception("connection closed")
        await mgr.connect_events("job-1", good_ws)
        await mgr.connect_events("job-1", bad_ws)

        await mgr.broadcast_event("job-1", {"type": "test"})
        assert bad_ws not in mgr._events.get("job-1", set())
        # Good connection still there
        assert good_ws in mgr._events["job-1"]

    @pytest.mark.anyio
    async def test_broadcast_event_no_clients_is_noop(self):
        mgr = ConnectionManager()
        await mgr.broadcast_event("nonexistent", {"type": "test"})  # must not raise

    @pytest.mark.anyio
    async def test_broadcast_screenshot_sends_binary(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-1", ws)
        payload = b"\x01" + b"\x00" * 36 + b"jpeg"
        await mgr.broadcast_screenshot("job-1", payload)
        ws.send_bytes.assert_called_once_with(payload)

    @pytest.mark.anyio
    async def test_broadcast_screenshot_removes_stale_connection(self):
        mgr = ConnectionManager()
        good_ws, bad_ws = AsyncMock(), AsyncMock()
        bad_ws.send_bytes.side_effect = Exception("broken pipe")
        await mgr.connect_screenshots("job-1", good_ws)
        await mgr.connect_screenshots("job-1", bad_ws)

        await mgr.broadcast_screenshot("job-1", b"frame")
        assert bad_ws not in mgr._screenshots.get("job-1", set())

    @pytest.mark.anyio
    async def test_has_screenshot_clients_true_after_connect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-1", ws)
        assert mgr.has_screenshot_clients("job-1") is True

    @pytest.mark.anyio
    async def test_has_screenshot_clients_false_after_disconnect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-1", ws)
        mgr.disconnect_screenshots("job-1", ws)
        assert mgr.has_screenshot_clients("job-1") is False

    def test_disconnect_events_cleans_up_empty_job(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr._events["job-1"] = {ws}
        mgr.disconnect_events("job-1", ws)
        assert "job-1" not in mgr._events

    def test_disconnect_screenshots_cleans_up_empty_job(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr._screenshots["job-1"] = {ws}
        mgr.disconnect_screenshots("job-1", ws)
        assert "job-1" not in mgr._screenshots


# ── _OrchestratorStub ────────────────────────────────────────────────────────


class TestOrchestratorStub:
    def setup_method(self):
        self.stub = _OrchestratorStub()

    @pytest.mark.anyio
    async def test_start_pipeline_emits_agent_spawn_events(self):
        items = [ItemCard(job_id="j1", name_guess="Phone", confidence=0.9)]
        await self.stub.start_pipeline("job-1", items)
        events = []
        while not self.stub.events.empty():
            events.append(self.stub.events.get_nowait())
        assert all(e["type"] == "agent:spawn" for e in events)
        assert len(events) == 5  # 5 platforms per item

    @pytest.mark.anyio
    async def test_start_pipeline_event_has_required_keys(self):
        items = [ItemCard(job_id="j1", name_guess="Phone", confidence=0.9)]
        await self.stub.start_pipeline("job-1", items)
        event = self.stub.events.get_nowait()
        assert "type" in event and "data" in event
        data = event["data"]
        assert {"agentId", "platform", "phase", "task"} <= set(data.keys())

    @pytest.mark.anyio
    async def test_start_pipeline_spawns_all_platforms(self):
        items = [ItemCard(job_id="j1", name_guess="Phone", confidence=0.9)]
        await self.stub.start_pipeline("job-1", items)
        states = self.stub.get_agent_states("job-1")
        platforms = {v["platform"] for v in states.values()}
        assert {"ebay", "facebook", "mercari", "apple", "amazon"} == platforms

    @pytest.mark.anyio
    async def test_start_pipeline_multiple_items_scale_linearly(self):
        items = [
            ItemCard(job_id="j1", name_guess="Phone", confidence=0.9),
            ItemCard(job_id="j1", name_guess="Laptop", confidence=0.8),
        ]
        await self.stub.start_pipeline("job-1", items)
        events = []
        while not self.stub.events.empty():
            events.append(self.stub.events.get_nowait())
        assert len(events) == 10  # 5 platforms × 2 items

    def test_get_agent_states_returns_all_agents(self):
        self.stub._agents["a1"] = {"agent_id": "a1", "platform": "ebay"}
        result = self.stub.get_agent_states("any-job")
        assert "a1" in result

    def test_get_browser_returns_none(self):
        assert self.stub.get_browser("any-agent") is None

    @pytest.mark.anyio
    async def test_agent_state_includes_status_and_phase(self):
        items = [ItemCard(job_id="j1", name_guess="Watch", confidence=0.7)]
        await self.stub.start_pipeline("job-1", items)
        states = self.stub.get_agent_states("job-1")
        for state in states.values():
            assert state["status"] == "queued"
            assert state["phase"] == "research"


# ── _event_drain_loop ─────────────────────────────────────────────────────────


class TestEventDrainLoop:
    @pytest.mark.anyio
    async def test_drains_queue_and_broadcasts(self):
        """Loop should pull events from orchestrator.events and broadcast them."""
        stub = _OrchestratorStub()
        await stub.events.put({"type": "agent:spawn", "data": {"agentId": "x"}})

        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_events("drain-test", ws)

        with patch("backend.server.orchestrator", stub), \
             patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_event_drain_loop("drain-test"))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        ws.send_json.assert_called_with({"type": "agent:spawn", "data": {"agentId": "x"}})

    @pytest.mark.anyio
    async def test_cancels_cleanly(self):
        stub = _OrchestratorStub()
        with patch("backend.server.orchestrator", stub):
            task = asyncio.create_task(_event_drain_loop("job-x"))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


# ── _screenshot_push_loop ─────────────────────────────────────────────────────


class TestScreenshotPushLoop:
    def setup_method(self):
        streaming_mod.frame_store.clear()
        streaming_mod.focused_agent_id = None

    @pytest.mark.anyio
    async def test_sends_binary_frame_to_screenshot_clients(self):
        streaming_mod.frame_store["agent-1"] = FrameData(jpeg=b"FAKEJPEG", ts=0.0)

        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("loop-job", ws)

        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("loop-job"))
            await asyncio.sleep(0.15)  # at least one grid tick (1.0 fps default)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert ws.send_bytes.called

    @pytest.mark.anyio
    async def test_skips_agents_with_no_frames(self):
        """Loop must not crash when frame_store is empty."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("loop-job", ws)

        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("loop-job"))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        ws.send_bytes.assert_not_called()

    @pytest.mark.anyio
    async def test_cancels_cleanly(self):
        with patch("backend.server.ws_manager", ConnectionManager()):
            task = asyncio.create_task(_screenshot_push_loop("job-x"))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
