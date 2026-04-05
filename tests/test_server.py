"""Tests for backend/server.py — REST endpoints, WS protocol, pipeline orchestration."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.server import app, _jobs, _job_items, ws_manager, ConnectionManager
from backend.models.job import Job, JobStatus
from backend.models.item_card import ItemCard


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
