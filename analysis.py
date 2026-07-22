"""SEO analysis engine -- post-crawl issue detection, health score, and PDF report."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CATEGORY_ORDER = [
    "titles", "meta", "headings", "indexability", "open_graph",
    "twitter_cards", "images", "schema", "technical", "urls", "content",
    "hreflang", "canonical", "links",
]

HOW_TO_FIX: dict[str, str] = {
    "missing_title": "Add a unique, descriptive <title> tag (30-60 characters) to every page.",
    "title_too_long": "Keep titles under 60 characters to avoid truncation in search results.",
    "title_too_short": "Titles under 30 characters may underperform. Add more descriptive text.",
    "duplicate_title": "Each page should have a unique title that describes its specific content.",
    "missing_meta_description": "Add a unique meta description (120-155 characters) summarising the page.",
    "meta_description_too_long": "Keep meta descriptions under 155 characters to avoid truncation.",
    "meta_description_too_short": "Meta descriptions under 70 characters may underperform. Add more detail.",
    "duplicate_meta_description": "Each page should have a unique meta description.",
    "missing_h1": "Every page needs exactly one H1 tag describing the main topic.",
    "missing_h2": "Add H2 subheadings to break up content and improve scannability.",
    "multiple_h1": "Use only one H1 per page. Move additional headings to H2 level.",
    "h1_equals_title": "H1 and title are identical -- consider varying them for better SERP context.",
    "noindex_page": "Page is set to noindex -- verify this is intentional.",
    "canonical_missing": "Add a canonical tag to indicate the preferred URL for this page.",
    "canonical_not_self": "Canonical points to a different URL. Ensure this is intentional.",
    "og_title_missing": "Add an og:title meta tag for better social media sharing.",
    "og_description_missing": "Add an og:description meta tag for better social media sharing.",
    "og_image_missing": "Add an og:image meta tag -- social previews without images look poor.",
    "og_type_missing": "Add an og:type meta tag (e.g. article, website, product).",
    "og_incomplete": "Complete all OG tags (title, description, image, type) for optimal social sharing.",
    "og_mismatch_title": "og:title differs from page title -- consider keeping them consistent.",
    "twitter_missing": "Add a twitter:card meta tag for Twitter/X sharing previews.",
    "twitter_incomplete": "Add twitter:title, twitter:image, and twitter:site for full Twitter card support.",
    "images_missing_alt": "Add descriptive alt text to images for accessibility and SEO.",
    "images_not_lazy": "Consider adding loading='lazy' to off-screen images to improve page speed.",
    "no_schema": "Add structured data (JSON-LD) to help search engines understand your content.",
    "invalid_jsonld": "Fix the JSON-LD syntax error -- search engines cannot parse invalid markup.",
    "viewport_missing": "Add <meta name='viewport' content='width=device-width, initial-scale=1'> for mobile.",
    "html_lang_missing": "Add lang attribute to <html> tag (e.g. <html lang='en'>).",
    "charset_missing": "Add <meta charset='utf-8'> to declare character encoding.",
    "thin_content": "Content is thin (< 200 words). Add substantive, useful information.",
    "empty_page": "Page has no visible text content. Ensure the page loaded correctly.",
    "url_too_long": "Shorten URLs to under 115 characters for better readability.",
    "url_has_underscores": "Use hyphens instead of underscores in URL paths (Google treats underscores as word-joiners).",
    "url_uppercase": "Use lowercase in URLs to avoid case-sensitivity issues.",
    "url_non_ascii": "Avoid non-ASCII characters in URLs -- use percent-encoding or transliterate.",
    "url_query_params": "URLs with query parameters may be crawled less frequently. Consider clean URLs.",
    "url_session_id": "Remove session IDs from URLs -- they cause duplicate content issues.",
    "orphan_page": "This page has zero internal inlinks. Add links from other pages to it.",
    "hreflang_invalid_code": "Fix invalid hreflang language codes -- use valid ISO 639-1 codes.",
    "hreflang_missing_x_default": "Add an hreflang x-default tag for the fallback language version.",
    "hreflang_mismatch": "Ensure all hreflang entries reference the same set of languages across linked pages.",
    "broken_links_found": "Fix broken links (4xx/5xx) pointing from your pages to improve user experience.",
    "canonical_chain_too_long": "Shorten canonical redirect chains to avoid SEO dilution.",
}


@dataclass
class Issue:
    category: str
    severity: str  # "error" | "warning" | "opportunity"
    name: str
    urls: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.urls)

    @property
    def how_to_fix(self) -> str:
        return HOW_TO_FIX.get(self.name, "Review this issue and fix as needed.")


def _url(rows: list[dict], key: str, value: str) -> list[str]:
    return [r.get("url", "") for r in rows if r.get(key) == value and r.get("status") == "ok"]


def _missing(rows: list[dict], key: str) -> list[str]:
    return [r.get("url", "") for r in rows if not r.get(key) and r.get("status") == "ok"]


def _empty(rows: list[dict], key: str) -> list[str]:
    return [r.get("url", "") for r in rows if r.get(key, "") == "" and r.get("status") == "ok"]


def _gt(rows: list[dict], key: str, threshold: int) -> list[str]:
    return [
        r.get("url", "") for r in rows
        if isinstance(r.get(key), (int, float)) and r[key] > threshold
        and r.get("status") == "ok"
    ]


def _lt(rows: list[dict], key: str, threshold: int) -> list[str]:
    return [
        r.get("url", "") for r in rows
        if isinstance(r.get(key), (int, float)) and r[key] < threshold
        and r.get("status") == "ok"
    ]


def _group_by(rows: list[dict], key: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for r in rows:
        val = r.get(key, "")
        if val and r.get("status") == "ok":
            groups.setdefault(val, []).append(r.get("url", ""))
    return groups


def _ok_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("status") == "ok"]


def analyze_results(results: list[dict]) -> list[Issue]:
    """Run all Tier 1 analyses on a list of SEO result rows.

    Each row is a dict with keys like title, meta_description, h1, status, etc.
    Returns a list of Issue objects, sorted by category then severity.
    """
    issues: list[Issue] = []
    ok = _ok_rows(results)
    if not ok:
        return issues

    # ── Title issues ──
    urls = _missing(ok, "title")
    if urls:
        issues.append(Issue("titles", "error", "missing_title", urls))

    dupes = _group_by(ok, "title")
    for title, urls in dupes.items():
        if len(urls) > 1:
            issues.append(Issue("titles", "warning", "duplicate_title", urls))

    urls = _gt(ok, "title_len", 70)
    if urls:
        issues.append(Issue("titles", "error", "title_too_long", urls))
    else:
        urls = _gt(ok, "title_len", 60)
        if urls:
            issues.append(Issue("titles", "warning", "title_too_long", urls))

    urls = _lt(ok, "title_len", 30)
    if urls:
        issues.append(Issue("titles", "warning", "title_too_short", urls))

    # ── Meta description issues ──
    urls = _missing(ok, "meta_description")
    if urls:
        issues.append(Issue("meta", "warning", "missing_meta_description", urls))

    dupes = _group_by(ok, "meta_description")
    for desc, urls in dupes.items():
        if len(urls) > 1:
            issues.append(Issue("meta", "warning", "duplicate_meta_description", urls))

    urls = _gt(ok, "meta_desc_len", 160)
    if urls:
        issues.append(Issue("meta", "error", "meta_description_too_long", urls))
    else:
        urls = _gt(ok, "meta_desc_len", 155)
        if urls:
            issues.append(Issue("meta", "warning", "meta_description_too_long", urls))

    urls = _lt(ok, "meta_desc_len", 70)
    if urls:
        issues.append(Issue("meta", "warning", "meta_description_too_short", urls))

    # ── Heading issues ──
    urls = _missing(ok, "h1")
    if urls:
        issues.append(Issue("headings", "error", "missing_h1", urls))

    urls_h1 = [r for r in ok if r.get("h1")]
    urls_no_h2 = [r.get("url", "") for r in urls_h1 if not r.get("h2s")]
    if urls_no_h2:
        issues.append(Issue("headings", "opportunity", "missing_h2", urls_no_h2))

    # ── Indexability ──
    urls = [r.get("url", "") for r in ok if "noindex" in str(r.get("robots_meta", "")).lower()]
    if urls:
        issues.append(Issue("indexability", "error", "noindex_page", urls))

    # ── Canonical issues ──
    urls = _empty(ok, "canonical")
    if urls:
        issues.append(Issue("canonical", "warning", "canonical_missing", urls))

    urls_not_self = []
    for r in ok:
        c = r.get("canonical", "")
        url = r.get("url", "")
        if c and url and c != url:
            urls_not_self.append(url)
    if urls_not_self:
        issues.append(Issue("canonical", "opportunity", "canonical_not_self", urls_not_self))

    # ── Open Graph issues ──
    for field_name, issue_name in [
        ("og_title", "og_title_missing"),
        ("og_description", "og_description_missing"),
        ("og_image", "og_image_missing"),
    ]:
        urls = _missing(ok, field_name)
        if urls:
            issues.append(Issue("open_graph", "opportunity", issue_name, urls))

    # og_type is in extended fields
    if any(r.get("og_type") for r in ok):
        urls = _missing(ok, "og_type")
        if urls:
            issues.append(Issue("open_graph", "opportunity", "og_type_missing", urls))

    # og completeness
    og_fields = ["og_title", "og_description", "og_image"]
    incomplete = [
        r.get("url", "") for r in ok
        if sum(1 for f in og_fields if r.get(f)) < len(og_fields)
    ]
    if incomplete:
        issues.append(Issue("open_graph", "opportunity", "og_incomplete", incomplete))

    # og mismatch
    mismatch = [
        r.get("url", "") for r in ok
        if r.get("og_title") and r.get("title") and r["og_title"] != r["title"]
    ]
    if mismatch:
        issues.append(Issue("open_graph", "opportunity", "og_mismatch_title", mismatch))

    # ── Twitter Card issues ──
    if any(r.get("twitter_card") for r in ok):
        urls = _missing(ok, "twitter_card")
        if urls:
            issues.append(Issue("twitter_cards", "opportunity", "twitter_missing", urls))

        tw_fields = ["twitter_title", "twitter_image", "twitter_site"]
        incomplete = [
            r.get("url", "") for r in ok
            if r.get("twitter_card") and not all(r.get(f) for f in tw_fields)
        ]
        if incomplete:
            issues.append(Issue("twitter_cards", "opportunity", "twitter_incomplete", incomplete))

    # ── Image issues ──
    urls = [
        r.get("url", "") for r in ok
        if isinstance(r.get("images_missing_alt"), int) and r["images_missing_alt"] > 0
    ]
    if urls:
        issues.append(Issue("images", "warning", "images_missing_alt", urls))

    urls = [
        r.get("url", "") for r in ok
        if isinstance(r.get("images_no_lazy"), int) and r["images_no_lazy"] > 5
    ]
    if urls:
        issues.append(Issue("images", "opportunity", "images_not_lazy", urls))

    # ── Schema issues ──
    urls = _empty(ok, "schema_types")
    if urls:
        issues.append(Issue("schema", "opportunity", "no_schema", urls))

    # JSON-LD parse check
    invalid = []
    for r in ok:
        jld = r.get("jsonld_full", "")
        if not jld:
            continue
        for part in jld.split("\n---\n"):
            try:
                json.loads(part)
            except (json.JSONDecodeError, ValueError):
                invalid.append(r.get("url", ""))
                break
    if invalid:
        issues.append(Issue("schema", "error", "invalid_jsonld", invalid))

    # ── Technical issues ──
    if any(r.get("meta_viewport") for r in ok):
        urls = _empty(ok, "meta_viewport")
        if urls:
            issues.append(Issue("technical", "warning", "viewport_missing", urls))

    urls = _empty(ok, "html_lang")
    if urls:
        issues.append(Issue("technical", "warning", "html_lang_missing", urls))

    urls = _empty(ok, "meta_charset")
    if urls:
        issues.append(Issue("technical", "opportunity", "charset_missing", urls))

    urls = [
        r.get("url", "") for r in ok
        if isinstance(r.get("iframe_count"), int) and r["iframe_count"] > 3
    ]
    if urls:
        issues.append(Issue("technical", "opportunity", "iframe_count_high", urls))

    # ── URL hygiene ──
    urls = [r.get("url", "") for r in ok if len(r.get("url", "")) > 200]
    if urls:
        issues.append(Issue("urls", "error", "url_too_long", urls))
    else:
        urls = [r.get("url", "") for r in ok if len(r.get("url", "")) > 115]
        if urls:
            issues.append(Issue("urls", "warning", "url_too_long", urls))

    urls = [r.get("url", "") for r in ok if "_" in r.get("url", "").split("?")[0].split("#")[0]]
    if urls:
        issues.append(Issue("urls", "opportunity", "url_has_underscores", urls))

    urls = [
        r.get("url", "") for r in ok
        if any(c.isupper() for c in r.get("url", "").split("//", 1)[-1])
    ]
    if urls:
        issues.append(Issue("urls", "opportunity", "url_uppercase", urls))

    urls = [
        r.get("url", "") for r in ok
        if any(ord(c) > 127 for c in r.get("url", ""))
    ]
    if urls:
        issues.append(Issue("urls", "warning", "url_non_ascii", urls))

    urls = [r.get("url", "") for r in ok if "?" in r.get("url", "")]
    if urls:
        issues.append(Issue("urls", "opportunity", "url_query_params", urls))

    session_pattern = re.compile(r"[?&](PHPSESSID|jsessionid|sid)=", re.IGNORECASE)
    urls = [r.get("url", "") for r in ok if session_pattern.search(r.get("url", ""))]
    if urls:
        issues.append(Issue("urls", "warning", "url_session_id", urls))

    # ── Content issues ──
    urls = [
        r.get("url", "") for r in ok
        if isinstance(r.get("word_count"), int) and r["word_count"] == 0
    ]
    if urls:
        issues.append(Issue("content", "error", "empty_page", urls))

    urls = [
        r.get("url", "") for r in ok
        if isinstance(r.get("word_count"), int) and 0 < r["word_count"] < 200
    ]
    if urls:
        issues.append(Issue("content", "warning", "thin_content", urls))

    # ── Hreflang issues ──
    if any(r.get("hreflang") for r in ok):
        # x-default check
        urls = [
            r.get("url", "") for r in ok
            if r.get("hreflang") and "x-default" not in str(r["hreflang"])
        ]
        if urls:
            issues.append(Issue("hreflang", "opportunity", "hreflang_missing_x_default", urls))

        # invalid codes
        valid_langs = {
            "en", "fr", "de", "es", "it", "pt", "nl", "ru", "zh", "ja", "ko", "ar",
            "hi", "th", "vi", "tr", "pl", "cs", "sk", "hu", "ro", "bg", "hr", "sl",
            "et", "lv", "lt", "fi", "sv", "da", "no", "nb", "nn", "is", "ga", "mt",
            "eu", "ca", "gl", "af", "sw", "id", "ms", "tl", "bn", "ta", "te", "ml",
            "kn", "gu", "pa", "ur", "fa", "he", "el", "uk", "mk", "sq", "sr", "bs",
            "x-default",
        }
        invalid_urls = []
        for r in ok:
            hl = r.get("hreflang", "")
            if not hl:
                continue
            for entry in str(hl).split("|"):
                code = entry.strip().split(":")[0].strip().lower()
                if code and code not in valid_langs and not re.match(r"^[a-z]{2}-[a-z]{2}$", code):
                    invalid_urls.append(r.get("url", ""))
                    break
        if invalid_urls:
            issues.append(Issue("hreflang", "warning", "hreflang_invalid_code", invalid_urls))

        # hreflang consistency: build language sets per URL and flag mismatches
        hreflang_sets: dict[str, set[str]] = {}
        for r in ok:
            hl = r.get("hreflang", "")
            if not hl:
                continue
            langs = set()
            for entry in str(hl).split("|"):
                code = entry.strip().split(":")[0].strip().lower()
                if code:
                    langs.add(code)
            if langs:
                hreflang_sets[r.get("url", "")] = langs
        if hreflang_sets:
            ref_set = next(iter(hreflang_sets.values()))
            mismatched = [url for url, langs in hreflang_sets.items() if langs != ref_set]
            if mismatched and len(mismatched) > 1:
                issues.append(Issue("hreflang", "warning", "hreflang_mismatch", mismatched))

    # ── Links ──
    urls = [
        r.get("url", "") for r in ok
        if isinstance(r.get("internal_links"), int) and r["internal_links"] == 0
    ]
    if urls:
        issues.append(Issue("links", "opportunity", "orphan_page", urls))

    # Broken links (populated during crawl via _analyze_broken_links)
    broken = [r for r in ok if r.get("broken_links")]
    if broken:
        urls_broken = []
        for r in broken:
            for bl in r.get("broken_links", []):
                urls_broken.append(f"{r.get('url', '')} -> {bl.get('target_url', '')} ({bl.get('status_code', '?')})")
        if urls_broken:
            issues.append(Issue("links", "warning", "broken_links_found", urls_broken))

    # Canonical chain length check
    long_chains = [
        r.get("url", "") for r in ok
        if r.get("canonical_chain") and len(str(r["canonical_chain"]).split(" -> ")) > 2
    ]
    if long_chains:
        issues.append(Issue("canonical", "warning", "canonical_chain_too_long", long_chains))

    # Sort: errors first, then warnings, then opportunities
    severity_order = {"error": 0, "warning": 1, "opportunity": 2}
    cat_order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    issues.sort(key=lambda i: (cat_order.get(i.category, 99), severity_order.get(i.severity, 9)))

    return issues


def compute_health_score(issues: list[Issue], total_pages: int) -> int:
    """Compute Ahrefs-style 0-100 health score.

    Each error costs 1 point per page affected (capped at total_pages).
    Each warning costs 0.5 points per page affected.
    Each opportunity costs 0.2 points per page affected.
    Score = max(0, 100 - total_deductions).
    """
    if total_pages <= 0:
        return 100

    deductions = 0.0
    for issue in issues:
        if issue.severity == "error":
            deductions += issue.count * 1.0
        elif issue.severity == "warning":
            deductions += issue.count * 0.5
        elif issue.severity == "opportunity":
            deductions += issue.count * 0.2

    # Normalize: worst case = every page has every error
    max_possible = total_pages * 10  # rough upper bound
    normalized = min(deductions / max_possible, 1.0) if max_possible > 0 else 0
    score = max(0, int(100 - normalized * 100))
    return score


def group_issues_by_category(issues: list[Issue]) -> dict[str, list[Issue]]:
    """Group issues by category, preserving category order."""
    groups: dict[str, list[Issue]] = {}
    for issue in issues:
        groups.setdefault(issue.category, []).append(issue)
    # Reorder to match CATEGORY_ORDER
    return {k: groups[k] for k in CATEGORY_ORDER if k in groups}


def summarize_issues(issues: list[Issue]) -> dict[str, Any]:
    """Return summary counts: total issues, per severity, per category."""
    counts = {"error": 0, "warning": 0, "opportunity": 0}
    for issue in issues:
        counts[issue.severity] += issue.count

    by_cat: dict[str, dict[str, int]] = {}
    for issue in issues:
        cat = issue.category
        by_cat.setdefault(cat, {"error": 0, "warning": 0, "opportunity": 0})
        by_cat[cat][issue.severity] += issue.count

    return {
        "total": counts["error"] + counts["warning"] + counts["opportunity"],
        "errors": counts["error"],
        "warnings": counts["warning"],
        "opportunities": counts["opportunity"],
        "by_category": by_cat,
    }


# ── PDF Report ──

def generate_pdf_report(
    results: list[dict],
    issues: list[Issue],
    health_score: int,
    output_dir: str = "",
    title: str = "SEO Audit Report",
) -> bytes:
    """Generate a PDF report using fpdf2."""
    from fpdf import FPDF

    ok = _ok_rows(results)
    total = len(results)
    ok_count = len(ok)
    summary = summarize_issues(issues)
    categories = group_issues_by_category(issues)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Cover page ──
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 28)
    pdf.cell(0, 20, title, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", "", 12)
    gen_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf.cell(
        0, 8, f"Generated: {gen_date}",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    if output_dir:
        pdf.cell(
            0, 8, f"Output: {output_dir}",
            new_x="LMARGIN", new_y="NEXT", align="C",
        )
    pdf.ln(20)

    # Health score
    if health_score >= 80:
        score_color = (40, 180, 99)
    elif health_score >= 50:
        score_color = (241, 196, 15)
    else:
        score_color = (231, 76, 60)
    pdf.set_fill_color(*score_color)
    pdf.rect(60, 90, 90, 40, "F")
    pdf.set_font("Helvetica", "B", 36)
    pdf.set_text_color(255, 255, 255)
    pdf.text(60, 115, str(health_score))
    pdf.set_font("Helvetica", "", 12)
    pdf.text(85, 115, "/ 100")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(55)
    pdf.set_font("Helvetica", "B", 14)
    label = "Good" if health_score >= 80 else "Needs Work" if health_score >= 50 else "Poor"
    pdf.cell(
        0, 10, f"Health Score: {label}",
        new_x="LMARGIN", new_y="NEXT", align="C",
    )
    pdf.ln(10)

    # Metrics row
    pdf.set_font("Helvetica", "", 11)
    col_w = 45
    x_start = (210 - col_w * 4) / 2
    pdf.set_x(x_start)
    metrics = [
        ("Total URLs", str(total)), ("OK", str(ok_count)),
        ("Errors", str(summary["errors"])),
        ("Warnings", str(summary["warnings"])),
    ]
    for label, value in metrics:
        pdf.cell(col_w, 8, f"{label}: {value}", align="C")
    pdf.ln(12)

    # ── Issues summary page ──
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Issues by Category", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Header
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(60, 8, "Category", border=1, fill=True)
    pdf.cell(30, 8, "Errors", border=1, fill=True, align="C")
    pdf.cell(30, 8, "Warnings", border=1, fill=True, align="C")
    pdf.cell(30, 8, "Opportunities", border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 10)
    for cat, cat_issues in categories.items():
        e = sum(i.count for i in cat_issues if i.severity == "error")
        w = sum(i.count for i in cat_issues if i.severity == "warning")
        o = sum(i.count for i in cat_issues if i.severity == "opportunity")
        if e + w + o == 0:
            continue
        pdf.cell(60, 7, cat.replace("_", " ").title(), border=1)
        pdf.cell(30, 7, str(e), border=1, align="C")
        pdf.cell(30, 7, str(w), border=1, align="C")
        pdf.cell(30, 7, str(o), border=1, align="C")
        pdf.ln()

    # ── Issue details pages ──
    for cat, cat_issues in categories.items():
        for issue in cat_issues:
            if issue.count == 0:
                continue
            if pdf.get_y() > 240:
                pdf.add_page()

            sev_label = {
                "error": "ERROR", "warning": "WARNING", "opportunity": "OPPORTUNITY"
            }[issue.severity]
            if issue.severity == "error":
                sev_color = (231, 76, 60)
            elif issue.severity == "warning":
                sev_color = (241, 196, 15)
            else:
                sev_color = (52, 152, 219)

            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(*sev_color)
            issue_title = issue.name.replace("_", " ").title()
            pdf.cell(
                0, 8,
                f"[{sev_label}] {issue_title} ({issue.count})",
                new_x="LMARGIN", new_y="NEXT",
            )
            pdf.set_text_color(100, 100, 100)
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 6, issue.how_to_fix, new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)

            pdf.set_font("Helvetica", "", 9)
            for u in issue.urls[:10]:
                pdf.cell(5, 5, "")
                pdf.cell(0, 5, u[:90], new_x="LMARGIN", new_y="NEXT")
            if issue.count > 10:
                pdf.cell(5, 5, "")
                pdf.set_font("Helvetica", "I", 9)
                pdf.cell(0, 5, f"... and {issue.count - 10} more", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)
            pdf.ln(3)

    # ── Footer pages: title length / meta desc / word count distributions ──
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Title Length Distribution", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    title_lens = [r.get("title_len", 0) for r in ok if isinstance(r.get("title_len"), int)]
    if title_lens:
        buckets = {"0 (missing)": 0, "1-29": 0, "30-60": 0, "61-70": 0, "70+": 0}
        for tl in title_lens:
            if tl == 0:
                buckets["0 (missing)"] += 1
            elif tl < 30:
                buckets["1-29"] += 1
            elif tl <= 60:
                buckets["30-60"] += 1
            elif tl <= 70:
                buckets["61-70"] += 1
            else:
                buckets["70+"] += 1

        pdf.set_font("Helvetica", "", 10)
        max_val = max(buckets.values()) if buckets.values() else 1
        for label, count in buckets.items():
            bar_width = int((count / max_val) * 120) if max_val > 0 else 0
            pdf.cell(25, 7, label, align="R")
            pdf.cell(5, 7, "")
            pdf.set_fill_color(52, 152, 219)
            pdf.cell(bar_width, 7, "", fill=True)
            pdf.cell(10, 7, f" {count}")
            pdf.ln()
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 8, "No title length data available.")

    # Meta description distribution
    pdf.ln(8)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Meta Description Length", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    meta_lens = [r.get("meta_desc_len", 0) for r in ok if isinstance(r.get("meta_desc_len"), int)]
    if meta_lens:
        buckets = {"0 (missing)": 0, "1-69": 0, "70-155": 0, "156-160": 0, "160+": 0}
        for ml in meta_lens:
            if ml == 0:
                buckets["0 (missing)"] += 1
            elif ml < 70:
                buckets["1-69"] += 1
            elif ml <= 155:
                buckets["70-155"] += 1
            elif ml <= 160:
                buckets["156-160"] += 1
            else:
                buckets["160+"] += 1

        pdf.set_font("Helvetica", "", 10)
        max_val = max(buckets.values()) if buckets.values() else 1
        for label, count in buckets.items():
            bar_width = int((count / max_val) * 120) if max_val > 0 else 0
            pdf.cell(25, 7, label, align="R")
            pdf.cell(5, 7, "")
            pdf.set_fill_color(46, 204, 113)
            pdf.cell(bar_width, 7, "", fill=True)
            pdf.cell(10, 7, f" {count}")
            pdf.ln()

    # Word count distribution
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Word Count Distribution", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    word_counts = [r.get("word_count", 0) for r in ok if isinstance(r.get("word_count"), int)]
    if word_counts:
        buckets = {"0 (empty)": 0, "1-199": 0, "200-499": 0, "500-999": 0, "1000+": 0}
        for wc in word_counts:
            if wc == 0:
                buckets["0 (empty)"] += 1
            elif wc < 200:
                buckets["1-199"] += 1
            elif wc < 500:
                buckets["200-499"] += 1
            elif wc < 1000:
                buckets["500-999"] += 1
            else:
                buckets["1000+"] += 1

        pdf.set_font("Helvetica", "", 10)
        max_val = max(buckets.values()) if buckets.values() else 1
        for label, count in buckets.items():
            bar_width = int((count / max_val) * 120) if max_val > 0 else 0
            pdf.cell(25, 7, label, align="R")
            pdf.cell(5, 7, "")
            pdf.set_fill_color(155, 89, 182)
            pdf.cell(bar_width, 7, "", fill=True)
            pdf.cell(10, 7, f" {count}")
            pdf.ln()

    return bytes(pdf.output())
