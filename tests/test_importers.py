"""Tests for importers.py — URL parsing, validation, and import functions."""

from __future__ import annotations

import pytest

from importers import (
    import_from_csv_file,
    import_from_sitemap_xml,
    import_from_wp_xml,
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


class TestImportFromSitemapXml:
    def test_basic_sitemap(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://example.com/contact</loc></url>
</urlset>"""
        urls = import_from_sitemap_xml(xml)
        assert len(urls) == 3
        assert "https://example.com/" in urls
        assert "https://example.com/about" in urls

    def test_no_namespace(self):
        xml = """<?xml version="1.0"?>
<urlset>
  <url><loc>https://test.com/page1</loc></url>
  <url><loc>https://test.com/page2</loc></url>
</urlset>"""
        urls = import_from_sitemap_xml(xml)
        assert len(urls) == 2

    def test_invalid_xml(self):
        with pytest.raises(ValueError, match="Invalid XML"):
            import_from_sitemap_xml("not xml at all")

    def test_no_loc_elements(self):
        xml = """<?xml version="1.0"?>
<urlset><url><loc></loc></url></urlset>"""
        with pytest.raises(ValueError, match="No <loc>"):
            import_from_sitemap_xml(xml)


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


class TestImportFromWpXml:
    def test_basic_export(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:content="http://purl.org/rss/1.0/modules/content/"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:wp="http://wordpress.org/export/1.2/">
<channel>
  <item>
    <title>Hello World</title>
    <link>https://example.com/hello-world</link>
    <wp:post_date>2024-01-15 10:30:00</wp:post_date>
    <wp:post_type>post</wp:post_type>
    <category domain="category" nicename="news">News</category>
    <category domain="post_tag" nicename="intro">Intro</category>
  </item>
</channel>
</rss>"""
        posts = import_from_wp_xml(xml)
        assert len(posts) == 1
        assert posts[0]["title"] == "Hello World"
        assert posts[0]["url"] == "https://example.com/hello-world"
        assert posts[0]["date"] == "2024-01-15"
        assert "News" in posts[0]["category"]
        assert "Intro" in posts[0]["tags"]

    def test_no_posts(self):
        xml = """<?xml version="1.0"?>
<rss version="2.0"><channel></channel></rss>"""
        with pytest.raises(ValueError, match="No posts/pages"):
            import_from_wp_xml(xml)
