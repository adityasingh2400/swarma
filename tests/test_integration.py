"""Integration tests — verify pipeline component interactions with mocked externals.
Tests the full flow: video upload → intake → orchestrator → route decision → events.
No real browsers, no real LLMs, no real ffmpeg."""
from __future__ import annotations

import asyncio
import json
import struct
import time
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from backend.config import settings
from backend.models.item_card import ItemCard, ItemCategory
from backend.models.job import Job, JobStatus
from backend.server import (
    ConnectionManager,
    _OrchestratorStub,
    _event_drain_loop,
    _screenshot_push_loop,
    _jobs,
    _job_items,
    ws_manager,
)
from backend.streaming import (
    FrameData,
    encode_binary_frame,
    frame_store,
    get_all_agent_ids,
    get_frame_for_delivery,
)
from contracts import AgentEvent, AgentState, RouteDecision
from models.item_card import ItemCard as RootItemCard
from models.listing_package import ListingPackage, ListingImage
from orchestrator import Orchestrator, PLAYBOOKS, register_playbook
from playbooks.ebay import EbayPlaybook
from playbooks.facebook import FacebookPlaybook
from playbooks.mercari import MercariPlaybook
from playbooks.depop import DepopPlaybook
from playbooks.amazon import AmazonPlaybook
from route_decision import route_decision


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _make_jpeg(w=64, h=64, color=(128, 128, 128)) -> bytes:
    img = Image.new("RGB", (w, h), color=color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _make_item(**overrides) -> RootItemCard:
    defaults = dict(
        item_id="integ-test-001",
        name_guess="iPhone 14 Pro 128GB",
        category=ItemCategory.ELECTRONICS,
    )
    defaults.update(overrides)
    return RootItemCard(**defaults)


def _make_package(**overrides) -> ListingPackage:
    images = [
        ListingImage(path="/img/hero.jpg", role="hero"),
        ListingImage(path="/img/defect.jpg", role="defect_proof"),
        ListingImage(path="/img/spec.jpg", role="spec_card"),
        ListingImage(path="/img/sec1.jpg", role="secondary"),
        ListingImage(path="/img/sec2.jpg", role="secondary"),
        ListingImage(path="/img/sec3.jpg", role="secondary"),
    ]
    defaults = dict(
        item_id="integ-test-001",
        title="Apple iPhone 14 Pro 128GB Space Black Unlocked",
        description="Excellent condition iPhone 14 Pro.",
        price_strategy=799.00,
        images=images,
    )
    defaults.update(overrides)
    return ListingPackage(**defaults)


# ── Integration: Playbook → Route Decision Flow ────────────────────────────


class TestPlaybookRouteDecisionIntegration:
    """Test that playbook parse_research output feeds correctly into route_decision."""

    def test_ebay_research_output_feeds_route_decision(self):
        item = _make_item()
        pb = EbayPlaybook()
        parsed = pb.parse_research('{"sold_prices": [700, 800, 900], "listings_found": 3}')
        research = {"ebay": parsed}
        decision = route_decision(item, research)
        assert "ebay" in decision.platforms
        assert decision.prices["ebay"] == 800.0  # avg of 700, 800, 900

    def test_multi_platform_research_feeds_route_decision(self):
        item = _make_item()
        research = {
            "ebay": EbayPlaybook().parse_research(
                '{"sold_prices": [700, 800, 900], "listings_found": 3}'
            ),
            "facebook": FacebookPlaybook().parse_research(
                '{"sold_prices": [650, 750], "listings_found": 2}'
            ),
            "mercari": MercariPlaybook().parse_research(
                '{"sold_prices": [680, 720, 760], "listings_found": 3}'
            ),
        }
        decision = route_decision(item, research)
        assert len(decision.platforms) >= 2
        # Platforms should be ranked
        scores = [decision.scores[p] for p in decision.platforms]
        assert scores == sorted(scores, reverse=True)

    def test_failed_research_doesnt_block_decision(self):
        item = _make_item()
        research = {
            "ebay": EbayPlaybook().parse_research(
                '{"sold_prices": [800], "listings_found": 1}'
            ),
            "facebook": FacebookPlaybook().parse_research(None),
            "mercari": MercariPlaybook().parse_research("garbage"),
        }
        decision = route_decision(item, research)
        # eBay should be in the result, others may or may not depending on score
        assert "ebay" in decision.platforms

    def test_amazon_research_only_has_zero_price(self):
        item = _make_item()
        parsed = AmazonPlaybook().parse_research(
            '{"parts": [{"part_name": "Screen", "part_price": 49.99, "part_url": "u"}]}'
        )
        assert parsed["avg_sold_price"] == 0.0  # Amazon is research-only
        assert parsed["total_repair_cost"] == 49.99


# ── Integration: Playbook Research → Listing Task Flow ──────────────────────


class TestPlaybookListingFlowIntegration:
    """Test that research output can produce valid listing tasks."""

    def test_ebay_full_flow_produces_listing_task(self):
        item = _make_item()
        pb = EbayPlaybook()
        # Simulate research
        parsed = pb.parse_research('{"sold_prices": [700, 800], "listings_found": 2}')
        # Build route decision
        decision = route_decision(item, {"ebay": parsed})
        # Create listing package
        package = _make_package(price_strategy=decision.prices.get("ebay", 799.0))
        # Generate listing task
        task, actions = pb.listing_task(item, package)
        assert isinstance(task, str)
        assert len(task) > 100  # Should have detailed instructions
        assert actions[0]["navigate"]["url"] == "https://ebay.com/sell"

    def test_all_platforms_produce_valid_listing_tasks(self):
        item = _make_item()
        package = _make_package()
        playbooks = [EbayPlaybook(), FacebookPlaybook(), MercariPlaybook(), DepopPlaybook()]
        for pb in playbooks:
            task, actions = pb.listing_task(item, package)
            assert isinstance(task, str), f"{pb.platform} listing task is not a string"
            assert len(actions) >= 1, f"{pb.platform} has no initial_actions"
            assert "navigate" in actions[0], f"{pb.platform} first action is not navigate"

    def test_amazon_listing_returns_skip(self):
        item = _make_item()
        package = _make_package()
        pb = AmazonPlaybook()
        task, actions = pb.listing_task(item, package)
        assert "SKIPPED" in task
        assert actions == []


# ── Integration: Binary WS Frame → Frontend Decode ────────────────────────


class TestBinaryFrameRoundTrip:
    """Test that binary frames can be encoded by server and decoded by frontend logic."""

    def test_encode_decode_roundtrip(self):
        jpeg = _make_jpeg()
        agent_id = "ebay-research-abc123"
        frame = encode_binary_frame(agent_id, jpeg)

        # Decode like the frontend would
        assert frame[0:1] == b"\x01"  # version byte

        agent_bytes = frame[1:33]
        decoded_id = agent_bytes.rstrip(b"\x00").decode("utf-8")
        assert decoded_id == agent_id

        ts = struct.unpack(">I", frame[33:37])[0]
        assert ts > 0

        payload = frame[37:]
        assert payload == jpeg

    def test_multiple_agents_distinguishable(self):
        """When multiple agents stream simultaneously, their frames must be distinguishable."""
        agents = ["ebay-research-abc", "facebook-listing-xyz", "mercari-research-123"]
        frames = {}
        for agent_id in agents:
            jpeg = _make_jpeg(color=(hash(agent_id) % 256, 0, 0))
            frames[agent_id] = encode_binary_frame(agent_id, jpeg)

        # Verify each frame decodes to the correct agent
        for agent_id, frame in frames.items():
            decoded_id = frame[1:33].rstrip(b"\x00").decode("utf-8")
            assert decoded_id == agent_id


# ── Integration: Event Pipeline ──────────────────────────────────────────────


class TestEventPipelineIntegration:
    """Test that events flow correctly from orchestrator stub through WS manager."""

    @pytest.mark.anyio
    async def test_event_flow_stub_to_ws(self):
        """Events emitted by orchestrator stub should reach WS clients."""
        stub = _OrchestratorStub()
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_events("job-1", ws)

        # Emit an event
        await stub.events.put({"type": "agent:spawn", "data": {"agentId": "test-1"}})

        # Drain loop should deliver it
        with patch("backend.server.orchestrator", stub), \
             patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_event_drain_loop("job-1"))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        ws.send_json.assert_called_with({"type": "agent:spawn", "data": {"agentId": "test-1"}})

    @pytest.mark.anyio
    async def test_screenshot_frame_store_to_ws(self):
        """Screenshots in frame_store should be delivered to WS clients."""
        frame_store.clear()
        jpeg = _make_jpeg()
        frame_store["agent-1"] = FrameData(jpeg=jpeg, ts=time.time())

        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect_screenshots("job-1", ws)

        with patch("backend.server.ws_manager", mgr):
            task = asyncio.create_task(_screenshot_push_loop("job-1"))
            await asyncio.sleep(0.5)  # Wait for at least one delivery cycle (5fps = 200ms interval)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert ws.send_bytes.called
        sent_frame = ws.send_bytes.call_args[0][0]
        # Verify it's a valid binary frame
        assert sent_frame[0:1] == b"\x01"
        payload = sent_frame[37:]
        assert payload == jpeg

        frame_store.clear()


