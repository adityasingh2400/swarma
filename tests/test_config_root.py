"""Tests for config.py (root-level v2 config used by orchestrator and playbooks)."""
from __future__ import annotations

from pathlib import Path

from config import Settings, settings


class TestRootSettings:
    def test_singleton_loads(self):
        assert settings is not None
        assert isinstance(settings, Settings)

    def test_browser_use_defaults(self):
        s = Settings()
        assert s.max_concurrent_agents > 0
        assert isinstance(s.use_cloud, bool)
        assert isinstance(s.use_chat_browser_use, bool)

    def test_screencast_fps_positive(self):
        s = Settings()
        assert s.screencast_fps > 0

    def test_storage_state_map_all_platforms(self):
        s = Settings()
        ssm = s.storage_state_map
        assert "ebay" in ssm
        assert "facebook" in ssm
        assert "mercari" in ssm
        assert "depop" in ssm

    def test_storage_state_map_returns_none_for_missing_cookies(self):
        """Cookie files won't exist in test env → values should be None."""
        s = Settings(
            ebay_cookies="./nonexistent/ebay.json",
            facebook_cookies="./nonexistent/facebook.json",
            mercari_cookies="./nonexistent/mercari.json",
            depop_cookies="./nonexistent/depop.json",
        )
        ssm = s.storage_state_map
        for platform, path in ssm.items():
            assert path is None, f"{platform} should be None for missing cookie file"

    def test_ensure_dirs_creates_directories(self, tmp_path):
        s = Settings(
            upload_dir=str(tmp_path / "uploads"),
            frames_dir=str(tmp_path / "frames"),
            optimized_dir=str(tmp_path / "optimized"),
            jobs_dir=str(tmp_path / "jobs"),
            listing_images_dir=str(tmp_path / "listing-images"),
        )
        s.ensure_dirs()
        assert (tmp_path / "uploads").is_dir()
        assert (tmp_path / "frames").is_dir()
        assert (tmp_path / "optimized").is_dir()
        assert (tmp_path / "jobs").is_dir()
        assert (tmp_path / "listing-images").is_dir()

    def test_gemini_keys_present(self):
        s = Settings()
        assert hasattr(s, "gemini_api_key")
        for i in range(2, 11):
            assert hasattr(s, f"gemini_api_key_{i}")

    def test_auth_cookie_paths_are_strings(self):
        s = Settings()
        assert isinstance(s.ebay_cookies, str)
        assert isinstance(s.facebook_cookies, str)
        assert isinstance(s.mercari_cookies, str)
        assert isinstance(s.depop_cookies, str)

    def test_api_defaults(self):
        s = Settings()
        assert s.api_host == "0.0.0.0"
        assert s.api_port == 8080
