"""Tests for importers.py — URL parsing, validation, and import functions."""

from __future__ import annotations

from importers import (
    import_from_csv_file,
    is_valid_url,
    parse_urls_text,
)


class TestIsValidUrl:
    def test_valid_http(self):
        assert is_valid_url("http://example.com") is True

    def test_valid_https(self):
        assert is_valid_url("https://example.com/page") is True

    def test_invalid_no_scheme(self):
        assert is_valid_url("example.com") is False

    def test_invalid_ftp(self):
        assert is_valid_url("ftp://example.com") is False

    def test_empty(self):
        assert is_valid_url("") is False

    def test_with_path_and_query(self):
        assert is_valid_url("https://example.com/path?q=1&b=2") is True


class TestParseUrlsText:
    def test_one_per_line(self):
        raw = "https://a.com\nhttps://b.com\nhttps://c.com"
        result = parse_urls_text(raw)
        assert result == ["https://a.com", "https://b.com", "https://c.com"]

    def test_comma_separated(self):
        raw = "https://a.com, https://b.com"
        result = parse_urls_text(raw)
        assert result == ["https://a.com", "https://b.com"]

    def test_deduplication(self):
        raw = "https://a.com\nhttps://a.com\nhttps://b.com"
        result = parse_urls_text(raw)
        assert result == ["https://a.com", "https://b.com"]

    def test_skips_comments(self):
        raw = "# comment\nhttps://a.com\n# another\nhttps://b.com"
        result = parse_urls_text(raw)
        assert result == ["https://a.com", "https://b.com"]

    def test_skips_empty(self):
        raw = "\n\nhttps://a.com\n\n"
        result = parse_urls_text(raw)
        assert result == ["https://a.com"]

    def test_windows_line_endings(self):
        raw = "https://a.com\r\nhttps://b.com"
        result = parse_urls_text(raw)
        assert result == ["https://a.com", "https://b.com"]


class TestImportFromCsvFile:
    def test_single_column(self):
        csv = "https://a.com\nhttps://b.com"
        pairs = import_from_csv_file(csv)
        assert len(pairs) == 2
        assert pairs[0] == ("https://a.com", None)
        assert pairs[1] == ("https://b.com", None)

    def test_two_columns(self):
        csv = "https://old.com,https://new.com\nhttps://old2.com,https://new2.com"
        pairs = import_from_csv_file(csv)
        assert len(pairs) == 2
        assert pairs[0] == ("https://old.com", "https://new.com")

    def test_skips_invalid(self):
        csv = "https://a.com\nnot-a-url\nhttps://b.com"
        pairs = import_from_csv_file(csv)
        assert len(pairs) == 2

    def test_bytes_input(self):
        csv = b"https://a.com\nhttps://b.com"
        pairs = import_from_csv_file(csv)
        assert len(pairs) == 2
