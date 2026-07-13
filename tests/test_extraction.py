"""Tests for extraction.py — rule engine and ruleset persistence."""

from __future__ import annotations

from extraction import (
    apply_regex,
    build_extraction_js,
    delete_ruleset,
    list_rulesets,
    load_ruleset,
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