# ── Integration: Config Consistency ──────────────────────────────────────────


class TestConfigIntegration:
    """Verify config settings used by different components are consistent."""

    def test_root_and_backend_configs_both_load(self):
        from config import settings as root_settings
        from backend.config import settings as backend_settings
        # Both should have API host/port
        assert root_settings.api_port == 8080
        assert backend_settings.api_port == 8080

    def test_backend_config_has_screenshot_settings(self):
        """streaming.py reads these from backend.config."""
        from backend.config import settings as s
        assert hasattr(s, "screenshot_capture_fps")
        assert hasattr(s, "screenshot_grid_quality")
        assert hasattr(s, "screenshot_grid_width")
        assert hasattr(s, "screenshot_grid_height")
        assert hasattr(s, "screenshot_grid_delivery_fps")

    def test_root_config_has_browser_use_settings(self):
        """orchestrator.py reads these from config."""
        from config import settings as s
        assert hasattr(s, "browser_use_api_key")
        assert hasattr(s, "max_concurrent_agents")

    def test_storage_state_map_returns_dict(self):
        from config import settings as s
        ssm = s.storage_state_map
        assert isinstance(ssm, dict)
        assert "ebay" in ssm
        assert "facebook" in ssm
        assert "mercari" in ssm
        assert "depop" in ssm


