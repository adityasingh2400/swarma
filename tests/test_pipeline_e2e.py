"""End-to-end pipeline tests — verify the product end goal is achieved.

Uses the real test video (./data/uploads/0be92aec26ed.mp4) and real API keys.
Tests the full flow: video → intake → items → route decision → listing tasks.

Run:
    python -m pytest tests/test_pipeline_e2e.py -v -s --tb=short
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from backend.config import settings
from backend.intake import (
    PipelineTimings,
    extract_audio,
    extract_frames_streaming,
    streaming_analysis,
    _extract_segment_frames,
    _filter_quality_frames,
    _raw_to_item_card,
)
from backend.models.item_card import ItemCard, ItemCategory
from models.listing_package import ListingPackage, ListingImage
from contracts import RouteDecision
from route_decision import route_decision
from playbooks.ebay import EbayPlaybook
from playbooks.facebook import FacebookPlaybook
from playbooks.mercari import MercariPlaybook
from playbooks.depop import DepopPlaybook
from playbooks.amazon import AmazonPlaybook


# ── Fixtures ─────────────────────────────────────────────────────────────────

VIDEO_PATH = str(Path(__file__).resolve().parent.parent / "data" / "uploads" / "cb369e902a37d1df.mp4")


@pytest.fixture(scope="module")
def video_path():
    p = Path(VIDEO_PATH)
    if not p.exists():
        pytest.skip(f"Test video not found: {VIDEO_PATH}")
    return str(p)


# ── Phase 1: Frame Extraction (ffmpeg) ──────────────────────────────────────

class TestFrameExtractionPipeline:
    """Verify that ffmpeg can extract frames from the real video."""

    def test_streaming_extraction_produces_frames(self, video_path):
        frames = []

        async def _collect():
            async for idx, data in extract_frames_streaming(video_path, fps=1.0):
                frames.append((idx, data))

        asyncio.run(_collect())
        assert len(frames) >= 10, f"Expected 10+ frames at 1fps, got {len(frames)}"
        # All frames should be valid JPEGs
        for idx, data in frames:
            assert data[:2] == b"\xff\xd8", f"Frame {idx} not JPEG"

    def test_segment_extraction_produces_segments(self, video_path):
        segments = asyncio.run(_extract_segment_frames(video_path, num_segments=10))
        assert len(segments) == 10
        non_empty = [s for s in segments if s]
        assert len(non_empty) >= 5, f"Expected 5+ non-empty segments, got {len(non_empty)}"

    def test_opencv_filter_selects_sharp_frames(self, video_path):
        """OpenCV quality filter should reduce frame count while keeping sharp ones."""
        segments = asyncio.run(_extract_segment_frames(video_path, num_segments=5))
        all_frames = []
        for seg in segments:
            all_frames.extend(seg)

        filtered = _filter_quality_frames(all_frames, max_output_frames=10)
        assert len(filtered) <= 10
        assert len(filtered) >= 1


# ── Phase 2: Full Intake Pipeline (Video → Items) ──────────────────────────

class TestIntakePipeline:
    """Verify the full intake pipeline produces ItemCards from a real video.
    This is the core product end goal: video → identified items."""

    @pytest.fixture(scope="class")
    def intake_result(self, video_path):
        """Run the full intake pipeline once and share the result across tests."""
        result = asyncio.run(streaming_analysis(video_path, "e2e-test-001"))
        return result

    def test_returns_items(self, intake_result):
        items, timings, best_frames, _transcript = intake_result
        assert isinstance(items, list)
        assert len(items) >= 1, "Intake should identify at least 1 item from the test video"

    def test_items_are_item_cards(self, intake_result):
        items, _, _, _ = intake_result
        for item in items:
            assert isinstance(item, ItemCard), f"Expected ItemCard, got {type(item)}"

    def test_items_have_required_fields(self, intake_result):
        items, _, _, _ = intake_result
        for item in items:
            assert item.name_guess, f"Item {item.item_id} has no name_guess"
            assert item.confidence > 0, f"Item {item.item_id} has zero confidence"
            assert item.category in ItemCategory, f"Item {item.item_id} has invalid category"

    def test_items_have_condition_labels(self, intake_result):
        items, _, _, _ = intake_result
        for item in items:
            assert item.condition_label in ("Like New", "Good", "Fair"), (
                f"Item {item.item_id} has unexpected condition: {item.condition_label}"
            )

    def test_timings_populated(self, intake_result):
        _, timings, _, _ = intake_result
        assert isinstance(timings, PipelineTimings)
        assert timings.total_sec > 0, "Total time should be > 0"
        assert timings.frame_count > 0, "Should have extracted frames"

    def test_best_frames_returned(self, intake_result):
        _, _, best_frames, _ = intake_result
        assert isinstance(best_frames, list)
        # Each entry should be (index, jpeg_bytes)
        for item in best_frames:
            assert len(item) == 2
            idx, data = item
            assert isinstance(idx, int)
            assert isinstance(data, bytes)

    def test_pipeline_completes_under_120s(self, intake_result):
        _, timings, _, _ = intake_result
        assert timings.total_sec < 120, (
            f"Pipeline took {timings.total_sec:.1f}s — should complete under 120s"
        )

    def test_no_exact_duplicate_names(self, intake_result):
        """Dedup should collapse items with identical names into one."""
        items, _, _, _ = intake_result
        names = [item.name_guess for item in items]
        unique_names = set(names)
        assert len(names) == len(unique_names), (
            f"Found duplicate item names after dedup: {names}"
        )

    def test_electronics_categorized_correctly(self, intake_result):
        """iPads and iPhones should be categorized as electronics, not other."""
        items, _, _, _ = intake_result
        for item in items:
            name_lower = item.name_guess.lower()
            if any(kw in name_lower for kw in ["ipad", "iphone", "phone", "tablet"]):
                assert item.category == ItemCategory.ELECTRONICS, (
                    f"'{item.name_guess}' should be electronics, got {item.category.value}"
                )


# ── Phase 3: Route Decision with Real Intake Output ────────────────────────

class TestRouteDecisionWithRealData:
    """Test that route decision works with realistic research data
    that would come from the marketplace agents."""

    def test_route_decision_with_intake_items(self):
        """Simulate the full flow: intake → research → route decision."""
        item = ItemCard(
            item_id="e2e-phone",
            name_guess="iPhone 14 Pro 128GB",
            category=ItemCategory.ELECTRONICS,
            confidence=0.9,
        )
        # Simulate research results from 5 marketplace agents
        research = {
            "ebay": {"avg_sold_price": 750.0, "listings_found": 12},
            "facebook": {"avg_sold_price": 700.0, "listings_found": 8},
            "mercari": {"avg_sold_price": 680.0, "listings_found": 6},
            "depop": {"avg_sold_price": 620.0, "listings_found": 3},
        }
        decision = route_decision(item, research)
        assert isinstance(decision, RouteDecision)
        assert len(decision.platforms) >= 2, "Should recommend at least 2 platforms"
        # Facebook ranks #1 due to low effort + fast speed offsetting eBay's value edge
        assert decision.platforms[0] in ("ebay", "facebook"), (
            f"Top platform should be ebay or facebook, got {decision.platforms[0]}"
        )
        assert all(decision.scores[p] > 0 for p in decision.platforms)


# ── Phase 4: Playbook Integration with Real Items ──────────────────────────

class TestPlaybookIntegrationWithRealItems:
    """Verify playbooks generate valid tasks from real intake output."""

    @pytest.fixture
    def real_item(self):
        return ItemCard(
            item_id="e2e-real-001",
            name_guess="Samsung Galaxy S23 Ultra 256GB",
            category=ItemCategory.ELECTRONICS,
            confidence=0.88,
            visible_defects=[],
        )

    @pytest.fixture
    def real_package(self, real_item):
        return ListingPackage(
            item_id=real_item.item_id,
            title="Samsung Galaxy S23 Ultra 256GB Phantom Black Unlocked",
            description="Excellent condition Samsung Galaxy S23 Ultra 256GB.",
            price_strategy=649.00,
            images=[
                ListingImage(path="/img/hero.jpg", role="hero"),
                ListingImage(path="/img/side.jpg", role="secondary"),
                ListingImage(path="/img/back.jpg", role="secondary"),
                ListingImage(path="/img/screen.jpg", role="secondary"),
            ],
        )

    def test_all_research_tasks_generate_valid_urls(self, real_item):
        playbooks = [EbayPlaybook(), FacebookPlaybook(), MercariPlaybook(),
                     DepopPlaybook(), AmazonPlaybook()]
        for pb in playbooks:
            task, actions = pb.research_task(real_item)
            assert len(actions) >= 1, f"{pb.platform} has no initial_actions"
            url = actions[0]["navigate"]["url"]
            assert "http" in url, f"{pb.platform} URL is not valid: {url}"
            assert real_item.name_guess.split()[0] in url or "Samsung" in url or "Galaxy" in url, (
                f"{pb.platform} URL doesn't contain item name: {url}"
            )

    def test_all_listing_tasks_contain_price(self, real_item, real_package):
        listing_playbooks = [EbayPlaybook(), FacebookPlaybook(), MercariPlaybook(), DepopPlaybook()]
        for pb in listing_playbooks:
            task, actions = pb.listing_task(real_item, real_package)
            assert "649.00" in task, f"{pb.platform} listing task missing price"

    def test_all_research_parse_handles_empty_results(self):
        playbooks = [EbayPlaybook(), FacebookPlaybook(), MercariPlaybook(),
                     DepopPlaybook(), AmazonPlaybook()]
        for pb in playbooks:
            result = pb.parse_research(None)
            assert "avg_sold_price" in result or "parts" in result, (
                f"{pb.platform} parse_research(None) missing expected keys"
            )


# ── Phase 5: Full Pipeline Flow (Intake → Decision → Listing Tasks) ────────

class TestFullPipelineFlow:
    """Test the complete product pipeline with the real test video.
    This is the top-level integration test verifying the end goal."""

    def test_video_to_listing_tasks(self, video_path):
        """THE product end goal test:
        1. Video → intake → items identified
        2. Items → simulated research → route decision
        3. Decision → listing tasks generated for top platforms
        """
        # Step 1: Run intake
        items, timings, best_frames, _transcript = asyncio.run(
            streaming_analysis(video_path, "e2e-full-flow")
        )
        assert len(items) >= 1, "Intake must identify at least 1 item"
        print(f"\n=== INTAKE RESULTS ===")
        print(f"Items found: {len(items)}")
        for item in items:
            print(f"  - {item.name_guess} ({item.category.value}) confidence={item.confidence:.2f}")
        print(f"Pipeline time: {timings.total_sec:.1f}s")
        print(f"Frames extracted: {timings.frame_count}")

        # Step 2: For each item, simulate research and run route decision
        playbooks = {
            "ebay": EbayPlaybook(),
            "facebook": FacebookPlaybook(),
            "mercari": MercariPlaybook(),
            "depop": DepopPlaybook(),
            "amazon": AmazonPlaybook(),
        }

        for item in items:
            # Verify research tasks can be generated
            for platform, pb in playbooks.items():
                task, actions = pb.research_task(item)
                assert task, f"Empty research task for {platform}/{item.name_guess}"
                assert actions, f"No initial actions for {platform}/{item.name_guess}"

            # Simulate research results (as if agents had run)
            simulated_research = {
                "ebay": {"avg_sold_price": 500.0, "listings_found": 8},
                "facebook": {"avg_sold_price": 450.0, "listings_found": 5},
                "mercari": {"avg_sold_price": 420.0, "listings_found": 4},
            }

            # Step 3: Route decision
            decision = route_decision(item, simulated_research)
            assert len(decision.platforms) >= 2
            print(f"\n--- Route Decision for {item.name_guess} ---")
            print(f"  Platforms: {decision.platforms}")
            print(f"  Prices: {decision.prices}")
            print(f"  Scores: {decision.scores}")

            # Step 4: Generate listing tasks for decided platforms
            package = ListingPackage(
                item_id=item.item_id,
                title=item.name_guess,
                description=f"{item.name_guess} in {item.condition_label} condition.",
                price_strategy=decision.prices.get(decision.platforms[0], 0.0),
                platforms=decision.platforms,
                prices=decision.prices,
                images=[ListingImage(path=p, role="hero" if i == 0 else "secondary")
                        for i, p in enumerate(item.hero_frame_paths[:4])],
            )

            for platform in decision.platforms:
                if platform in playbooks and platform != "amazon":
                    pb = playbooks[platform]
                    task, actions = pb.listing_task(item, package)
                    assert task, f"Empty listing task for {platform}"
                    assert actions, f"No initial actions for listing on {platform}"
                    print(f"  {platform} listing task: {len(task)} chars, {len(actions)} actions")

        print(f"\n=== FULL PIPELINE PASSED ===")


# ── Phase 6: Server Upload Endpoint Integration ────────────────────────────

class TestServerUploadIntegration:
    """Test the FastAPI upload endpoint with the real video."""

    def test_upload_video_returns_job_id(self, video_path):
        from fastapi.testclient import TestClient
        from backend.server import app, _jobs

        _jobs.clear()
        client = TestClient(app)
        with open(video_path, "rb") as f:
            resp = client.post("/api/upload", files={"video": ("test.mp4", f, "video/mp4")})
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "processing"
        job_id = data["job_id"]

        # Job should exist in store
        assert job_id in _jobs
        _jobs.clear()

    def test_job_status_queryable_after_upload(self, video_path):
        from fastapi.testclient import TestClient
        from backend.server import app, _jobs

        _jobs.clear()
        client = TestClient(app)
        with open(video_path, "rb") as f:
            resp = client.post("/api/upload", files={"video": ("test.mp4", f, "video/mp4")})
        job_id = resp.json()["job_id"]

        status_resp = client.get(f"/api/jobs/{job_id}")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["job"]["job_id"] == job_id
        _jobs.clear()
