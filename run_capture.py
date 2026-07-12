"""CLI runner for screenshots and SEO extraction (desktop use)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path

from page_capture import PageCapture, load_config
from seleniumbase import SB

from importers import import_from_sitemap_url, import_from_sitemap_xml, import_from_csv_file, import_from_wp_xml, parse_urls_text

HERE = Path(__file__).resolve().parent
CONFIG = load_config(HERE / "config.yaml")


def slugify(url: str) -> str:
    base = re.sub(r"^https?://", "", url.lower())
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")


def _seo_js() -> str:
    return r"""
(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const metaContent = (attr, val) => {
        const el = document.querySelector(`meta[${attr}="${val}"]`);
        return el ? (el.getAttribute('content') || '') : '';
    };
    const title = document.title || '';
    const metaDesc = metaContent('name', 'description');
    const canonical = (q('link[rel="canonical"]') || {}).href || '';
    const robotsMeta = metaContent('name', 'robots');
    const h1 = (q('h1') || {innerText: ''}).innerText.trim();
    const h2s = qa('h2').map(e => e.innerText.trim()).filter(Boolean).join(' | ');
    const h3s = qa('h3').map(e => e.innerText.trim()).filter(Boolean).join(' | ');
    const ogTitle = metaContent('property', 'og:title');
    const ogDesc = metaContent('property', 'og:description');
    const ogImage = metaContent('property', 'og:image');
    const schemaTypes = qa('script[type="application/ld+json"]')
        .map(s => { try { const d = JSON.parse(s.textContent); return d['@type'] || ''; } catch(e) { return ''; } })
        .flat().filter(Boolean).join(' | ');
    const bodyText = (document.body || {innerText: ''}).innerText || '';
    const wordCount = bodyText.trim().split(/\s+/).filter(Boolean).length;
    const host = window.location.hostname;
    let internal = 0, external = 0;
    qa('a[href]').forEach(a => {
        try {
            const u = new URL(a.href, window.location.href);
            if (u.hostname === host) internal++;
            else if (u.protocol.startsWith('http')) external++;
        } catch(e) {}
    });
    const imagesMissingAlt = qa('img').filter(img => !img.getAttribute('alt')).length;
    return JSON.stringify({
        title, metaDesc, canonical, robotsMeta, h1, h2s, h3s,
        ogTitle, ogDesc, ogImage, schemaTypes, wordCount,
        internal, external, imagesMissingAlt,
    });
})()
"""


def run_screenshots(urls: list[str]) -> list[dict]:
    runtime_cfg = {
        "viewport": CONFIG.get("viewport", {"width": 1920, "height": 1080}),
        "timing": CONFIG.get("timing", {}),
        "hide": CONFIG.get("hide", {}),
        "hide_visibility": CONFIG.get("hide_visibility", {}),
    }
    results = []
    photos_dir = HERE / "photos"
    photos_dir.mkdir(exist_ok=True)

    with SB(uc=True, test=True, headless=False, window_size="1920,1080") as sb:
        page = PageCapture(sb, runtime_cfg)
        for i, url in enumerate(urls):
            print(f"[{i+1}/{len(urls)}] Capturing: {url}")
            try:
                page.open(url)
                page.scroll()
                sb.sleep(runtime_cfg["timing"].get("stabilization_ms", 2500) / 1000)
                page.hide_overlays()
                slug_name = slugify(url)
                png_path = photos_dir / f"{slug_name}.png"
                page.capture_png(png_path)
                extracted = page.extract_data()
                results.append({
                    "url": url, "status": "ok",
                    "page_name": extracted.get("page_name", ""),
                    "h1": extracted.get("h1", ""),
                    "file": str(png_path),
                })
                print(f"  -> OK: {png_path.name}")
            except Exception as exc:
                print(f"  -> FAIL: {exc}")
                results.append({"url": url, "status": f"error: {exc}"})
            time.sleep(random.uniform(
                runtime_cfg["timing"].get("inter_page_delay_min", 1.0),
                runtime_cfg["timing"].get("inter_page_delay_max", 2.0),
            ))
    return results


def run_seo(urls: list[str]) -> list[dict]:
    runtime_cfg = {
        "viewport": CONFIG.get("viewport", {"width": 1920, "height": 1080}),
        "timing": CONFIG.get("timing", {}),
        "hide": CONFIG.get("hide", {}),
        "hide_visibility": CONFIG.get("hide_visibility", {}),
    }
    results = []

    with SB(uc=True, test=True, headless=False, window_size="1920,1080") as sb:
        page = PageCapture(sb, runtime_cfg)
        for i, url in enumerate(urls):
            print(f"[{i+1}/{len(urls)}] Extracting SEO: {url}")
            try:
                page.open(url)
                sb.sleep(runtime_cfg["timing"].get("stabilization_ms", 2500) / 1000)
                raw = sb.cdp.evaluate(_seo_js())
                payload = json.loads(raw or "{}")
                results.append({
                    "url": url, "status": "ok",
                    "title": payload.get("title", ""),
                    "title_len": len(payload.get("title", "")),
                    "meta_description": payload.get("metaDesc", ""),
                    "meta_desc_len": len(payload.get("metaDesc", "")),
                    "canonical": payload.get("canonical", ""),
                    "robots_meta": payload.get("robotsMeta", ""),
                    "h1": payload.get("h1", ""),
                    "h2s": payload.get("h2s", ""),
                    "h3s": payload.get("h3s", ""),
                    "og_title": payload.get("ogTitle", ""),
                    "og_description": payload.get("ogDesc", ""),
                    "og_image": payload.get("ogImage", ""),
                    "schema_types": payload.get("schemaTypes", ""),
                    "word_count": payload.get("wordCount", 0),
                    "internal_links": payload.get("internal", 0),
                    "external_links": payload.get("external", 0),
                    "images_missing_alt": payload.get("imagesMissingAlt", 0),
                })
                print(f"  -> OK")
            except Exception as exc:
                print(f"  -> FAIL: {exc}")
                results.append({"url": url, "status": f"error: {exc}"})
            time.sleep(random.uniform(
                runtime_cfg["timing"].get("inter_page_delay_min", 1.0),
                runtime_cfg["timing"].get("inter_page_delay_max", 2.0),
            ))
    return results


def main():
    parser = argparse.ArgumentParser(description="Page Capture CLI")
    parser.add_argument("--kind", choices=["screenshot", "seo"], default="screenshot")
    parser.add_argument("urls", nargs="*", help="URL(s) to process")
    parser.add_argument("--sitemap-url", help="Fetch URLs from a sitemap URL")
    parser.add_argument("--sitemap-file", help="Read sitemap XML from file")
    parser.add_argument("--csv", help="Read URL pairs from CSV file (uses first column)")
    parser.add_argument("--wp-xml", help="Read URLs from WordPress XML export file")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: auto-generated)")
    args = parser.parse_args()

    urls: list[str] = []

    if args.urls:
        urls = [u for u in args.urls if u.strip()]

    if args.sitemap_url:
        print(f"Fetching sitemap: {args.sitemap_url}")
        fetched = import_from_sitemap_url(args.sitemap_url)
        urls.extend(fetched)
        print(f"  Found {len(fetched)} URLs")

    if args.sitemap_file:
        raw = Path(args.sitemap_file).read_text(encoding="utf-8")
        parsed = import_from_sitemap_xml(raw)
        urls.extend(parsed)
        print(f"  Parsed {len(parsed)} URLs from sitemap")

    if args.csv:
        raw = Path(args.csv).read_bytes()
        pairs = import_from_csv_file(raw)
        csv_urls = [a for a, _ in pairs]
        urls.extend(csv_urls)
        print(f"  Found {len(csv_urls)} URLs from CSV")

    if args.wp_xml:
        raw = Path(args.wp_xml).read_bytes()
        posts = import_from_wp_xml(raw)
        wp_urls = [p["url"] for p in posts]
        urls.extend(wp_urls)
        print(f"  Found {len(wp_urls)} URLs from WordPress export")

    urls = list(dict.fromkeys(urls))  # deduplicate preserving order
    urls = [u for u in urls if u.strip()]

    if not urls:
        urls_env = os.environ.get("URLS", "")
        if urls_env:
            urls = parse_urls_text(urls_env)

    if not urls:
        print("No URLs provided. Pass URLs as arguments or use --sitemap-url, --csv, --wp-xml, or set URLS env var.")
        sys.exit(1)

    kind = args.kind
    print(f"Kind: {kind}, URLs: {len(urls)}")

    if args.output_dir:
        output_dir = HERE / args.output_dir
    else:
        output_dir = HERE / ("output" if len(urls) < 100 else f"output_{len(urls)}urls")

    output_dir.mkdir(exist_ok=True)

    if kind == "seo":
        results = run_seo(urls)
        csv_path = output_dir / "seo_results.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            if results:
                w = csv.DictWriter(f, fieldnames=results[0].keys())
                w.writeheader()
                w.writerows(results)
        print(f"SEO results written to {csv_path}")
    else:
        results = run_screenshots(urls)
        csv_path = output_dir / "capture_results.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            if results:
                w = csv.DictWriter(f, fieldnames=results[0].keys())
                w.writeheader()
                w.writerows(results)
        print(f"Screenshot results written to {csv_path}")

    print("Done.")


if __name__ == "__main__":
    main()
