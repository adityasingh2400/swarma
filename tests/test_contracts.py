"""Tests for contracts.py — shared types for the v2 pipeline."""
from __future__ import annotations

import time

import pytest

from contracts import AgentEvent, AgentState, RouteDecision, Playbook
from models.item_card import ItemCard
from models.listing_package import ListingPackage


# ── AgentEvent ──────────────────────────────────────────────────────────────


class TestAgentEvent:
    def test_creates_with_required_fields(self):
        event = AgentEvent(type="agent:spawn", agent_id="ebay-research-abc123")
        assert event.type == "agent:spawn"
        assert event.agent_id == "ebay-research-abc123"

    def test_timestamp_auto_populated(self):
        before = time.time()
        event = AgentEvent(type="agent:spawn", agent_id="x")
        after = time.time()
        assert before <= event.timestamp <= after

    def test_data_defaults_to_empty_dict(self):
        event = AgentEvent(type="agent:spawn", agent_id="x")
        assert event.data == {}

    def test_data_accepts_arbitrary_dict(self):
        event = AgentEvent(
            type="agent:result",
            agent_id="ebay-research-abc",
            data={"final_result": "some text", "duration_s": 14.2},
        )
        assert event.data["final_result"] == "some text"
        assert event.data["duration_s"] == 14.2

    def test_all_event_types_valid(self):
        for etype in ["agent:spawn", "agent:status", "agent:result",
                       "agent:complete", "agent:error", "decision:made"]:
            event = AgentEvent(type=etype, agent_id="test")
            assert event.type == etype

    def test_serializes_to_dict(self):
        event = AgentEvent(type="agent:spawn", agent_id="x", data={"key": "val"})
        d = event.model_dump()
        assert d["type"] == "agent:spawn"
        assert d["agent_id"] == "x"
        assert d["data"]["key"] == "val"
        assert "timestamp" in d


# ── AgentState ──────────────────────────────────────────────────────────────


class TestAgentState:
    def test_creates_with_required_fields(self):
        state = AgentState(
            agent_id="ebay-research-abc",
            item_id="item1",
            platform="ebay",
            phase="research",
            status="queued",
            task="Research iPhone on eBay",
        )
        assert state.agent_id == "ebay-research-abc"
        assert state.platform == "ebay"
        assert state.phase == "research"
        assert state.status == "queued"

    def test_optional_fields_default_none(self):
        state = AgentState(
            agent_id="x", item_id="y", platform="ebay",
            phase="research", status="queued", task="test",
        )
        assert state.started_at is None
        assert state.completed_at is None
        assert state.result is None
        assert state.error is None

    def test_all_status_values(self):
        for status in ["queued", "running", "retrying", "complete", "error", "blocked"]:
            state = AgentState(
                agent_id="x", item_id="y", platform="ebay",
                phase="research", status=status, task="test",
            )
            assert state.status == status


# ── RouteDecision ──────────────────────────────────────────────────────────


class TestRouteDecision:
    def test_creates_with_required_fields(self):
        rd = RouteDecision(
            item_id="item1",
            platforms=["ebay", "facebook"],
            prices={"ebay": 799.0, "facebook": 750.0},
        )
        assert rd.item_id == "item1"
        assert rd.platforms == ["ebay", "facebook"]
        assert rd.prices["ebay"] == 799.0

    def test_scores_default_empty(self):
        rd = RouteDecision(item_id="x", platforms=[], prices={})
        assert rd.scores == {}

    def test_serializes_to_dict(self):
        rd = RouteDecision(
            item_id="item1",
            platforms=["ebay"],
            prices={"ebay": 500.0},
            scores={"ebay": 0.85},
        )
        d = rd.model_dump()
        assert d["item_id"] == "item1"
        assert d["platforms"] == ["ebay"]
        assert d["prices"]["ebay"] == 500.0
        assert d["scores"]["ebay"] == 0.85


# ── Playbook ABC ──────────────────────────────────────────────────────────


class TestPlaybookABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Playbook()

    def test_subclass_must_implement_all_methods(self):
        class IncompletePlaybook(Playbook):
            platform = "test"
            def research_task(self, item):
                return ("task", [])
            # Missing listing_task and parse_research

        with pytest.raises(TypeError):
            IncompletePlaybook()

    def test_complete_subclass_instantiates(self):
        class CompletePlaybook(Playbook):
            platform = "test"
            def research_task(self, item):
                return ("task", [])
            def listing_task(self, item, package):
                return ("task", [])
            def parse_research(self, result):
                return {}

        pb = CompletePlaybook()
        assert pb.platform == "test"