# ── Integration: Models Interop ─────────────────────────────────────────────


class TestModelInterop:
    """Test that models from different modules work together."""

    def test_item_card_to_listing_package(self):
        """ItemCard properties are used by playbooks to build listing tasks."""
        item = _make_item(
            visible_defects=[
                {"description": "scratch", "source": "visual", "severity": "moderate"},
            ],
        )
        assert item.condition_label == "Good"
        assert item.has_defects is True

        # Playbook uses these in listing task
        pb = EbayPlaybook()
        task, _ = pb.listing_task(item, _make_package())
        assert "scratch" in task
        assert "Good" in task

    def test_route_decision_to_listing_package(self):
        """RouteDecision fields map to ListingPackage."""
        decision = RouteDecision(
            item_id="test",
            platforms=["ebay", "facebook"],
            prices={"ebay": 799.0, "facebook": 750.0},
            scores={"ebay": 0.85, "facebook": 0.78},
        )
        package = ListingPackage(
            item_id=decision.item_id,
            platforms=decision.platforms,
            prices=decision.prices,
        )
        assert package.platforms == ["ebay", "facebook"]
        assert package.prices["ebay"] == 799.0

    def test_job_status_transitions(self):
        """Verify the expected status flow: UPLOADING → EXTRACTING → ANALYZING → EXECUTING → COMPLETED."""
        job = Job(job_id="test")
        expected_flow = [
            JobStatus.UPLOADING, JobStatus.EXTRACTING,
            JobStatus.ANALYZING, JobStatus.EXECUTING, JobStatus.COMPLETED,
        ]
        for status in expected_flow:
            job.status = status
            job.touch()
        assert job.status == JobStatus.COMPLETED

    def test_job_failure_from_any_status(self):
        """Job can transition to FAILED from any status."""
        for status in JobStatus:
            job = Job(status=status)
            job.status = JobStatus.FAILED
            job.error = "Something went wrong"
            assert job.status == JobStatus.FAILED


# ── Integration: Orchestrator Stub Pipeline ──────────────────────────────────


class TestOrchestratorStubPipeline:
    """Test the full stub pipeline flow."""

    @pytest.mark.anyio
    async def test_multi_item_pipeline(self):
        stub = _OrchestratorStub()
        items = [
            ItemCard(job_id="j1", name_guess="iPhone 15", confidence=0.9),
            ItemCard(job_id="j1", name_guess="MacBook Pro", confidence=0.85),
        ]
        await stub.start_pipeline("job-1", items)

        events = []
        while not stub.events.empty():
            events.append(stub.events.get_nowait())

        # 5 platforms × 2 items = 10 events
        assert len(events) == 10
        assert all(e["type"] == "agent:spawn" for e in events)

        # Each item should have 5 agents
        item1_agents = [e for e in events if items[0].item_id[:6] in e["data"]["agentId"]]
        item2_agents = [e for e in events if items[1].item_id[:6] in e["data"]["agentId"]]
        assert len(item1_agents) == 5
        assert len(item2_agents) == 5

    @pytest.mark.anyio
    async def test_agent_states_populated_after_pipeline(self):
        stub = _OrchestratorStub()
        items = [ItemCard(job_id="j1", name_guess="Watch", confidence=0.8)]
        await stub.start_pipeline("job-1", items)

        states = stub.get_agent_states("job-1")
        assert len(states) == 5
        for state in states.values():
            assert state["status"] == "queued"
            assert state["phase"] == "research"
