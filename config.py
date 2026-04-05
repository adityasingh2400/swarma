from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Browser-Use
    browser_use_api_key: str = ""
    use_cloud: bool = True
    use_chat_browser_use: bool = False  # True = paid ChatBrowserUse, False = Gemini
    max_concurrent_agents: int = 15

    # Gemini — round-robin keys from v1
    gemini_api_key: str = ""
    gemini_api_key_2: str = ""
    gemini_api_key_3: str = ""
    gemini_api_key_4: str = ""
    gemini_api_key_5: str = ""
    gemini_api_key_6: str = ""
    gemini_api_key_7: str = ""
    gemini_api_key_8: str = ""
    gemini_api_key_9: str = ""
    gemini_api_key_10: str = ""

    # Auth — storage_state JSON files per platform
    ebay_cookies: str = "./auth/ebay-cookies.json"
    facebook_cookies: str = "./auth/facebook-cookies.json"
    mercari_cookies: str = "./auth/mercari-cookies.json"
    depop_cookies: str = "./auth/depop-cookies.json"

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    upload_dir: str = "./data/uploads"
    frames_dir: str = "./data/frames"
    optimized_dir: str = "./data/optimized"
    jobs_dir: str = "./data/jobs"
    listing_images_dir: str = "./data/listing-images"

    @property
    def storage_state_map(self) -> dict[str, str | None]:
        """Map platform name to cookie file path, or None if file doesn't exist."""
        mapping = {
            "ebay": self.ebay_cookies,
            "facebook": self.facebook_cookies,
            "mercari": self.mercari_cookies,
            "depop": self.depop_cookies,
        }
        return {
            platform: path if Path(path).exists() else None
            for platform, path in mapping.items()
        }

    def ensure_dirs(self) -> None:
        for d in (self.upload_dir, self.frames_dir, self.optimized_dir,
                  self.jobs_dir, self.listing_images_dir):
            Path(d).mkdir(parents=True, exist_ok=True)


settings = Settings()
