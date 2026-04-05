"""Tests for extraction.py — JS extraction snippets and tool factories."""
from __future__ import annotations

import json

import pytest

from extraction import (
    EBAY_SOLD_JS,
    MERCARI_JS,
    FACEBOOK_JS,
    DEPOP_JS,
    PLATFORM_JS,
    get_extraction_js,
    make_initial_actions,
    make_research_tools,
)


# ── Platform JS Registry ────────────────────────────────────────────────────


class TestPlatformJS:
    def test_all_4_platforms_have_js(self):
        assert "ebay" in PLATFORM_JS
        assert "mercari" in PLATFORM_JS
        assert "facebook" in PLATFORM_JS
        assert "depop" in PLATFORM_JS

    def test_each_js_is_an_iife(self):
        for platform, js in PLATFORM_JS.items():
            assert js.strip().startswith("("), f"{platform} JS is not an IIFE"
            assert js.strip().endswith("()"), f"{platform} JS does not self-invoke"

    def test_each_js_returns_json_stringify(self):
        for platform, js in PLATFORM_JS.items():
            assert "JSON.stringify" in js, f"{platform} JS doesn't return JSON.stringify"

    def test_ebay_js_extracts_prices(self):
        assert "s-item" in EBAY_SOLD_JS
        assert "prices" in EBAY_SOLD_JS

    def test_mercari_js_targets_item_cells(self):
        assert "ItemCell" in MERCARI_JS or "price" in MERCARI_JS.lower()

    def test_facebook_js_extracts_dollar_prices(self):
        assert "$" in FACEBOOK_JS or "\\$" in FACEBOOK_JS

    def test_depop_js_extracts_dollar_prices(self):
        assert "$" in DEPOP_JS or "\\$" in DEPOP_JS

    def test_ebay_js_includes_total_listings(self):
        assert "total_listings" in EBAY_SOLD_JS

    def test_all_js_return_avg_field(self):
        for platform, js in PLATFORM_JS.items():
            assert "avg" in js, f"{platform} JS missing avg field"

    def test_all_js_return_count_field(self):
        for platform, js in PLATFORM_JS.items():
            assert "count" in js, f"{platform} JS missing count field"


# ── get_extraction_js ────────────────────────────────────────────────────────


class TestGetExtractionJS:
    def test_returns_correct_js_for_known_platforms(self):
        assert get_extraction_js("ebay") == EBAY_SOLD_JS
        assert get_extraction_js("mercari") == MERCARI_JS
        assert get_extraction_js("facebook") == FACEBOOK_JS
        assert get_extraction_js("depop") == DEPOP_JS

    def test_unknown_platform_falls_back_to_facebook(self):
        result = get_extraction_js("unknown_platform")
        assert result == FACEBOOK_JS


# ── make_initial_actions ─────────────────────────────────────────────────────


class TestMakeInitialActions:
    def test_returns_list_with_navigate(self):
        actions = make_initial_actions("ebay", "https://ebay.com/sch/test")
        assert isinstance(actions, list)
        assert len(actions) >= 1
        assert "navigate" in actions[0]
        assert actions[0]["navigate"]["url"] == "https://ebay.com/sch/test"

    def test_url_preserved_exactly(self):
        url = "https://example.com/search?q=test+query&filter=true"
        actions = make_initial_actions("facebook", url)
        assert actions[0]["navigate"]["url"] == url


# ── make_research_tools ──────────────────────────────────────────────────────


class TestMakeResearchTools:
    def test_returns_none_for_all_platforms(self):
        for platform in ["ebay", "mercari", "facebook", "depop", "amazon"]:
            assert make_research_tools(platform) is None

    def test_returns_none_for_unknown_platform(self):
        assert make_research_tools("unknown") is None
