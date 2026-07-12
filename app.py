"""Page Capture — Streamlit UI for screenshots and SEO extraction."""

from __future__ import annotations

import csv
import io
import json
import random
import re
import time
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from page_capture import PageCapture, load_config
from seleniumbase import SB

HERE = Path(__file__).resolve().parent
CONFIG = load_config(HERE / "config.yaml")


def parse_urls_input(raw: str) -> list[str]:
    cleaned: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for token in re.split(r"[,\s]+", line):
            token = token.strip()
            if not token or token.startswith("#"):
                continue
            cleaned.append(token)
    return cleaned


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
        .flat()
        .filter(Boolean)
        .join(' | ');
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
        title,
        metaDesc,
        canonical,
        robotsMeta,
        h1,
        h2s,
        h3s,
        ogTitle,
        ogDesc,
        ogImage,
        schemaTypes,
        wordCount,
        internal,
        external,
        imagesMissingAlt,
    });
})()
"""


def build_zip(results: list[dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            for key in ("png", "pdf"):
                p = Path(r.get(key, ""))
                if p.exists() and p.is_file():
                    zf.write(p, arcname=p.name)
    return buf.getvalue()


def main() -> None:
    st.set_page_config(page_title="Page Capture", layout="wide", page_icon="📸")
    st.title("📸 Page Capture")
    st.caption("Automated screenshots and SEO extraction via headless Chromium.")

    tab_ss, tab_seo, tab_cfg = st.tabs(["Screenshots", "SEO Extraction", "Settings"])

    # ── Screenshots Tab ──
    with tab_ss:
        with st.form("ss_form"):
            urls_text = st.text_area(
                "URLs (one per line)",
                height=150,
                placeholder="https://example.com\nhttps://example.org",
            )
            col1, col2, col3 = st.columns(3)
            with col1:
                ss_width = st.number_input("Width", value=CONFIG["viewport"]["width"], min_value=320, max_value=3840)
            with col2:
                ss_height = st.number_input("Height", value=CONFIG["viewport"]["height"], min_value=320, max_value=2160)
            with col3:
                ss_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=1.0, max_value=60.0)
            col4, col5 = st.columns(2)
            with col4:
                ss_full = st.checkbox("Full page", value=True)
            with col5:
                ss_pdf = st.checkbox("Also save PDF", value=False)
            submitted = st.form_submit_button("🚀 Run Capture")

        if submitted:
            urls = parse_urls_input(urls_text)
            if not urls:
                st.warning("Enter at least one URL.")
            else:
                runtime_cfg = {
                    "viewport": {"width": int(ss_width), "height": int(ss_height)},
                    "timing": {**CONFIG["timing"], "stabilization_ms": int(ss_delay * 1000)},
                    "hide": CONFIG.get("hide", {}),
                    "hide_visibility": CONFIG.get("hide_visibility", {}),
                }
                progress = st.progress(0, text="Starting...")
                results = []

                with SB(uc=True, test=True, headless=True, window_size=f"{ss_width},{ss_height}") as sb:
                    page = PageCapture(sb, runtime_cfg)
                    total = len(urls)
                    for i, url in enumerate(urls, start=1):
                        slug = slugify(url)
                        try:
                            page.open(url)
                            page.scroll()
                            sb.sleep(runtime_cfg["timing"]["stabilization_ms"] / 1000)
                            page.hide_overlays()
                            refs = {}
                            if True:
                                png_path = HERE / f"{slug}.png"
                                page.capture_png(png_path)
                                refs["png"] = str(png_path)
                            if ss_pdf:
                                pdf_path = HERE / f"{slug}.pdf"
                                page.capture_pdf(pdf_path)
                                refs["pdf"] = str(pdf_path)
                            extracted = page.extract_data()
                            results.append({
                                "url": url,
                                "status": "✅",
                                "page_name": extracted.get("page_name", ""),
                                "h1": extracted.get("h1", ""),
                                **refs,
                            })
                        except Exception as exc:
                            results.append({"url": url, "status": f"❌ {exc}"})
                        progress.progress(i / total, text=f"{i}/{total} — {url}")
                        time.sleep(random.uniform(
                            runtime_cfg["timing"]["inter_page_delay_min"],
                            runtime_cfg["timing"]["inter_page_delay_max"],
                        ))

                st.success(f"Done — {len(results)} URL(s) captured.")
                df = pd.DataFrame(results)
                st.dataframe(df, use_container_width=True)
                if results:
                    st.download_button(
                        "⬇ Download ZIP",
                        data=build_zip(results),
                        file_name="capture_results.zip",
                        mime="application/zip",
                    )

    # ── SEO Tab ──
    with tab_seo:
        with st.form("seo_form"):
            urls_text_seo = st.text_area(
                "URLs (one per line)",
                height=150,
                placeholder="https://example.com\nhttps://example.org",
                key="seo_urls",
            )
            seo_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=1.0, max_value=60.0, key="seo_delay")
            seo_submitted = st.form_submit_button("🚀 Run SEO Extraction")

        if seo_submitted:
            urls_seo = parse_urls_input(urls_text_seo)
            if not urls_seo:
                st.warning("Enter at least one URL.")
            else:
                runtime_cfg = {
                    "viewport": {**CONFIG["viewport"]},
                    "timing": {**CONFIG["timing"], "stabilization_ms": int(seo_delay * 1000)},
                    "hide": CONFIG.get("hide", {}),
                    "hide_visibility": CONFIG.get("hide_visibility", {}),
                }
                progress = st.progress(0, text="Starting...")
                seo_results = []

                with SB(uc=True, test=True, headless=True, window_size=f"{runtime_cfg['viewport']['width']},{runtime_cfg['viewport']['height']}") as sb:
                    page = PageCapture(sb, runtime_cfg)
                    total = len(urls_seo)
                    for i, url in enumerate(urls_seo, start=1):
                        try:
                            page.open(url)
                            sb.sleep(runtime_cfg["timing"]["stabilization_ms"] / 1000)
                            raw = sb.cdp.evaluate(_seo_js())
                            payload = json.loads(raw or "{}")
                            seo_results.append({
                                "url": url,
                                "status": "✅",
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
                        except Exception as exc:
                            seo_results.append({"url": url, "status": f"❌ {exc}"})
                        progress.progress(i / total, text=f"{i}/{total} — {url}")
                        time.sleep(random.uniform(
                            runtime_cfg["timing"]["inter_page_delay_min"],
                            runtime_cfg["timing"]["inter_page_delay_max"],
                        ))

                st.success(f"Done — {len(seo_results)} URL(s) extracted.")
                df_seo = pd.DataFrame(seo_results)
                st.dataframe(df_seo, use_container_width=True)
                if seo_results:
                    csv_buf = io.StringIO()
                    writer = csv.DictWriter(csv_buf, fieldnames=seo_results[0].keys())
                    writer.writeheader()
                    writer.writerows(seo_results)
                    st.download_button(
                        "⬇ Download CSV",
                        data=csv_buf.getvalue().encode(),
                        file_name="seo_results.csv",
                        mime="text/csv",
                    )

    # ── Settings Tab ──
    with tab_cfg:
        st.subheader("Configuration")
        st.json(CONFIG)


if __name__ == "__main__":
    main()
