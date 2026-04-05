"""Unit tests for orchestrator.py — playbook registry, agent lifecycle, pipeline logic.
No real browsers or LLMs — all mocked."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contracts import AgentEvent, AgentState, Playbook, RouteDecision
from models.item_card import ItemCard, ItemCategory
from models.listing_package import ListingPackage
from orchestrator import (
    Orchestrator,
    PLAYBOOKS,
    register_playbook,
    get_all_playbooks,
    get_playbook,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


class StubPlaybook(Playbook):
    platform = "stub"

    def research_task(self, item):
        return ("Research stub", [{"navigate": {"url": "https://example.com"}}])

    def listing_task(self, item, package):
        return ("List stub", [{"navigate": {"url": "https://example.com/sell"}}])

    def parse_research(self, result):
        return {"avg_sold_price": 100.0, "listings_found": 5}


def _make_item(**overrides) -> ItemCard:
    defaults = dict(
        item_id="test123",
        name_guess="iPhone 14 Pro",
        category=ItemCategory.ELECTRONICS,
    )
    defaults.update(overrides)
    return ItemCard(**defaults)


# ── Playbook Registry ───────────────────────────────────────────────────────


class TestPlaybookRegistry:
    def setup_method(self):
        self._saved = dict(PLAYBOOKS)

    def teardown_method(self):
        PLAYBOOKS.clear()
        PLAYBOOKS.update(self._saved)

    def test_register_playbook(self):
        pb = StubPlaybook()
        register_playbook(pb)
        assert "stub" in PLAYBOOKS
        assert PLAYBOOKS["stub"] is pb

    def test_get_all_playbooks(self):
        pb = StubPlaybook()
        register_playbook(pb)
        all_pb = get_all_playbooks()
        assert pb in all_pb

    def test_get_playbook_by_name(self):
        pb = StubPlaybook()
        register_playbook(pb)
        assert get_playbook("stub") is pb

    def test_get_playbook_raises_for_unknown(self):
        with pytest.raises(KeyError):
            get_playbook("nonexistent_platform_xyz")

    def test_register_overwrites_existing(self):
        pb1 = StubPlaybook()
        pb2 = StubPlaybook()
        register_playbook(pb1)
        register_playbook(pb2)
        assert PLAYBOOKS["stub"] is pb2


# ── Orchestrator Init ────────────────────────────────────────────────────────


class TestOrchestratorInit:
    def test_default_max_concurrent(self):
        orch = Orchestrator()
        assert orch.sem._value > 0

    def test_custom_max_concurrent(self):
        orch = Orchestrator(max_concurrent=5)
        assert orch.sem._value == 5

    def test_events_queue_created(self):
        orch = Orchestrator()
        assert isinstance(orch.events, asyncio.Queue)

    def test_agents_dict_empty(self):
        orch = Orchestrator()
        assert orch.agents == {}
        assert orch.agent_states == {}


# ── Agent Instance Access ────────────────────────────────────────────────────


class TestAgentAccess:
    def test_get_agent_instance_returns_none_for_unknown(self):
        orch = Orchestrator()
        assert orch.get_agent_instance("nonexistent") is None

    def test_get_active_agents_empty(self):
        orch = Orchestrator()
        assert orch.get_active_agents() == []

    def test_get_active_agents_returns_states(self):
        orch = Orchestrator()
        orch.agent_states["test-agent"] = AgentState(
            agent_id="test-agent", item_id="item1",
            platform="ebay", phase="research",
            status="running", task="test",
        )
        agents = orch.get_active_agents()
        assert len(agents) == 1
        assert agents[0].agent_id == "test-agent"


# ── Event Emission ──────────────────────────────────────────────────────────


class TestEventEmission:
    def test_emit_puts_event_on_queue(self):
        orch = Orchestrator()
        event = AgentEvent(type="agent:spawn", agent_id="test")
        orch._emit(event)
        assert not orch.events.empty()
        queued = orch.events.get_nowait()
        assert queued.type == "agent:spawn"

    def test_update_state(self):
        orch = Orchestrator()
        orch.agent_states["test"] = AgentState(
            agent_id="test", item_id="item1",
            platform="ebay", phase="research",
            status="running", task="test",
        )
        orch._update_state("test", status="complete")
        assert orch.agent_states["test"].status == "complete"

    def test_update_state_noop_for_unknown(self):
        orch = Orchestrator()
        orch._update_state("nonexistent", status="complete")  # should not raise


# ── Browser Profile ─────────────────────────────────────────────────────────


class TestBrowserProfile:
    def test_make_profile_returns_browser_profile(self):
        orch = Orchestrator()
        profile = orch._make_profile("ebay")
        assert profile is not None
        # BrowserProfile should have certain attributes
        assert hasattr(profile, "storage_state")


# ── Pipeline (mocked) ──────────────────────────────────────────────────────


class TestPipelineMocked:
    def setup_method(self):
        self._saved = dict(PLAYBOOKS)

    def teardown_method(self):
        PLAYBOOKS.clear()
        PLAYBOOKS.update(self._saved)

    @pytest.mark.anyio
    async def test_start_pipeline_no_playbooks_logs_warning(self):
        PLAYBOOKS.clear()
        orch = Orchestrator(max_concurrent=2)
        items = [_make_item()]
        # Should not raise, just log a warning
        await orch.start_pipeline("job-1", items)

    @pytest.mark.anyio
    @pytest.mark.parametrize("anyio_backend", ["asyncio"], indirect=True)
    async def test_start_pipeline_emits_events(self):
        """With mocked run_agent, pipeline should emit decision events."""
        pb = StubPlaybook()
        register_playbook(pb)

        orch = Orchestrator(max_concurrent=5)

        # Mock run_agent to return a mock history
        mock_history = MagicMock()
        mock_history.is_done.return_value = True
        mock_history.final_result.return_value = '{"avg_sold_price": 100, "listings_found": 5}'

        with patch.object(orch, "run_agent", new_callable=AsyncMock, return_value=mock_history):
            items = [_make_item()]
            await orch.start_pipeline("job-1", items)

        # Drain events
        events = []
        while not orch.events.empty():
            events.append(orch.events.get_nowait())

        # Should have at least a decision:made event
        decision_events = [e for e in events if e.type == "decision:made"]
        assert len(decision_events) >= 1


# ── Step Callback ──────────────────────────────────────────────────────────


class TestStepCallback:
    def test_make_step_callback_returns_callable(self):
        orch = Orchestrator()
        cb = orch._make_step_callback("test-agent")
        assert callable(cb)

    def test_step_callback_emits_status_event(self):
        orch = Orchestrator()
        cb = orch._make_step_callback("test-agent")

        mock_state = MagicMock()
        mock_state.screenshot = None
        mock_state.url = "https://example.com"

        mock_output = MagicMock()
        mock_output.current_state.memory = "found items"
        mock_output.current_state.next_goal = "click next"
        mock_output.action = []

        cb(mock_state, mock_output, step=1)

        event = orch.events.get_nowait()
        assert event.type == "agent:status"
        assert event.agent_id == "test-agent"
        assert event.data["step"] == 1

    def test_step_callback_emits_screenshot_event(self):
        orch = Orchestrator()
        cb = orch._make_step_callback("test-agent")

        mock_state = MagicMock()
        mock_state.screenshot = "base64data"
        mock_state.url = "https://example.com"

        cb(mock_state, None, step=1)

        # Should emit both screenshot and status events
        events = []
        while not orch.events.empty():
            events.append(orch.events.get_nowait())

        types = [e.type for e in events]
        assert "agent:screenshot" in types
        assert "agent:status" in types
