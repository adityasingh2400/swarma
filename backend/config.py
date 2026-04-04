from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Gemini — supports up to 10 API keys for concurrent round-robin
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

    # ASI:One
    asi_one_api_key: str = ""

    # eBay
    ebay_app_id: str = ""
    ebay_cert_id: str = ""
    ebay_dev_id: str = ""
    ebay_oauth_token: str = ""
    ebay_sandbox: bool = True

    # Amazon PA-API
    amazon_access_key: str = ""
    amazon_secret_key: str = ""
    amazon_partner_tag: str = ""

    # Agent Seeds
    intake_agent_seed: str = "reroute-intake-agent-seed-phrase-change-me"
    condition_fusion_agent_seed: str = "reroute-condition-fusion-seed-phrase-change-me"
    return_agent_seed: str = "reroute-return-agent-seed-phrase-change-me"
    trade_in_agent_seed: str = "reroute-trade-in-agent-seed-phrase-change-me"
    marketplace_resale_agent_seed: str = "reroute-marketplace-resale-seed-phrase-change-me"
    repair_roi_agent_seed: str = "reroute-repair-roi-agent-seed-phrase-change-me"
    bundle_opportunity_agent_seed: str = "reroute-bundle-opportunity-seed-phrase-change-me"
    route_decider_agent_seed: str = "reroute-route-decider-agent-seed-phrase-change-me"
    concierge_agent_seed: str = "reroute-concierge-agent-seed-phrase-change-me"

    # Server
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    bureau_port: int = 8000
    upload_dir: str = "./data/uploads"
    frames_dir: str = "./data/frames"
    optimized_dir: str = "./data/optimized"
    jobs_dir: str = "./data/jobs"

    # Agentverse
    agentverse_api_key: str = ""

    # Browser-Use
    browser_use_api_key: str = ""
    max_concurrent_agents: int = 12
    context_pool_size: int = 12

    # Screenshot streaming
    screenshot_capture_fps: float = 2.0
    screenshot_grid_quality: int = 60
    screenshot_grid_width: int = 320
    screenshot_grid_height: int = 240
    screenshot_focus_quality: int = 80
    screenshot_focus_width: int = 1280
    screenshot_focus_height: int = 960
    screenshot_grid_delivery_fps: float = 1.0
    screenshot_focus_delivery_fps: float = 3.0

    # Intake
    intake_batch_size: int = 5
    intake_ffmpeg_fps: float = 1.0
    intake_min_frames_required: int = 3
    gemini_detection_model: str = "gemini-2.5-flash-lite-preview-06-17"
    gemini_detail_model: str = "gemini-2.5-flash-preview-05-20"

    # Feature Flags
    enable_facebook_adapter: bool = False
    enable_depop_adapter: bool = False
    demo_mode: bool = True

    @property
    def ebay_base_url(self) -> str:
        if self.ebay_sandbox:
            return "https://api.sandbox.ebay.com"
        return "https://api.ebay.com"

    @property
    def ebay_browse_url(self) -> str:
        return f"{self.ebay_base_url}/buy/browse/v1"

    @property
    def ebay_sell_url(self) -> str:
        return f"{self.ebay_base_url}/sell/inventory/v1"

    def ensure_dirs(self) -> None:
        for d in (self.upload_dir, self.frames_dir, self.optimized_dir, self.jobs_dir):
            Path(d).mkdir(parents=True, exist_ok=True)


settings = Settings()
