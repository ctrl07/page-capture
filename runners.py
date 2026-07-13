from __future__ import annotations

import csv
import io
import json
import random
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import img2pdf
from PIL import Image
from seleniumbase import SB

from extraction import (
    build_seo_js,
    extract_from_page,
    get_standard_seo_fields,
    parse_seo_fields,
)
from importers import is_valid_url
from page_capture import PageCapture

HERE = Path(__file__).resolve().parent
HISTORY_FILE = HERE / ".run_history.json"


def slugify(url: str) -> str:
    base = re.sub(r"^https?://", "", url.lower())
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")


def parse_seo_payload(raw: str, seo_fields: list[dict] | None = None) -> dict:
    """Parse raw JSON from SEO JS into a flat dict.

    When seo_fields is None, falls back to legacy hardcoded field mapping
    for backwards compatibility with existing _seo_js() callers.
    """
    if seo_fields is not None:
        return parse_seo_fields(raw, seo_fields)
    # Legacy fallback — matches original _seo_js() output exactly
    payload = json.loads(raw or "{}")
    return {
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
    }


def write_results_csv(results: list[dict], csv_path: Path) -> None:
    """Write a list of result dicts to a CSV file."""
    if not results:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    all_keys = list(dict.fromkeys(k for row in results for k in row))
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)


def build_runtime_config(CONFIG: dict, viewport: dict, stabilization_ms: int) -> dict:
    """Build the runtime config dict from global CONFIG and per-run overrides."""
    return {
        "viewport": viewport,
        "timing": {**CONFIG["timing"], "stabilization_ms": stabilization_ms},
        "hide": CONFIG.get("hide", {}),
        "hide_visibility": CONFIG.get("hide_visibility", {}),
    }


def _compute_internal_inlinks(results: list[dict]) -> None:
    """Compute internal_inlinks for each row based on outlink counts from all pages.

    Since we only have outlink *counts* (not individual URLs), we estimate
    inlinks as the total outlinks from pages whose internal_links > 0,
    distributed proportionally. This is approximate — a full link graph
    would require collecting individual outlink URLs.
    """
    # For now, set internal_inlinks = 0 for all pages
    # A future enhancement can collect individual outlink URLs during crawl
    for row in results:
        if row.get("status") == "ok":
            row["internal_inlinks"] = row.get("internal_inlinks", 0)


def _seo_js() -> str:
    return r"""
(() => {
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const metaContent = (attr, val) => {
        const el = document.querySelector(`meta[${attr}="${val}"]`);
        return el ? (el.getAttribute('content') || '') : '';
    };
    const _contentArea = (() => {
        for (const sel of [
            'main', 'article', '[role="main"]', '[role="article"]',
            '.content', '.main-content', '.post-content', '.entry-content',
            '.article-content', '.page-content', '.site-content',
            '#content', '#main-content', '#main', '#mainContent',
        ]) {
            const el = document.querySelector(sel);
            if (el && el.querySelectorAll('h2, h3').length > 0) return el;
        }
        return null;
    })();
    const _headings = (tag, max) => {
        const scope = _contentArea || document;
        const seen = new Set();
        const out = [];
        for (const el of scope.querySelectorAll(tag)) {
            const t = el.innerText.trim().replace(/\s+/g, ' ');
            if (t && !seen.has(t)) { seen.add(t); out.push(t); }
            if (out.length >= max) break;
        }
        return out.join(' | ');
    };
    const title = document.title || '';
    const metaDesc = metaContent('name', 'description');
    const canonical = (q('link[rel="canonical"]') || {}).href || '';
    const robotsMeta = metaContent('name', 'robots');
    const h1 = ((_contentArea || document).querySelector('h1') || {innerText: ''}).innerText.trim();
    const h2s = _headings('h2', 15);
    const h3s = _headings('h3', 15);
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
    const imagesMissingAlt = qa('img').filter(_i => !_i.getAttribute('alt')).length;
    return JSON.stringify({
        title, metaDesc, canonical, robotsMeta, h1, h2s, h3s,
        ogTitle, ogDesc, ogImage, schemaTypes, wordCount,
        internal, external, imagesMissingAlt,
    });
})()
"""


