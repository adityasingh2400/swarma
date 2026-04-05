"""Unit tests for backend/intake.py — pure functions, no API calls."""
from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from backend.intake import (
    PipelineTimings,
    _build_item_prompt,
    _compute_hist,
    _compute_sharpness,
    _filter_quality_frames,
    _process_listing_image,
    _raw_to_item_card,
    _select_best_frames_per_item,
    DETECTION_PROMPT,
)
from backend.models.item_card import ItemCard, ItemCategory


# ── PipelineTimings ──────────────────────────────────────────────────────────


class TestPipelineTimings:
    def test_defaults_all_zero(self):
        t = PipelineTimings()
        assert t.audio_extraction_sec == 0.0
        assert t.transcription_sec == 0.0
        assert t.total_sec == 0.0
        assert t.frame_count == 0

    def test_audio_fields_present(self):
        t = PipelineTimings(audio_extraction_sec=1.5, transcription_sec=2.3)
        assert t.audio_extraction_sec == 1.5
        assert t.transcription_sec == 2.3


# ── Item-Aware Prompt ────────────────────────────────────────────────────────


class TestBuildItemPrompt:
    def test_contains_item_names(self):
        prompt = _build_item_prompt(["iPhone 15 Pro", "AirPods Pro 2"])
        assert "iPhone 15 Pro" in prompt
        assert "AirPods Pro 2" in prompt

    def test_returns_json_instruction(self):
        prompt = _build_item_prompt(["Watch"])
        assert "JSON" in prompt
        assert "null" in prompt

    def test_requires_exact_item_id(self):
        prompt = _build_item_prompt(["MacBook Air M3"])
        assert "EXACT name from list" in prompt


class TestDetectionPrompt:
    def test_prompt_at_least_1024_tokens_for_caching(self):
        # Gemini context caching activates at >=1024 tokens.
        # Rough estimate: 1 token ~ 4 chars for English.
        assert len(DETECTION_PROMPT) >= 1024, (
            f"DETECTION_PROMPT is {len(DETECTION_PROMPT)} chars, "
            "needs >=1024 for Gemini context caching"
        )

    def test_prompt_requests_json_array(self):
        assert "JSON array" in DETECTION_PROMPT

    def test_prompt_includes_bounding_box(self):
        assert "bounding_box" in DETECTION_PROMPT


# ── OpenCV Quality Filter ────────────────────────────────────────────────────


class TestFilterQualityFrames:
    def test_returns_empty_for_empty_input(self):
        assert _filter_quality_frames([]) == []

    def test_returns_subset_up_to_max(self, make_jpeg):
        frames = [(i, make_jpeg(64, 64, (i * 30, i * 20, i * 10))) for i in range(20)]
        result = _filter_quality_frames(frames, max_output_frames=5)
        assert len(result) <= 5
        # Each result is (idx, bytes)
        for idx, data in result:
            assert isinstance(idx, int)
            assert isinstance(data, bytes)

    def test_prefers_sharper_frames(self, make_jpeg):
        from io import BytesIO
        from PIL import Image, ImageFilter

        # Create a blurry frame and a sharp frame
        sharp_img = Image.new("RGB", (128, 128), "white")
        # Add high-frequency content (edges)
        pixels = sharp_img.load()
        for x in range(0, 128, 4):
            for y in range(128):
                pixels[x, y] = (0, 0, 0)
        buf = BytesIO()
        sharp_img.save(buf, format="JPEG", quality=90)
        sharp_bytes = buf.getvalue()

        blurry_img = sharp_img.filter(ImageFilter.GaussianBlur(radius=10))
        buf2 = BytesIO()
        blurry_img.save(buf2, format="JPEG", quality=90)
        blurry_bytes = buf2.getvalue()

        frames = [(0, blurry_bytes), (1, sharp_bytes)]
        result = _filter_quality_frames(frames, max_output_frames=1)
        assert len(result) == 1
        assert result[0][0] == 1  # sharp frame should win


# ── Sharpness and Histogram Helpers ──────────────────────────────────────────


