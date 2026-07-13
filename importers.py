"""Import URLs from sitemaps, CSV/WP XML files, or manual input."""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests

__all__ = [
    "import_from_sitemap_url",
    "import_from_sitemap_xml",
    "import_from_csv_file",
    "import_from_wp_xml",
    "parse_urls_text",
    "is_valid_url",
]


def is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme in ("http", "https") and parsed.netloc)


def parse_urls_text(raw: str) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for token in re.split(r"[,\s]+", line):
            token = token.strip()
            if not token or token.startswith("#"):
                continue
            if token not in seen:
                seen.add(token)
                cleaned.append(token)
    return cleaned


def import_from_sitemap_url(url: str) -> list[str]:
    resp = requests.get(url, timeout=60, headers={"User-Agent": "page-capture/1.0"})
    resp.raise_for_status()
    return _parse_sitemap_xml(resp.text)


def import_from_sitemap_xml(raw: str) -> list[str]:
    return _parse_sitemap_xml(raw)


def _parse_sitemap_xml(raw: str) -> list[str]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"Invalid XML: {e}") from e
    ns_match = re.match(r"\{(.+?)\}", root.tag)
    ns = ns_match.group(1) if ns_match else ""

    def tag(name):
        return f"{{{ns}}}{name}" if ns else name

    urls = []
    for loc in root.iter(tag("loc")):
        if loc.text:
            u = loc.text.strip()
            if is_valid_url(u):
                urls.append(u)

    if not urls:
        raise ValueError("No <loc> elements found in sitemap XML")

    return urls


def import_from_csv_file(content: str | bytes) -> list[tuple[str, str | None]]:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    import csv as csv_module

    reader = csv_module.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return []

    pairs: list[tuple[str, str | None]] = []

    for row in rows:
        if not row:
            continue
        a = (row[0] or "").strip().strip('"')
        if not is_valid_url(a):
            continue
        b = (row[1] or "").strip().strip('"') if len(row) > 1 else ""
        if b and is_valid_url(b):
            pairs.append((a, b))
        else:
            pairs.append((a, None))

    return pairs


def import_from_wp_xml(content: str | bytes) -> list[dict]:
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    root = ET.fromstring(content)

    ns_map = {
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
        "wp": "http://wordpress.org/export/1.2/",
    }

    def text(el, tag):
        found = el.find(tag, ns_map)
        return found.text.strip() if found is not None and found.text else ""

    def text_ns(el, ns_prefix, local_tag):
        ns_url = ns_map.get(ns_prefix, "")
        found = el.find(f"{{{ns_url}}}{local_tag}")
        return found.text.strip() if found is not None and found.text else ""

    def strip_html(html):
        return re.sub(r"<[^>]+>", "", html).strip()

    posts = []
    for item in root.iter("item"):
        title = text(item, "title")
        link = text(item, "link")
        if not link or not is_valid_url(link):
            continue

        post_date = text_ns(item, "wp", "post_date")
        date_part = post_date.split(" ")[0] if post_date else ""

        content_enc = text_ns(item, "content", "encoded")
        excerpt = strip_html(text_ns(item, "wp", "excerpt_encoded"))
        h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", content_enc, re.IGNORECASE | re.DOTALL)
        h1 = strip_html(h1_match.group(1)) if h1_match else title

        categories = [
            c.text.strip()
            for c in item.findall("category")
            if c.text and c.get("domain") == "category"
        ]
        tags = [
            c.text.strip()
            for c in item.findall("category")
            if c.text and c.get("domain") == "post_tag"
        ]

        posts.append({
            "title": title,
            "url": link,
            "date": date_part,
            "description": excerpt,
            "h1": h1,
            "category": ", ".join(categories),
            "tags": ", ".join(tags),
            "author": text_ns(item, "dc", "creator"),
            "content": strip_html(content_enc),
        })

    if not posts:
        raise ValueError("No posts/pages found in WordPress XML export")

    return posts
