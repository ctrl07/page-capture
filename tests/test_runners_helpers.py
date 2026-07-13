"""Tests for runners.py — utility functions (slugify, parse_seo_payload, build_runtime_config)."""

from __future__ import annotations

import json

from runners import build_runtime_config, parse_seo_payload, slugify


class TestSlugify:
    def test_basic_url(self):
        assert slugify("https://example.com/page") == "example_com_page"

    def test_with_path(self):
        assert slugify("https://example.com/some/deep/path") == "example_com_some_deep_path"

    def test_strips_protocol(self):
        result = slugify("https://test.com")
        assert result.startswith("test_com") or result == "test_com"

    def test_lowercase(self):
        result = slugify("HTTPS://EXAMPLE.COM")
        assert result == "example_com"

    def test_special_chars(self):
        result = slugify("https://example.com/page?id=1&foo=bar")
        assert "page" in result


class TestParseSeoPayload:
    def test_basic_fields(self):
        raw = json.dumps({
            "title": "My Page",
            "metaDesc": "A description",
            "h1": "Main Heading",
            "wordCount": 500,
        })
        result = parse_seo_payload(raw)
        assert result["title"] == "My Page"
        assert result["title_len"] == 7
        assert result["meta_description"] == "A description"
        assert result["meta_desc_len"] == 13
        assert result["h1"] == "Main Heading"
        assert result["word_count"] == 500

    def test_empty_payload(self):
        result = parse_seo_payload("")
        assert result["title"] == ""
        assert result["word_count"] == 0

    def test_og_fields(self):
        raw = json.dumps({
            "ogTitle": "OG Title",
            "ogDesc": "OG Desc",
            "ogImage": "https://example.com/img.jpg",
        })
        result = parse_seo_payload(raw)
        assert result["og_title"] == "OG Title"
        assert result["og_description"] == "OG Desc"
        assert result["og_image"] == "https://example.com/img.jpg"

    def test_link_counts(self):
        raw = json.dumps({"internal": 15, "external": 3})
        result = parse_seo_payload(raw)
        assert result["internal_links"] == 15
        assert result["external_links"] == 3


class TestBuildRuntimeConfig:
    def test_basic(self):
        config = {
            "timing": {
                "stabilization_ms": 800,
                "inter_page_delay_min": 0.3,
                "inter_page_delay_max": 0.5,
            },
            "hide": {"chat": [".chat-widget"]},
            "hide_visibility": {},
        }
        viewport = {"width": 1920, "height": 1080}
        result = build_runtime_config(config, viewport, 1000)
        assert result["viewport"] == viewport
        assert result["timing"]["stabilization_ms"] == 1000
        assert result["timing"]["inter_page_delay_min"] == 0.3
        assert result["hide"]["chat"] == [".chat-widget"]

    def test_custom_delay(self):
        config = {
            "timing": {"stabilization_ms": 500, "inter_page_delay_min": 0, "inter_page_delay_max": 1},
            "hide": {},
            "hide_visibility": {},
        }
        result = build_runtime_config(config, {"width": 800, "height": 600}, 2000)
        assert result["timing"]["stabilization_ms"] == 2000
