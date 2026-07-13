from __future__ import annotations

import csv
import io
import json
import random
import re
import threading
import time
import zipfile
from datetime import datetime
from typing import Optional
from pathlib import Path

import img2pdf
from PIL import Image

from page_capture import PageCapture
from seleniumbase import SB

from extraction import extract_from_page
from importers import is_valid_url

HERE = Path(__file__).resolve().parent
HISTORY_FILE = HERE / ".run_history.json"


def slugify(url: str) -> str:
    base = re.sub(r"^https?://", "", url.lower())
    return re.sub(r"[^a-z0-9]+", "_", base).strip("_")


def parse_seo_payload(raw: str) -> dict:
    """Parse the raw JSON string returned by _seo_js() into a flat dict."""
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
    def __init__(self, urls: list[str], runtime_cfg: dict, output_dir: Path, kind: str = "screenshot", generate_pdf: bool = False):
        self.urls = urls
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
        self.kind = kind
        self.generate_pdf = generate_pdf
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
                        raw = sb.cdp.evaluate(_seo_js())
                        row = {"url": url, "status": "ok", **parse_seo_payload(raw)}
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

    def __init__(self, urls: list[str], collectors: list[dict], runtime_cfg: dict, output_dir: Path):
        self.urls = urls
        self.collectors = collectors
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
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
                            raw = sb.cdp.evaluate(_seo_js())
                            seo_row = {"url": url, "status": "ok", **parse_seo_payload(raw)}
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
