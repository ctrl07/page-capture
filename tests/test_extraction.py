"""Tests for extraction.py — rule engine, ruleset persistence, and SEO fields."""

from __future__ import annotations

import json

from extraction import (
    ALL_SEO_FIELDS,
    EXTENDED_SEO_FIELDS,
    STANDARD_SEO_FIELDS,
    apply_regex,
    build_extraction_js,
    build_seo_js,
    delete_ruleset,
    get_seo_field_names,
    get_seo_fields_by_category,
    get_standard_seo_fields,
    list_rulesets,
    load_ruleset,
    parse_seo_fields,
    save_ruleset,
)


class TestBuildExtractionJs:
    def test_text_single(self):
        js = build_extraction_js([{"name": "title", "selector": "h1", "type": "text"}])
        assert "document.querySelector" in js
        assert "textContent" in js
        assert "return JSON.stringify(r)" in js

    def test_text_multiple(self):
        js = build_extraction_js([{"name": "items", "selector": ".item", "type": "text", "multiple": True}])
        assert "Array.from" in js

    def test_attribute(self):
        js = build_extraction_js([{"name": "link", "selector": "a.hero", "type": "attribute", "attribute": "href"}])
        assert "getAttribute" in js

    def test_count(self):
        js = build_extraction_js([{"name": "count", "selector": ".card", "type": "count"}])
        assert ".length" in js

    def test_exists(self):
        js = build_extraction_js([{"name": "has_banner", "selector": ".banner", "type": "exists"}])
        assert "!==null" in js

    def test_html(self):
        js = build_extraction_js([{"name": "content", "selector": ".main", "type": "html"}])
        assert "innerHTML" in js

    def test_empty_rules(self):
        js = build_extraction_js([])
        assert js == "(()=>{var r={};;return JSON.stringify(r);})()"


class TestApplyRegex:
    def test_no_regex(self):
        assert apply_regex("hello", "") == "hello"

    def test_match(self):
        assert apply_regex("price: $12.99", r"\d+\.\d+") == "12.99"

    def test_no_match(self):
        assert apply_regex("no price here", r"\d+\.\d+") == "no price here"

    def test_list_values(self):
        result = apply_regex(["$1.00", "$2.00", "free"], r"\d+")
        assert result == ["1", "2", "free"]

    def test_invalid_regex(self):
        assert apply_regex("test", "[invalid") == "test"


class TestRulesets:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extraction, "RULESETS_DIR", tmp_path)
        rules = [{"name": "test", "selector": "h1", "type": "text"}]
        save_ruleset(rules, "test-rules")
        loaded = load_ruleset("test-rules")
        assert loaded == rules

    def test_list_rulesets(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extraction, "RULESETS_DIR", tmp_path)
        save_ruleset([{"name": "a", "selector": "h1", "type": "text"}], "alpha")
        save_ruleset([{"name": "b", "selector": "h2", "type": "text"}], "beta")
        names = list_rulesets()
        assert "alpha" in names
        assert "beta" in names

    def test_delete_ruleset(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extraction, "RULESETS_DIR", tmp_path)
        save_ruleset([{"name": "x", "selector": "h1", "type": "text"}], "to-delete")
        assert delete_ruleset("to-delete") is True
        assert load_ruleset("to-delete") == []

    def test_delete_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extraction, "RULESETS_DIR", tmp_path)
        assert delete_ruleset("does-not-exist") is False

    def test_load_nonexistent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(extraction, "RULESETS_DIR", tmp_path)
        assert load_ruleset("nope") == []


# Need to import extraction module for monkeypatching
import extraction  # noqa: E402


class TestBuildSeoJs:
    def test_standard_fields_produces_js(self):
        fields = get_standard_seo_fields()
        js = build_seo_js(fields)
        assert "return JSON.stringify(r)" in js
        assert "document.title" in js
        assert "link[rel=" in js

    def test_empty_fields(self):
        js = build_seo_js([])
        assert "return JSON.stringify(r)" in js
        assert "var r={}" in js

    def test_meta_field(self):
        fields = [{"name": "desc", "type": "meta", "selector": 'meta[name="description"]'}]
        js = build_seo_js(fields)
        assert "querySelector" in js
        assert "getAttribute('content')" in js
        assert "desc" in js

    def test_count_field(self):
        fields = [{"name": "img_count", "type": "count", "selector": "img"}]
        js = build_seo_js(fields)
        assert "querySelectorAll" in js
        assert ".length" in js

    def test_exists_field(self):
        fields = [{"name": "has_banner", "type": "exists", "selector": ".banner"}]
        js = build_seo_js(fields)
        assert "!==null" in js

    def test_builtin_field(self):
        fields = [{"name": "title", "type": "builtin", "js_key": "title"}]
        js = build_seo_js(fields)
        assert "document.title" in js

    def test_derived_field_skipped(self):
        fields = [
            {"name": "title", "type": "builtin", "js_key": "title"},
            {"name": "title_len", "type": "derived", "derived_from": "title"},
        ]
        js = build_seo_js(fields)
        assert "title_len" not in js
        assert "document.title" in js

    def test_text_single(self):
        fields = [{"name": "h1", "type": "text", "selector": "h1"}]
        js = build_seo_js(fields)
        assert "querySelector" in js
        assert "textContent" in js

    def test_text_multiple(self):
        fields = [{"name": "items", "type": "text", "selector": ".item", "multiple": True}]
        js = build_seo_js(fields)
        assert "Array.from" in js

    def test_helpers_included(self):
        fields = [{"name": "title", "type": "builtin", "js_key": "title"}]
        js = build_seo_js(fields)
        assert "const q =" in js
        assert "const qa =" in js
        assert "const metaContent =" in js

    def test_all_extended_builtins_have_js(self):
        """Every extended builtin field should have a JS expression defined."""
        from extraction import _SEO_JS_EXPRS
        for f in EXTENDED_SEO_FIELDS:
            if f["type"] == "builtin":
                assert f["js_key"] in _SEO_JS_EXPRS, f"Missing JS expr for {f['js_key']}"


