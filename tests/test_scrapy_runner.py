"""Tests for the curl_cffi fast-crawl integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestFetchAndExtract:
    """Tests for _fetch_and_extract."""

    def test_import(self):
        from runners import _fetch_and_extract
        assert _fetch_and_extract is not None

    def test_extracts_title(self):
        from runners import _fetch_and_extract

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = """
        <html>
        <head><title>My Page Title</title></head>
        <body>
            <h1>Main Heading</h1>
            <h2>Section One</h2>
            <p>Some content here with multiple words for counting.</p>
            <a href="/about">About</a>
            <a href="https://other.com">External</a>
            <img src="pic.jpg" alt="A picture">
            <img src="no-alt.jpg">
            <meta name="description" content="A test description">
            <link rel="canonical" href="https://example.com/page">
            <meta property="og:title" content="OG Title">
            <script type="application/ld+json">{"@type": "WebPage"}</script>
        </body>
        </html>
        """

        with patch("curl_cffi.requests.get", return_value=mock_resp):
            result = _fetch_and_extract("https://example.com/page", {}, "TestBot/1.0")

        assert result["url"] == "https://example.com/page"
        assert result["status"] == "ok"
        assert result["status_code"] == 200
        assert result["title"] == "My Page Title"
        assert result["title_len"] == 13
        assert result["h1"] == "Main Heading"
        assert "Section One" in result["h2s"]
        assert result["meta_description"] == "A test description"
        assert result["canonical"] == "https://example.com/page"
        assert result["og_title"] == "OG Title"
        assert result["schema_types"] == "WebPage"
        assert result["internal_links"] == 1
        assert result["external_links"] == 1
        assert result["images_missing_alt"] == 1

    def test_empty_page(self):
        from runners import _fetch_and_extract

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><head><title></title></head><body></body></html>"

        with patch("curl_cffi.requests.get", return_value=mock_resp):
            result = _fetch_and_extract("https://example.com", {}, "")

        assert result["title"] == ""
        assert result["title_len"] == 0
        assert result["word_count"] == 0
        assert result["internal_links"] == 0

    def test_http_error(self):
        from runners import _fetch_and_extract

        with patch("curl_cffi.requests.get", side_effect=Exception("Connection refused")):
            result = _fetch_and_extract("https://example.com", {}, "")

        assert result["status"] == "error: Connection refused"


class TestFastRunner:
    """Tests for FastRunnerLegacy."""

    def test_import(self):
        from runners import FastRunnerLegacy
        assert FastRunnerLegacy is not None

    def test_init(self, tmp_path):
        from runners import FastRunnerLegacy

        urls = ["https://example.com", "https://example.com/about"]
        runtime_cfg = {
            "viewport": {"width": 1920, "height": 1080},
            "timing": {"stabilization_ms": 800, "inter_page_delay_min": 0.3, "inter_page_delay_max": 0.5},
        }
        runner = FastRunnerLegacy(urls, runtime_cfg, tmp_path / "output")
        assert runner.urls == urls
        assert runner.progress_total == 2
        assert runner.progress_done == 0
        assert runner.status == "queued"
        assert runner.results == {"seo": []}
        assert runner.cancelled is False

    def test_init_with_seo_fields(self, tmp_path):
        from extraction import get_standard_seo_fields
        from runners import FastRunnerLegacy

        fields = get_standard_seo_fields()
        runner = FastRunnerLegacy(
            ["https://example.com"],
            {"viewport": {"width": 800, "height": 600}, "timing": {"stabilization_ms": 500}},
            tmp_path / "out",
            seo_fields=fields,
        )
        assert runner.seo_fields == fields


class TestExtractSession:
    """Tests for PageCapture.extract_session()."""

    def test_import(self):
        from page_capture import PageCapture
        assert hasattr(PageCapture, "extract_session")

    def test_extract_session_returns_dict(self):
        from page_capture import PageCapture

        mock_sb = MagicMock()
        mock_sb.get_cookies.return_value = [
            {"name": "cf_clearance", "value": "abc", "domain": ".example.com", "path": "/",
             "secure": True, "httpOnly": True, "sameSite": "None"},
        ]
        mock_sb.cdp.get_user_agent.return_value = "Mozilla/5.0 TestAgent"
        mock_sb.evaluate.return_value = ""

        config = {"viewport": {"width": 800, "height": 600}, "timing": {}, "hide": {}}
        page = PageCapture(mock_sb, config)
        session = page.extract_session()

        assert "cookies" in session
        assert "user_agent" in session
        assert len(session["cookies"]) == 1
        assert session["cookies"][0]["name"] == "cf_clearance"
        assert session["cookies"][0]["value"] == "abc"
        assert session["user_agent"] == "Mozilla/5.0 TestAgent"

    def test_extract_session_handles_empty_cookies(self):
        from page_capture import PageCapture

        mock_sb = MagicMock()
        mock_sb.get_cookies.return_value = []
        mock_sb.cdp.get_user_agent.return_value = "UA"
        mock_sb.evaluate.return_value = ""

        config = {"viewport": {"width": 800, "height": 600}, "timing": {}, "hide": {}}
        page = PageCapture(mock_sb, config)
        session = page.extract_session()

        assert session["cookies"] == []
        assert session["user_agent"] == "UA"

    def test_extract_session_handles_exception(self):
        from page_capture import PageCapture

        mock_sb = MagicMock()
        mock_sb.get_cookies.side_effect = Exception("browser closed")
        mock_sb.cdp.get_user_agent.side_effect = Exception("no browser")
        mock_sb.evaluate.return_value = "FallbackUA/1.0"

        config = {"viewport": {"width": 800, "height": 600}, "timing": {}, "hide": {}}
        page = PageCapture(mock_sb, config)
        session = page.extract_session()

        assert session["cookies"] == []
        assert session["user_agent"] == "FallbackUA/1.0"
