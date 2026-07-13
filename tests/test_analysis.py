"""Tests for analysis.py — SEO issue detection, health score, and PDF report."""

from __future__ import annotations

from analysis import (
    Issue,
    analyze_results,
    compute_health_score,
    generate_pdf_report,
    group_issues_by_category,
    summarize_issues,
)


def _ok_row(**kwargs) -> dict:
    base = {
        "url": "https://example.com",
        "status": "ok",
        "title": "Example Page Title That Is Long Enough",
        "title_len": 40,
        "meta_description": "This is a sufficiently long meta description for testing purposes of the analysis engine.",
        "meta_desc_len": 85,
        "canonical": "https://example.com",
        "robots_meta": "",
        "h1": "Example",
        "h2s": "Section 1",
        "h3s": "",
        "og_title": "Example Page Title That Is Long Enough",
        "og_description": "This is a sufficiently long meta description for testing purposes of the analysis engine.",
        "og_image": "https://example.com/img.png",
        "og_type": "website",
        "schema_types": "WebPage",
        "word_count": 300,
        "internal_links": 5,
        "external_links": 2,
        "images_missing_alt": 0,
        "html_lang": "en",
        "meta_viewport": "width=device-width",
        "meta_charset": "utf-8",
    }
    base.update(kwargs)
    return base


class TestAnalyzeResults:
    def test_empty_results(self):
        issues = analyze_results([])
        assert issues == []

    def test_no_issues(self):
        rows = [_ok_row()]
        issues = analyze_results(rows)
        assert issues == []

    def test_missing_title(self):
        rows = [_ok_row(title="", title_len=0)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "missing_title" in names

    def test_title_too_long(self):
        rows = [_ok_row(title="x" * 71, title_len=71)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "title_too_long" in names

    def test_title_too_short(self):
        rows = [_ok_row(title="Hi", title_len=2)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "title_too_short" in names

    def test_duplicate_titles(self):
        rows = [
            _ok_row(url="https://a.com", title="Same Title"),
            _ok_row(url="https://b.com", title="Same Title"),
        ]
        issues = analyze_results(rows)
        dupes = [i for i in issues if i.name == "duplicate_title"]
        assert len(dupes) == 1
        assert dupes[0].count == 2

    def test_missing_meta_description(self):
        rows = [_ok_row(meta_description="", meta_desc_len=0)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "missing_meta_description" in names

    def test_meta_description_too_long(self):
        rows = [_ok_row(meta_description="x" * 161, meta_desc_len=161)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "meta_description_too_long" in names

    def test_meta_description_too_short(self):
        rows = [_ok_row(meta_description="Short", meta_desc_len=5)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "meta_description_too_short" in names

    def test_missing_h1(self):
        rows = [_ok_row(h1="")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "missing_h1" in names

    def test_missing_h2(self):
        rows = [_ok_row(h1="Hello", h2s="")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "missing_h2" in names

    def test_noindex_page(self):
        rows = [_ok_row(robots_meta="noindex, nofollow")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "noindex_page" in names

    def test_canonical_missing(self):
        rows = [_ok_row(canonical="")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "canonical_missing" in names

    def test_canonical_not_self(self):
        rows = [_ok_row(canonical="https://other.com")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "canonical_not_self" in names

    def test_og_fields_missing(self):
        rows = [_ok_row(og_title="", og_description="", og_image="")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "og_title_missing" in names
        assert "og_description_missing" in names
        assert "og_image_missing" in names

    def test_og_incomplete(self):
        rows = [_ok_row(og_title="Title", og_description="", og_image="")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "og_incomplete" in names

    def test_images_missing_alt(self):
        rows = [_ok_row(images_missing_alt=3)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "images_missing_alt" in names

    def test_thin_content(self):
        rows = [_ok_row(word_count=100)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "thin_content" in names

    def test_empty_page(self):
        rows = [_ok_row(word_count=0)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "empty_page" in names

    def test_url_too_long(self):
        rows = [_ok_row(url="https://example.com/" + "a" * 200)]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "url_too_long" in names

    def test_url_session_id(self):
        rows = [_ok_row(url="https://example.com/?PHPSESSID=abc123")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "url_session_id" in names

    def test_no_schema(self):
        rows = [_ok_row(schema_types="")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "no_schema" in names

    def test_html_lang_missing(self):
        rows = [_ok_row(html_lang="")]
        issues = analyze_results(rows)
        names = [i.name for i in issues]
        assert "html_lang_missing" in names

    def test_viewport_missing(self):
        # viewport check only triggers if any row has viewport — empty is treated as "no data"
        rows = [_ok_row(meta_viewport="")]
        issues = analyze_results(rows)
        viewport_issues = [i for i in issues if i.name == "viewport_missing"]
        assert viewport_issues == []

    def test_error_row_ignored(self):
        rows = [{"url": "https://bad.com", "status": "error: timeout", "title": ""}]
        issues = analyze_results(rows)
        assert issues == []

    def test_multiple_issues(self):
        rows = [_ok_row(title="", meta_description="", h1="", canonical="")]
        issues = analyze_results(rows)
        names = {i.name for i in issues}
        assert "missing_title" in names
        assert "missing_meta_description" in names
        assert "missing_h1" in names
        assert "canonical_missing" in names


class TestHealthScore:
    def test_perfect_score(self):
        rows = [_ok_row()]
        issues = analyze_results(rows)
        score = compute_health_score(issues, len(rows))
        assert score == 100

    def test_errors_reduce_score(self):
        rows = [_ok_row(title="", meta_description="")]
        issues = analyze_results(rows)
        score = compute_health_score(issues, len(rows))
        assert score < 100

    def test_many_errors_low_score(self):
        rows = [_ok_row(title="", meta_description="", h1="", canonical="") for _ in range(50)]
        issues = analyze_results(rows)
        score = compute_health_score(issues, len(rows))
        assert score < 80

    def test_empty_pages(self):
        score = compute_health_score([], 0)
        assert score == 100


class TestGroupingAndSummary:
    def test_group_by_category(self):
        rows = [_ok_row(title="", meta_description="")]
        issues = analyze_results(rows)
        grouped = group_issues_by_category(issues)
        assert "titles" in grouped
        assert "meta" in grouped

    def test_summarize_issues(self):
        rows = [_ok_row(title="", meta_description="")]
        issues = analyze_results(rows)
        summary = summarize_issues(issues)
        assert summary["total"] > 0
        assert isinstance(summary["errors"], int)
        assert isinstance(summary["warnings"], int)
        assert isinstance(summary["opportunities"], int)


class TestPdfReport:
    def test_generates_pdf(self):
        rows = [_ok_row(), _ok_row(title="", meta_description="")]
        issues = analyze_results(rows)
        score = compute_health_score(issues, len(rows))
        pdf = generate_pdf_report(rows, issues, score, title="Test Report")
        assert isinstance(pdf, bytes)
        assert len(pdf) > 100
        assert pdf[:4] == b"%PDF"

    def test_pdf_with_empty_results(self):
        pdf = generate_pdf_report([], [], 100)
        assert isinstance(pdf, bytes)
        assert pdf[:4] == b"%PDF"


class TestIssueDataclass:
    def test_count(self):
        issue = Issue("titles", "error", "missing_title", ["a", "b", "c"])
        assert issue.count == 3

    def test_how_to_fix(self):
        issue = Issue("titles", "error", "missing_title", ["a"])
        assert "title" in issue.how_to_fix.lower()

    def test_empty_how_to_fix(self):
        issue = Issue("test", "warning", "unknown_issue_name", ["a"])
        assert issue.how_to_fix == "Review this issue and fix as needed."