class TestParseSeoFields:
    def test_basic_fields(self):
        raw = json.dumps({"title": "Hello", "h1": "World"})
        fields = [
            {"name": "title", "type": "builtin", "js_key": "title"},
            {"name": "h1", "type": "builtin", "js_key": "h1"},
        ]
        result = parse_seo_fields(raw, fields)
        assert result["title"] == "Hello"
        assert result["h1"] == "World"

    def test_derived_title_len(self):
        raw = json.dumps({"title": "Hello World"})
        fields = [
            {"name": "title", "type": "builtin", "js_key": "title"},
            {"name": "title_len", "type": "derived", "derived_from": "title"},
        ]
        result = parse_seo_fields(raw, fields)
        assert result["title"] == "Hello World"
        assert result["title_len"] == 11

    def test_derived_meta_desc_len(self):
        raw = json.dumps({"meta_description": "A short description"})
        fields = [
            {"name": "meta_description", "type": "meta", "selector": 'meta[name="description"]'},
            {"name": "meta_desc_len", "type": "derived", "derived_from": "meta_description"},
        ]
        result = parse_seo_fields(raw, fields)
        assert result["meta_desc_len"] == 19

    def test_missing_field_defaults(self):
        raw = json.dumps({})
        fields = [
            {"name": "title", "type": "builtin", "js_key": "title"},
            {"name": "count", "type": "count", "selector": "img"},
        ]
        result = parse_seo_fields(raw, fields)
        assert result["title"] == ""
        assert result["count"] == 0

    def test_empty_raw(self):
        result = parse_seo_fields("", [{"name": "x", "type": "text", "selector": "h1"}])
        assert result["x"] == ""

    def test_standard_fields_roundtrip(self):
        """Standard fields dict produces the expected CSV column names."""
        fields = get_standard_seo_fields()
        names = [f["name"] for f in fields]
        assert "title" in names
        assert "meta_description" in names
        assert "h1" in names
        assert "og_title" in names
        assert "word_count" in names
        assert "internal_links" in names
        assert "images_missing_alt" in names
        assert len(fields) == 17


class TestSeoFieldConstants:
    def test_standard_count(self):
        assert len(STANDARD_SEO_FIELDS) == 17

    def test_extended_count(self):
        assert len(EXTENDED_SEO_FIELDS) == 19

    def test_all_count(self):
        assert len(ALL_SEO_FIELDS) == 36

    def test_get_standard_returns_copy(self):
        a = get_standard_seo_fields()
        b = get_standard_seo_fields()
        assert a == b
        a[0]["name"] = "mutated"
        assert b[0]["name"] != "mutated"

    def test_fields_by_category(self):
        cats = get_seo_fields_by_category()
        assert "meta" in cats
        assert "open_graph" in cats
        assert "twitter" in cats
        assert "links" in cats
        assert "images" in cats
        assert "schema" in cats

    def test_field_names(self):
        names = get_seo_field_names()
        assert isinstance(names, list)
        assert all(isinstance(n, str) for n in names)
        assert len(names) == 17

    def test_all_fields_have_required_keys(self):
        for f in ALL_SEO_FIELDS:
            assert "name" in f
            assert "type" in f
            assert "category" in f
            assert "description" in f


class TestMetaExtractionType:
    def test_meta_type_in_build_extraction_js(self):
        js = build_extraction_js([{"name": "desc", "selector": 'meta[name="description"]', "type": "meta"}])
        assert "meta[name=" in js
        assert "getAttribute('content')" in js

    def test_meta_type_in_extra(self):
        js = build_extraction_js([{"name": "og", "selector": 'meta[property="og:title"]', "type": "meta"}])
        assert "meta[property=" in js
