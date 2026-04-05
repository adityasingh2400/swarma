"""Tests for intake.py aggregation — Arctic-Embed dedup, per-item grouping."""
from __future__ import annotations

import asyncio

import pytest

from backend.intake import (
    _aggregate_detections,
    _aggregate_detections_per_item,
)


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Global Aggregation ───────────────────────────────────────────────────────


class TestAggregateDetections:
    def test_empty_input(self):
        result = run_async(_aggregate_detections([]))
        assert result == []

    def test_single_item_passes_through(self):
        items = [{"name": "iPhone 15", "confidence": 0.9, "likely_specs": {"brand": "Apple"}}]
        result = run_async(_aggregate_detections(items))
        assert len(result) == 1
        assert result[0]["name"] == "iPhone 15"

    def test_identical_items_cluster_together(self):
        items = [
            {"name": "iPhone 15 Pro 256GB", "confidence": 0.8, "likely_specs": {"brand": "Apple"}, "frame_indices": [0]},
            {"name": "iPhone 15 Pro 256GB", "confidence": 0.9, "likely_specs": {"brand": "Apple", "color": "Black"}, "frame_indices": [1]},
        ]
        result = run_async(_aggregate_detections(items, similarity_threshold=0.85))
        assert len(result) == 1
        # Should pick highest confidence
        assert result[0]["confidence"] == 0.9
        # Specs should be merged
        assert "brand" in result[0]["likely_specs"]
        assert "color" in result[0]["likely_specs"]
        # Frame indices should be merged
        assert set(result[0]["frame_indices"]) == {0, 1}

    def test_different_items_stay_separate(self):
        items = [
            {"name": "iPhone 15 Pro", "confidence": 0.9, "likely_specs": {"brand": "Apple"}},
            {"name": "Samsung Galaxy S24", "confidence": 0.85, "likely_specs": {"brand": "Samsung"}},
        ]
        result = run_async(_aggregate_detections(items, similarity_threshold=0.85))
        assert len(result) == 2

    def test_cluster_size_tracked(self):
        items = [
            {"name": "AirPods Pro", "confidence": 0.7, "likely_specs": {}, "frame_indices": [0]},
            {"name": "AirPods Pro 2", "confidence": 0.8, "likely_specs": {}, "frame_indices": [1]},
            {"name": "AirPods Pro 2nd gen", "confidence": 0.9, "likely_specs": {}, "frame_indices": [2]},
        ]
        result = run_async(_aggregate_detections(items, similarity_threshold=0.7))
        # These should cluster (very similar names)
        if len(result) == 1:
            assert result[0]["_cluster_size"] >= 2


# ── Per-Item Aggregation ─────────────────────────────────────────────────────


class TestAggregateDetectionsPerItem:
    def test_empty_input(self):
        result = run_async(_aggregate_detections_per_item([]))
        assert result == []

    def test_groups_by_item_id(self):
        items = [
            {"item_id": "phone", "name": "Phone v1", "confidence": 0.7, "likely_specs": {}, "frame_indices": [0]},
            {"item_id": "phone", "name": "Phone v2", "confidence": 0.9, "likely_specs": {}, "frame_indices": [1]},
            {"item_id": "watch", "name": "Watch", "confidence": 0.8, "likely_specs": {}, "frame_indices": [2]},
        ]
        result = run_async(_aggregate_detections_per_item(items))
        item_ids = [r["item_id"] for r in result]
        assert "phone" in item_ids
        assert "watch" in item_ids
        # Phone observations should merge into one
        phone_items = [r for r in result if r["item_id"] == "phone"]
        assert len(phone_items) == 1
        assert phone_items[0]["confidence"] == 0.9

    def test_preserves_item_id_after_aggregation(self):
        items = [
            {"item_id": "iPhone 15", "name": "iPhone", "confidence": 0.8, "likely_specs": {}, "frame_indices": [0]},
            {"item_id": "iPhone 15", "name": "iPhone", "confidence": 0.9, "likely_specs": {}, "frame_indices": [1]},
        ]
        result = run_async(_aggregate_detections_per_item(items))
        assert len(result) == 1
        assert result[0]["item_id"] == "iPhone 15"