def build_zip(results: list[dict], output_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            for key in ("file", "pdf"):
                p = Path(r.get(key, ""))
                if p.exists() and p.is_file():
                    zf.write(p, arcname=p.name)
    return buf.getvalue()


_PDF_DPI = 150


def png_to_pdf(png_path: Path, pdf_path: Path) -> None:
    """Convert a PNG to a single-page PDF using img2pdf with correct DPI."""
    dpi = _PDF_DPI
    with Image.open(png_path) as im:
        raw_dpi = im.info.get("dpi")
        if raw_dpi and raw_dpi[0] > 0 and raw_dpi[1] > 0:
            dpi = (int(raw_dpi[0]), int(raw_dpi[1]))
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = img2pdf.convert(str(png_path), dpi=dpi)
    if pdf_bytes:
        with open(pdf_path, "wb") as f:
            f.write(pdf_bytes)


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(entry: dict) -> None:
    history = load_history()
    history.insert(0, entry)
    if len(history) > 50:
        history = history[:50]
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def delete_history_entry(index: int) -> None:
    history = load_history()
    if 0 <= index < len(history):
        history.pop(index)
        with HISTORY_FILE.open("w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)


class CaptureRunner:
    def __init__(self, urls: list[str], runtime_cfg: dict, output_dir: Path, kind: str = "screenshot", generate_pdf: bool = False, seo_fields: list[dict] | None = None):
        self.urls = urls
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
        self.kind = kind
        self.generate_pdf = generate_pdf
        self.seo_fields = seo_fields
        self.results = []
        self.cancelled = False
        self._thread = None

    def run(self):
        self.results = []
        kind = self.kind
        output_dir = self.output_dir
        urls = self.urls
        runtime_cfg = self.runtime_cfg
        photos_dir = output_dir / "photos"
        photos_dir.mkdir(parents=True, exist_ok=True)
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        results = self.results

        with SB(uc=True, test=True, headless=False, window_size=f"{runtime_cfg['viewport']['width']},{runtime_cfg['viewport']['height']}") as sb:
            page = PageCapture(sb, runtime_cfg)
            for i, url in enumerate(urls):
                if self.cancelled:
                    break
                slug = slugify(url)
                row = {"url": url, "status": "waiting"}
                try:
                    if not is_valid_url(url):
                        row["status"] = "invalid URL"
                        results.append(row)
                        continue
                    page.open(url)
                    page.scroll()
                    sb.sleep(runtime_cfg["timing"]["stabilization_ms"] / 1000)
                    page.hide_overlays()
                    if kind == "seo":
                        fields = self.seo_fields or get_standard_seo_fields()
                        raw = sb.cdp.evaluate(build_seo_js(fields))
                        row = {"url": url, "status": "ok", **parse_seo_payload(raw, fields)}
                    else:
                        png_path = photos_dir / f"{slug}.png"
                        page.capture_png(png_path)
                        pdf_path = None
                        if self.generate_pdf:
                            pdf_dir = output_dir / "pdf"
                            pdf_dir.mkdir(parents=True, exist_ok=True)
                            pdf_path = pdf_dir / f"{slug}.pdf"
                            png_to_pdf(png_path, pdf_path)
                        page_data = page.extract_data()
                        row = {
                            "url": url, "status": "ok",
                            "page_name": page_data.get("page_name", ""),
                            "h1": page_data.get("h1", ""),
                            "file": str(png_path),
                            "pdf": str(pdf_path) if pdf_path else "",
                        }
                except Exception as exc:
                    row = {"url": url, "status": f"error: {exc}"}
                results.append(row)
                time.sleep(random.uniform(
                    runtime_cfg["timing"]["inter_page_delay_min"],
                    runtime_cfg["timing"]["inter_page_delay_max"],
                ))

        # Compute internal_inlinks from outlink counts across all pages
        if kind == "seo":
            _compute_internal_inlinks(results)

        csv_path = data_dir / ("seo_results.csv" if kind == "seo" else "capture_results.csv")
        write_results_csv(results, csv_path)

        timestamp = datetime.now().isoformat()
        total = len(results)
        ok_count = sum(1 for r in results if r.get("status") == "ok")
        save_history({
            "timestamp": timestamp,
            "kind": kind,
            "total": total,
            "ok": ok_count,
            "fail": total - ok_count,
            "output_dir": str(output_dir),
            "results": results,
        })


class ExtractionRunner:
    def __init__(self, urls: list[str], rules: list[dict], runtime_cfg: dict, output_dir: Path):
        self.urls = urls
        self.rules = rules
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
        self.results = []
        self.cancelled = False
        self._thread = None

    def run(self):
        self.results = []
        output_dir = self.output_dir
        urls = self.urls
        rules = self.rules
        runtime_cfg = self.runtime_cfg
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        results = self.results

        with SB(uc=True, test=True, headless=False, window_size=f"{runtime_cfg['viewport']['width']},{runtime_cfg['viewport']['height']}") as sb:
            page = PageCapture(sb, runtime_cfg)
            for i, url in enumerate(urls):
                if self.cancelled:
                    break
                row = {"url": url, "status": "waiting"}
                try:
                    if not is_valid_url(url):
                        row["status"] = "invalid URL"
                        results.append(row)
                        continue
                    page.open(url)
                    page.scroll()
                    sb.sleep(runtime_cfg["timing"]["stabilization_ms"] / 1000)
                    page.hide_overlays()
                    data = extract_from_page(sb, rules)
                    row = {"url": url, "status": "ok", **data}
                except Exception as exc:
                    row = {"url": url, "status": f"error: {exc}"}
                results.append(row)
                time.sleep(random.uniform(
                    runtime_cfg["timing"]["inter_page_delay_min"],
                    runtime_cfg["timing"]["inter_page_delay_max"],
                ))

        csv_path = data_dir / "extraction_results.csv"
        write_results_csv(results, csv_path)

        timestamp = datetime.now().isoformat()
        total = len(results)
        ok_count = sum(1 for r in results if r.get("status") == "ok")
        save_history({
            "timestamp": timestamp,
            "kind": "extraction",
            "total": total,
            "ok": ok_count,
            "fail": total - ok_count,
            "output_dir": str(output_dir),
            "results": results,
        })


class UnifiedRunner:
    """Run multiple collectors against the same URL list in one browser session.

    Each collector produces its own CSV; the history entry is one record tagged
    with the list of collectors actually run.
    """

    _thread: Optional[threading.Thread]

    def __init__(self, urls: list[str], collectors: list[dict], runtime_cfg: dict, output_dir: Path, seo_fields: list[dict] | None = None):
        self.urls = urls
        self.collectors = collectors
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
        self.seo_fields = seo_fields
        self.results = {"screenshot": [], "seo": [], "extraction": []}
        self.cancelled = False
        self._thread = None
        self.status = "queued"
        self.progress_total = len(urls) * max(len(collectors), 1)
        self.progress_done = 0

    def _bump_progress(self, n: int = 1) -> None:
        self.progress_done += n

    def run(self):
        self.results = {"screenshot": [], "seo": [], "extraction": []}
        self.progress_done = 0
        urls = self.urls
        runtime_cfg = self.runtime_cfg
        output_dir = self.output_dir
        collectors = self.collectors

        photos_dir = output_dir / "photos"
        photos_dir.mkdir(parents=True, exist_ok=True)
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        active = {c["name"] for c in collectors}
        run_screenshot = "screenshot" in active
        run_seo = "seo" in active
        run_extraction = "extraction" in active

        rules_by_collector: dict[str, list[dict]] = {}
        for c in collectors:
            if c["name"] == "extraction":
                rules_by_collector["extraction"] = c.get("rules") or []

        with SB(uc=True, test=True, headless=False, window_size=f"{runtime_cfg['viewport']['width']},{runtime_cfg['viewport']['height']}") as sb:
            page = PageCapture(sb, runtime_cfg)
            for i, url in enumerate(urls):
                if self.cancelled:
                    break
                slug = slugify(url)

                ss_row = None
                seo_row = None
                ext_row = None

                ok = False
                err = None
                if not is_valid_url(url):
                    err = "invalid URL"
                else:
                    try:
                        self.status = f"Opening {url}"
                        page.open(url)
                        page.scroll()
                        sb.sleep(runtime_cfg["timing"]["stabilization_ms"] / 1000)
                        page.hide_overlays()
                        ok = True
                    except Exception as exc:
                        err = str(exc)

                if run_screenshot:
                    if ok:
                        try:
                            png_path = photos_dir / f"{slug}.png"
                            page.capture_png(png_path)
                            page_data = page.extract_data()
                            ss_row = {
                                "url": url, "status": "ok",
                                "page_name": page_data.get("page_name", ""),
                                "h1": page_data.get("h1", ""),
                                "file": str(png_path),
                            }
                        except Exception as exc:
                            ss_row = {"url": url, "status": f"error: {exc}"}
                    else:
                        ss_row = {"url": url, "status": f"error: {err}"}
                    self.results["screenshot"].append(ss_row)
                    self._bump_progress()

                if run_seo and not self.cancelled:
                    if ok:
                        try:
                            fields = self.seo_fields or get_standard_seo_fields()
                            raw = sb.cdp.evaluate(build_seo_js(fields))
                            seo_row = {"url": url, "status": "ok", **parse_seo_fields(raw, fields)}
                        except Exception as exc:
                            seo_row = {"url": url, "status": f"error: {exc}"}
                    else:
                        seo_row = {"url": url, "status": f"error: {err}"}
                    self.results["seo"].append(seo_row)
                    self._bump_progress()

                if run_extraction and not self.cancelled:
                    rules = rules_by_collector.get("extraction", [])
                    if ok and rules:
                        try:
                            data = extract_from_page(sb, rules)
                            ext_row = {"url": url, "status": "ok", **data}
                        except Exception as exc:
                            ext_row = {"url": url, "status": f"error: {exc}"}
                    elif not ok:
                        ext_row = {"url": url, "status": f"error: {err}"}
                    else:
                        ext_row = {"url": url, "status": "no rules defined"}
                    self.results["extraction"].append(ext_row)
                    self._bump_progress()

                time.sleep(random.uniform(
                    runtime_cfg["timing"]["inter_page_delay_min"],
                    runtime_cfg["timing"]["inter_page_delay_max"],
                ))

        # Compute internal_inlinks from outlink counts across all pages
        if self.results.get("seo"):
            _compute_internal_inlinks(self.results["seo"])

        for kind, rows in self.results.items():
            if not rows:
                continue
            csv_path = data_dir / f"{kind}_results.csv"
            write_results_csv(rows, csv_path)

        total = sum(len(r) for r in self.results.values())
        ok_count = sum(
            1 for rows in self.results.values() for r in rows if r.get("status") == "ok"
        )
        save_history({
            "timestamp": datetime.now().isoformat(),
            "kind": "unified",
            "collectors": [c["name"] for c in collectors],
            "total": total,
            "ok": ok_count,
            "fail": total - ok_count,
            "output_dir": str(output_dir),
            "results_by_collector": self.results,
        })
        self.status = "done"


# ── Fast crawl (curl_cffi + threads) ────────────────────────────────────────────


def _fetch_and_extract(
    url: str,
    cookies: dict[str, str],
    user_agent: str,
    timeout: float = 30.0,
) -> dict:
    """Fetch one URL with curl_cffi (Chrome TLS impersonation) and extract SEO data."""
    from curl_cffi import requests as _curl
    from lxml import html as _html

    headers = {"User-Agent": user_agent} if user_agent else {}
    try:
        resp = _curl.get(url, cookies=cookies, headers=headers, timeout=timeout, impersonate="chrome")
    except Exception as exc:
        return {"url": url, "status": f"error: {exc}"}

    status_code = resp.status_code
    host = url.split("//")[-1].split("/")[0].split(":")[0]
    # Non-2xx responses are almost always bot-block pages (403/503/etc.)
    if status_code != 200:
        return {
            "url": url,
            "status": f"http_{status_code}",
            "status_code": status_code,
        }
    data: dict = {"url": url, "status": "ok", "status_code": status_code}

    try:
        tree = _html.fromstring(resp.text)
    except Exception:
        tree = None

    if tree is None:
        return data

    def _text(expr: str) -> str:
        return " ".join(t.strip() for t in tree.xpath(expr) if isinstance(t, str) and t.strip())

    def _attr(expr: str) -> str:
        vals = tree.xpath(expr)
        return vals[0].strip() if vals else ""

    title = _text("//title/text()")
    data["title"] = title
    data["title_len"] = len(title)

    meta_desc = _attr("//meta[@name='description']/@content")
    data["meta_description"] = meta_desc
    data["meta_desc_len"] = len(meta_desc)

    data["canonical"] = _attr("//link[@rel='canonical']/@href")
    data["robots_meta"] = _attr("//meta[@name='robots']/@content")

    data["h1"] = _text("//h1//text()")
    data["h2s"] = " | ".join(t for t in _text("//h2//text()").split(" | ")[:15])[:500]
    data["h3s"] = " | ".join(t for t in _text("//h3//text()").split(" | ")[:15])[:500]

    data["og_title"] = _attr("//meta[@property='og:title']/@content")
    data["og_description"] = _attr("//meta[@property='og:description']/@content")
    data["og_image"] = _attr("//meta[@property='og:image']/@content")

    schema_types = []
    for script_text in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            d = json.loads(script_text)
            t = d.get("@type", "")
            if isinstance(t, list):
                schema_types.extend(t)
            elif t:
                schema_types.append(t)
        except (json.JSONDecodeError, AttributeError):
            pass
    data["schema_types"] = " | ".join(schema_types)

    body_text = " ".join(tree.xpath("//body//text()"))
    data["word_count"] = len(body_text.split())

    internal = 0
    external = 0
    for href in tree.xpath("//a/@href"):
        href = href.strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        if href.startswith("//"):
            link_host = href[2:].split("/")[0].split(":")[0]
        elif href.startswith("http"):
            link_host = href.split("//")[-1].split("/")[0].split(":")[0]
        else:
            link_host = host
        if link_host == host:
            internal += 1
        else:
            external += 1
    data["internal_links"] = internal
    data["external_links"] = external

    imgs = tree.xpath("//img")
    missing = sum(1 for img in imgs if not (img.attrib.get("alt", "") or "").strip())
    data["images_missing_alt"] = missing

    # Soft-block detection: sites sometimes return 200 with a challenge/block page.
    # (Hard blocks via non-200 are already caught above by status_code != 200.)
    _BLOCK_MARKERS = (
        "just a moment", "attention required", "checking your browser",
        "dealer website", "access denied", "are you a robot", "enable javascript",
    )
    if data.get("status") == "ok":
        title_low = (data.get("title") or "").lower()
        if any(m in title_low for m in _BLOCK_MARKERS):
            data["status"] = "blocked"

    return data


class FastRunner:
    """Fast crawl using curl_cffi + ThreadPoolExecutor with cookies from SeleniumBase.

    Flow:
    1. Open first URL in SeleniumBase, solve Turnstile.
    2. Export cookies + user-agent.
    3. Close browser.
    4. Crawl all URLs concurrently with curl_cffi (8 threads).
    5. Collect results into ``self.results["seo"]``.
    """

    _thread: Optional[threading.Thread]

    def __init__(
        self,
        urls: list[str],
        runtime_cfg: dict,
        output_dir: Path,
        seo_fields: list[dict] | None = None,
    ):
        self.urls = urls
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
        self.seo_fields = seo_fields
        self.results: dict[str, list[dict]] = {"seo": []}
        self.cancelled = False
        self._thread = None
        self.status = "queued"
        self.progress_total = len(urls)
        self.progress_done = 0

    def _refresh_session(self, seed_url: str) -> dict:
        """Open a browser, solve Turnstile, and return a fresh session dict.

        Used to obtain a new clearance cookie when a crawl batch gets blocked.
        """
        viewport = self.runtime_cfg["viewport"]
        try:
            with SB(
                uc=True, test=True, headless=False,
                window_size=f"{viewport['width']},{viewport['height']}",
            ) as sb:
                page = PageCapture(sb, self.runtime_cfg)
                self.status = f"Solving Turnstile on {seed_url}"
                page.open(seed_url)
                page.scroll()
                sb.sleep(self.runtime_cfg["timing"]["stabilization_ms"] / 1000)
                page.hide_overlays()
                return page.extract_session()
        except Exception:
            return {}

    def _crawl_batch(self, urls: list[str], cookies_dict: dict, user_agent: str) -> list[dict]:
        if not urls:
            return []
        items: list[dict] = []
        max_workers = min(8, len(urls))

        def _crawl_one(url: str) -> dict:
            try:
                return _fetch_and_extract(url, cookies_dict, user_agent)
            except Exception as exc:
                return {"url": url, "status": f"error: {exc}"}

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_crawl_one, url): url for url in urls}
            for future in as_completed(futures):
                if self.cancelled:
                    break
                items.append(future.result())
        return items

    def run(self):
        self.results = {"seo": []}
        self.progress_done = 0
        self.status = "Starting browser..."

        output_dir = self.output_dir
        data_dir = output_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: open browser, solve Turnstile on first URL, export session
        session = self._refresh_session(self.urls[0])
        cookies_dict = {c["name"]: c["value"] for c in session.get("cookies", [])}
        user_agent = session.get("user_agent", "")

        # Step 2: crawl all URLs concurrently with curl_cffi
        self.status = f"Crawling {len(self.urls)} URLs..."
        items = self._crawl_batch(self.urls, cookies_dict, user_agent)
        self.progress_done = min(len(items), self.progress_total)

        # Step 3: retry anything that was blocked with a fresh Turnstile session
        max_retries = 3
        for attempt in range(max_retries):
            blocked = [
                it for it in items
                if not (it.get("status") == "ok" and it.get("status_code") == 200)
            ]
            if not blocked or self.cancelled:
                break
            self.status = f"Retrying {len(blocked)} blocked URLs (attempt {attempt + 1}/{max_retries})..."
            fresh = self._refresh_session(blocked[0]["url"])
            if not fresh.get("cookies"):
                break
            cookies_dict = {c["name"]: c["value"] for c in fresh.get("cookies", [])}
            user_agent = fresh.get("user_agent", "")
            retried = self._crawl_batch([it["url"] for it in blocked], cookies_dict, user_agent)
            by_url = {r["url"]: r for r in retried}
            for it in items:
                u = it.get("url")
                if u in by_url:
                    it.clear()
                    it.update(by_url[u])
            self.progress_done = min(len(items), self.progress_total)

        self.results["seo"] = items
        self.progress_done = self.progress_total
        self.status = "done"

        if items:
            _compute_internal_inlinks(items)

        csv_path = data_dir / "seo_results.csv"
        write_results_csv(items, csv_path)

        total = len(items)
        ok_count = sum(1 for r in items if r.get("status") == "ok")
        save_history({
            "timestamp": datetime.now().isoformat(),
            "kind": "fast_seo",
            "total": total,
            "ok": ok_count,
            "fail": total - ok_count,
            "output_dir": str(output_dir),
            "results": items,
        })
