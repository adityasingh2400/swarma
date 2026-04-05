"""Tests for backend/config.py — settings validation."""
from __future__ import annotations

from backend.config import Settings, settings


class TestSettings:
    def test_singleton_loads(self):
        assert settings is not None
        assert isinstance(settings, Settings)

    def test_gemini_image_model_is_flash_lite(self):
        assert "flash-lite" in settings.gemini_image_model

    def test_no_multi_strategy_config(self):
        """S2 solidification removed gemini_detection_model, gemini_detail_model, intake_strategy."""
        assert not hasattr(settings, "intake_strategy")
        # These fields should not exist on the Settings class
        field_names = set(Settings.model_fields.keys())
        assert "gemini_detection_model" not in field_names
        assert "gemini_detail_model" not in field_names
        assert "intake_strategy" not in field_names

    def test_intake_defaults(self):
        s = Settings()
        assert s.intake_batch_size == 5
        assert s.intake_min_frames_required == 3
        assert s.intake_num_segments == 10
        assert s.intake_similarity_threshold == 0.85

    def test_screenshot_defaults(self):
        s = Settings()
        assert s.screenshot_capture_fps == 2.0
        assert s.screenshot_grid_width == 320
        assert s.screenshot_grid_height == 240
        assert s.screenshot_focus_width == 1280
        assert s.screenshot_focus_height == 960

    def test_ensure_dirs_creates_directories(self, tmp_path):
        s = Settings(
            upload_dir=str(tmp_path / "uploads"),
            frames_dir=str(tmp_path / "frames"),
            optimized_dir=str(tmp_path / "optimized"),
            jobs_dir=str(tmp_path / "jobs"),
        )
        s.ensure_dirs()
        assert (tmp_path / "uploads").is_dir()
        assert (tmp_path / "frames").is_dir()
        assert (tmp_path / "optimized").is_dir()
        assert (tmp_path / "jobs").is_dir()

    def test_gemini_keys_1_through_9(self):
        """Intake uses keys 1-9 for round-robin."""
        s = Settings()
        assert hasattr(s, "gemini_api_key")
        for i in range(2, 10):
            assert hasattr(s, f"gemini_api_key_{i}")

    def test_deepgram_and_groq_keys(self):
        """Audio pipeline requires these keys."""
        s = Settings()
        assert hasattr(s, "deepgram_api_key")
        assert hasattr(s, "groq_api_key")