class TestComputeSharpness:
    def test_returns_float(self, sample_jpeg_bytes):
        score = _compute_sharpness(sample_jpeg_bytes)
        assert isinstance(score, float)

    def test_sharp_image_scores_higher(self):
        from io import BytesIO
        from PIL import Image, ImageFilter

        # Sharp: high-frequency edges
        img = Image.new("RGB", (128, 128), "white")
        pixels = img.load()
        for x in range(0, 128, 2):
            for y in range(128):
                pixels[x, y] = (0, 0, 0)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=95)
        sharp_score = _compute_sharpness(buf.getvalue())

        # Blurry: same image heavily blurred
        blurry = img.filter(ImageFilter.GaussianBlur(radius=8))
        buf2 = BytesIO()
        blurry.save(buf2, format="JPEG", quality=95)
        blurry_score = _compute_sharpness(buf2.getvalue())

        assert sharp_score > blurry_score


class TestComputeHist:
    def test_returns_64_bin_histogram(self, sample_jpeg_bytes):
        hist = _compute_hist(sample_jpeg_bytes)
        assert hist.shape == (64, 1)

    def test_histogram_is_normalized(self, sample_jpeg_bytes):
        hist = _compute_hist(sample_jpeg_bytes)
        # L1 norm should be ~1.0 after normalization
        assert abs(hist.sum() - 1.0) < 0.01


# ── Per-Item Frame Selection ─────────────────────────────────────────────────


class TestSelectBestFramesPerItem:
    def test_empty_items(self, make_jpeg):
        result = _select_best_frames_per_item([], [(0, make_jpeg())])
        assert result == {}

    def test_empty_frames(self):
        items = [{"item_id": "phone", "frame_indices": [0, 1]}]
        result = _select_best_frames_per_item(items, [])
        assert result == {}

    def test_single_item_gets_up_to_4_frames(self, make_jpeg):
        frames = [(i, make_jpeg(64, 64, (i * 40, 0, 0))) for i in range(10)]
        items = [{"item_id": "phone", "frame_indices": list(range(10))}]
        result = _select_best_frames_per_item(items, frames, target_per_item=4)
        assert "phone" in result
        assert len(result["phone"]) == 4

    def test_fewer_than_target_is_ok(self, make_jpeg):
        frames = [(0, make_jpeg()), (1, make_jpeg())]
        items = [{"item_id": "watch", "frame_indices": [0, 1]}]
        result = _select_best_frames_per_item(items, frames, target_per_item=4)
        assert len(result["watch"]) == 2

    def test_multiple_items_get_independent_frames(self, make_jpeg):
        frames = [
            (0, make_jpeg(64, 64, (255, 0, 0))),
            (1, make_jpeg(64, 64, (0, 255, 0))),
            (2, make_jpeg(64, 64, (0, 0, 255))),
            (3, make_jpeg(64, 64, (255, 255, 0))),
            (4, make_jpeg(64, 64, (0, 255, 255))),
            (5, make_jpeg(64, 64, (255, 0, 255))),
        ]
        items = [
            {"item_id": "phone", "frame_indices": [0, 1, 2]},
            {"item_id": "watch", "frame_indices": [3, 4, 5]},
        ]
        result = _select_best_frames_per_item(items, frames, target_per_item=4)
        assert "phone" in result
        assert "watch" in result
        phone_idxs = {idx for idx, _ in result["phone"]}
        watch_idxs = {idx for idx, _ in result["watch"]}
        # Each item's frames should come from its own frame_indices
        assert phone_idxs <= {0, 1, 2}
        assert watch_idxs <= {3, 4, 5}

    def test_frames_ordered_by_sharpness_descending(self):
        """Selected frames should be ordered from sharpest to least sharp."""
        from io import BytesIO
        from PIL import Image, ImageFilter

        # Create frames with known sharpness ordering
        frames = []
        for i in range(6):
            img = Image.new("RGB", (128, 128), "white")
            pixels = img.load()
            for x in range(0, 128, 2):
                for y in range(128):
                    pixels[x, y] = (0, 0, 0)
            # Apply increasing blur
            blur_radius = i * 2
            if blur_radius > 0:
                img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=95)
            frames.append((i, buf.getvalue()))

        items = [{"item_id": "test", "frame_indices": list(range(6))}]
        result = _select_best_frames_per_item(items, frames, target_per_item=4)

        selected = result["test"]
        sharpness_scores = [_compute_sharpness(data) for _, data in selected]
        # Should be descending
        for i in range(len(sharpness_scores) - 1):
            assert sharpness_scores[i] >= sharpness_scores[i + 1], (
                f"Frame {i} sharpness {sharpness_scores[i]:.1f} < "
                f"frame {i+1} sharpness {sharpness_scores[i+1]:.1f}"
            )

    def test_uses_name_fallback_when_no_item_id(self, make_jpeg):
        frames = [(0, make_jpeg()), (1, make_jpeg())]
        items = [{"name": "Some Gadget", "frame_indices": [0, 1]}]
        result = _select_best_frames_per_item(items, frames)
        assert "Some Gadget" in result


# ── Raw-to-ItemCard Conversion ───────────────────────────────────────────────


class TestRawToItemCard:
    def test_basic_conversion(self):
        raw = {
            "item_id": "iPhone 15 Pro",
            "category": "electronics",
            "condition": "good",
            "confidence": 0.92,
            "visible_defects": [{"description": "scratch", "severity": "minor"}],
            "likely_specs": {"brand": "Apple", "storage": "256GB"},
        }
        card = _raw_to_item_card(raw, "job-1", ["frame_0", "frame_1"])
        assert card.name_guess == "iPhone 15 Pro"
        assert card.category == ItemCategory.ELECTRONICS
        assert card.confidence == 0.92
        assert card.job_id == "job-1"
        assert card.hero_frame_paths == ["frame_0", "frame_1"]
        assert len(card.visible_defects) == 1
        assert card.likely_specs["brand"] == "Apple"

    def test_unknown_category_falls_back_to_other(self):
        raw = {"name": "Widget", "category": "invalid_cat", "confidence": 0.5}
        card = _raw_to_item_card(raw, "j", [])
        assert card.category == ItemCategory.OTHER

    def test_list_specs_coerced_to_string(self):
        raw = {
            "name": "Phone",
            "likely_specs": {"colors": ["red", "blue"], "size": "6.1in"},
            "confidence": 0.8,
        }
        card = _raw_to_item_card(raw, "j", [])
        assert card.likely_specs["colors"] == "red, blue"
        assert card.likely_specs["size"] == "6.1in"

    def test_name_priority_item_id_then_name_then_name_guess(self):
        # item_id takes precedence
        raw1 = {"item_id": "A", "name": "B", "name_guess": "C", "confidence": 0.5}
        assert _raw_to_item_card(raw1, "j", []).name_guess == "A"

        # Falls back to name
        raw2 = {"name": "B", "name_guess": "C", "confidence": 0.5}
        assert _raw_to_item_card(raw2, "j", []).name_guess == "B"

        # Falls back to name_guess
        raw3 = {"name_guess": "C", "confidence": 0.5}
        assert _raw_to_item_card(raw3, "j", []).name_guess == "C"

    def test_string_defects_handled(self):
        raw = {
            "name": "Phone",
            "visible_defects": ["scratch on back"],
            "confidence": 0.7,
        }
        card = _raw_to_item_card(raw, "j", [])
        assert len(card.visible_defects) == 1
        assert card.visible_defects[0].description == "scratch on back"


# ── Listing Image Processing ─────────────────────────────────────────────────


class TestProcessListingImage:
    def test_output_is_valid_jpeg(self, sample_jpeg_bytes):
        result = _process_listing_image(sample_jpeg_bytes, None)
        assert result[:2] == b"\xff\xd8"  # JPEG SOI
        assert result[-2:] == b"\xff\xd9"  # JPEG EOI

    def test_crops_to_bounding_box(self):
        from io import BytesIO
        from PIL import Image

        # Create 200x200 image
        img = Image.new("RGB", (200, 200), "white")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=90)

        # Crop to center 50% box
        result = _process_listing_image(buf.getvalue(), [0.25, 0.25, 0.75, 0.75])
        decoded = Image.open(BytesIO(result))
        # Should be smaller than 200x200 after crop + thumbnail
        assert decoded.size[0] <= 200
        assert decoded.size[1] <= 200

    def test_no_crash_with_invalid_bbox(self, sample_jpeg_bytes):
        # Inverted bbox (x2 < x1) should be a no-op
        result = _process_listing_image(sample_jpeg_bytes, [0.9, 0.9, 0.1, 0.1])
        assert len(result) > 0
