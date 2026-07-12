"""Page Capture — Desktop app for screenshots and SEO extraction."""

from __future__ import annotations

import csv
import io
import json
import random
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from page_capture import PageCapture, load_config
from seleniumbase import SB

from importers import (
    import_from_sitemap_url,
    import_from_sitemap_xml,
    import_from_csv_file,
    import_from_wp_xml,
    parse_urls_text,
    is_valid_url,
)

HERE = Path(__file__).resolve().parent
CONFIG = load_config(HERE / "config.yaml")
HISTORY_FILE = HERE / ".run_history.json"


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


def build_zip(results: list[dict], output_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            for key in ("png", "pdf"):
                p = Path(r.get(key, ""))
                if p.exists() and p.is_file():
                    zf.write(p, arcname=p.name)
    return buf.getvalue()


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


# ── Capture runner ──

class CaptureRunner:
    def __init__(self, urls, runtime_cfg, output_dir, kind="screenshot"):
        self.urls = urls
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
        self.kind = kind
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
                        payload = json.loads(raw or "{}")
                        row = {
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
                        }
                    else:
                        png_path = photos_dir / f"{slug}.png"
                        page.capture_png(png_path)
                        row = {
                            "url": url, "status": "ok",
                            "page_name": (page.extract_data()).get("page_name", ""),
                            "h1": (page.extract_data()).get("h1", ""),
                            "file": str(png_path),
                        }
                except Exception as exc:
                    row = {"url": url, "status": f"error: {exc}"}
                results.append(row)
                time.sleep(random.uniform(
                    runtime_cfg["timing"]["inter_page_delay_min"],
                    runtime_cfg["timing"]["inter_page_delay_max"],
                ))

        csv_path = data_dir / ("seo_results.csv" if kind == "seo" else "capture_results.csv")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            if results:
                w = csv.DictWriter(f, fieldnames=results[0].keys())
                w.writeheader()
                w.writerows(results)

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


# ── Review UI (shared by capture and history) ──

def render_results(results: list[dict], kind: str, output_dir: Path, key_prefix: str = "") -> None:
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    fail_count = len(results) - ok_count

    tabs = st.tabs(["Summary", "Details + Notes", "Preview"])

    with tabs[0]:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total", len(results))
        col2.metric("OK", ok_count)
        col3.metric("Failed", fail_count)

    with tabs[1]:
        df = pd.DataFrame(results)
        dcols = [c for c in df.columns if c not in ("png", "pdf", "file")]
        display_df = df[dcols] if dcols else df
        st.dataframe(display_df, width="stretch", hide_index=True, use_container_width=True)

        url_options = [f"{i+1}. {r['url']}" for i, r in enumerate(results)]
        sel_label = st.selectbox("Select a row for details", options=url_options, key=f"{key_prefix}row_sel")
        if sel_label:
            idx = int(sel_label.split(".")[0]) - 1
            row = results[idx]
            st.markdown("---")
            st.markdown(f"**Row {idx + 1}:** `{row['url']}`")
            with st.expander("Details", expanded=True):
                for k, v in row.items():
                    if k in ("png", "pdf", "file"):
                        continue
                    st.text_input(k, value=str(v), key=f"{key_prefix}detail_{k}_{idx}", label_visibility="collapsed")

            notes_key = f"{key_prefix}notes_{idx}"
            notes_val = st.session_state.get(notes_key, "")
            st.text_area("Notes", value=notes_val, key=notes_key, height=80)

            if kind == "screenshot":
                png_path = Path(row.get("file", ""))
                if png_path.exists():
                    st.image(str(png_path), use_container_width=True)

        if kind == "screenshot" and ok_count > 0:
            st.download_button(
                "Download ZIP",
                data=build_zip(results, output_dir),
                file_name="screenshots.zip",
                mime="application/zip",
                key=f"{key_prefix}dl_zip",
            )
        if kind == "seo" and results:
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            st.download_button(
                "Download CSV",
                data=csv_buf.getvalue().encode(),
                file_name="seo_results.csv",
                mime="text/csv",
                key=f"{key_prefix}dl_csv",
            )

    with tabs[2]:
        if kind == "screenshot":
            png_files = [
                r.get("file", "") for r in results
                if r.get("file") and Path(r.get("file", "")).exists()
            ]
            if not png_files:
                st.info("No screenshots available.")
            else:
                selected = st.selectbox(
                    "Choose screenshot",
                    options=png_files,
                    format_func=lambda x: Path(x).name,
                    key=f"{key_prefix}preview_sel",
                )
                if selected:
                    st.image(selected, use_container_width=True)
                    with open(selected, "rb") as f:
                        st.download_button(
                            "Download",
                            data=f,
                            file_name=Path(selected).name,
                            mime="image/png",
                            key=f"{key_prefix}preview_dl",
                        )
        else:
            st.info("Preview not available for SEO results. Check the Details tab.")


# ── Import Tab ──

IMPORT_SOURCES = ["Manual (text area)", "Sitemap URL", "Paste sitemap XML", "CSV file (upload)", "WordPress XML (upload)"]

def render_import_tab() -> list[str] | None:
    st.subheader("Import URLs")

    source = st.radio("Source", IMPORT_SOURCES, horizontal=True, key="import_source")

    urls: list[str] = []

    if source == "Manual (text area)":
        raw = st.text_area("URLs (one per line)", height=200, placeholder="https://example.com\nhttps://example.org", key="import_manual")
        if raw:
            urls = parse_urls_text(raw)

    elif source == "Sitemap URL":
        sitemap_url = st.text_input("Sitemap URL", placeholder="https://example.com/sitemap.xml", key="import_sitemap_url")
        if sitemap_url and st.button("Fetch & Parse", key="import_sitemap_fetch"):
            with st.spinner("Fetching sitemap..."):
                try:
                    urls = import_from_sitemap_url(sitemap_url)
                    st.success(f"Found {len(urls)} URLs")
                except Exception as e:
                    st.error(f"Failed: {e}")

    elif source == "Paste sitemap XML":
        raw_xml = st.text_area("Paste sitemap XML", height=250, key="import_sitemap_xml")
        if raw_xml and st.button("Parse", key="import_sitemap_parse"):
            try:
                urls = import_from_sitemap_xml(raw_xml)
                st.success(f"Found {len(urls)} URLs")
            except Exception as e:
                st.error(f"Failed: {e}")

    elif source == "CSV file (upload)":
        uploaded = st.file_uploader("Upload CSV", type=["csv", "txt"], key="import_csv")
        if uploaded:
            raw = uploaded.read().decode("utf-8", errors="replace")
            pairs = import_from_csv_file(raw)
            if pairs:
                has_second = any(b is not None for _, b in pairs)
                if has_second:
                    st.info("CSV has two columns — only using first column for capture")
                urls = [a for a, _ in pairs]
                st.success(f"Found {len(urls)} URLs from CSV")
            else:
                st.error("No valid URLs found in CSV")

    elif source == "WordPress XML (upload)":
        uploaded = st.file_uploader("Upload WordPress XML export", type=["xml"], key="import_wp")
        if uploaded:
            raw = uploaded.read()
            try:
                posts = import_from_wp_xml(raw)
                urls = [p["url"] for p in posts]
                st.success(f"Found {len(urls)} posts/pages from WordPress export")
                with st.expander("Preview posts"):
                    st.dataframe(pd.DataFrame(posts)[["title", "url", "date", "category"]])
            except Exception as e:
                st.error(f"Failed: {e}")

    else:
        urls = []

    if urls:
        n_invalid = sum(1 for u in urls if not is_valid_url(u))
        st.caption(f"{len(urls)} URL(s) loaded" + (f", {n_invalid} invalid (will be skipped)" if n_invalid else ""))
        with st.expander("Preview loaded URLs"):
            st.dataframe(pd.DataFrame({"url": urls}), use_container_width=True, hide_index=True)
        return urls

    return None


# ── Main UI ──

def main() -> None:
    st.set_page_config(page_title="Page Capture", layout="wide")
    st.title("Page Capture")
    st.caption("Automated screenshots and SEO extraction via headless Chromium.")

    if "runner" not in st.session_state:
        st.session_state.runner = None
    if "running" not in st.session_state:
        st.session_state.running = False
    if "capture_urls" not in st.session_state:
        st.session_state.capture_urls = None

    tab_import, tab_ss, tab_seo, tab_cfg, tab_history = st.tabs(["Import URLs", "Screenshots", "SEO Extraction", "Settings", "History"])

    # ── Import Tab ──
    with tab_import:
        urls = render_import_tab()
        if urls:
            st.session_state.capture_urls = urls
            valid_urls = [u for u in urls if is_valid_url(u)]
            st.info(f"Ready: {len(valid_urls)} valid URL(s)")
            if st.button("Send to Screenshots tab", key="to_ss"):
                st.session_state.ss_urls_text = "\n".join(urls)
                st.rerun()
            if st.button("Send to SEO tab", key="to_seo"):
                st.session_state.seo_urls_text = "\n".join(urls)
                st.rerun()

    # ── Screenshots Tab ──
    with tab_ss:
        default_ss = st.session_state.get("ss_urls_text", "")
        with st.form("ss_form"):
            urls_text = st.text_area("URLs (one per line)", height=150, placeholder="https://example.com\nhttps://example.org", value=default_ss)
            col1, col2, col3 = st.columns(3)
            with col1:
                ss_width = st.number_input("Width", value=CONFIG["viewport"]["width"], min_value=320, max_value=3840)
            with col2:
                ss_height = st.number_input("Height", value=CONFIG["viewport"]["height"], min_value=320, max_value=2160)
            with col3:
                ss_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0)
            col4, col5 = st.columns(2)
            with col4:
                ss_pdf = st.checkbox("Also save PDF", value=False)
            with col5:
                output_name = st.text_input("Output folder name", value=f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            submitted = st.form_submit_button("Run Capture", disabled=st.session_state.running)

        if submitted:
            urls = parse_urls_text(urls_text)
            invalid = [u for u in urls if not is_valid_url(u)]
            if not urls:
                st.warning("Enter at least one URL.")
            elif invalid:
                st.error(f"Invalid URLs: {', '.join(invalid)}")
            else:
                output_dir = HERE / output_name
                output_dir.mkdir(parents=True, exist_ok=True)
                runtime_cfg = {
                    "viewport": {"width": int(ss_width), "height": int(ss_height)},
                    "timing": {**CONFIG["timing"], "stabilization_ms": int(ss_delay * 1000)},
                    "hide": CONFIG.get("hide", {}),
                    "hide_visibility": CONFIG.get("hide_visibility", {}),
                }
                runner = CaptureRunner(urls, runtime_cfg, output_dir, "screenshot")
                st.session_state.runner = runner
                st.session_state.running = True

        if st.session_state.running and st.session_state.runner:
            runner = st.session_state.runner
            status_placeholder = st.empty()
            progress_bar = st.progress(0)
            cancel_col = st.columns([1])[0]
            if cancel_col.button("Cancel", key="cancel_ss"):
                runner.cancelled = True

            if not runner._thread or not runner._thread.is_alive():
                runner._thread = threading.Thread(target=runner.run, daemon=True)
                runner._thread.start()

            alive = True
            while alive:
                alive = runner._thread.is_alive()
                done = len(runner.results)
                total = len(runner.urls)
                pct = min(done / total, 1.0) if total else 0
                progress_bar.progress(pct, text=f"{done}/{total}")
                if runner.results:
                    last = runner.results[-1]
                    status_placeholder.info(f"Last: {last['url']} — {last['status']}")
                if not alive:
                    break
                time.sleep(0.3)

            st.session_state.running = False
            st.success(f"Done — {len(runner.results)} URL(s) processed.")
            render_results(runner.results, "screenshot", runner.output_dir, key_prefix="ss_")

    # ── SEO Tab ──
    with tab_seo:
        default_seo = st.session_state.get("seo_urls_text", "")
        with st.form("seo_form"):
            urls_text_seo = st.text_area("URLs (one per line)", height=150, placeholder="https://example.com\nhttps://example.org", value=default_seo, key="seo_urls")
            seo_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="seo_delay")
            seo_output_name = st.text_input("Output folder name", value=f"seo_{datetime.now().strftime('%Y%m%d_%H%M%S')}", key="seo_output")
            seo_submitted = st.form_submit_button("Run SEO Extraction", disabled=st.session_state.running)

        if seo_submitted:
            urls_seo = parse_urls_text(urls_text_seo)
            invalid = [u for u in urls_seo if not is_valid_url(u)]
            if not urls_seo:
                st.warning("Enter at least one URL.")
            elif invalid:
                st.error(f"Invalid URLs: {', '.join(invalid)}")
            else:
                output_dir = HERE / seo_output_name
                output_dir.mkdir(parents=True, exist_ok=True)
                runtime_cfg = {
                    "viewport": {**CONFIG["viewport"]},
                    "timing": {**CONFIG["timing"], "stabilization_ms": int(seo_delay * 1000)},
                    "hide": CONFIG.get("hide", {}),
                    "hide_visibility": CONFIG.get("hide_visibility", {}),
                }
                runner = CaptureRunner(urls_seo, runtime_cfg, output_dir, "seo")
                st.session_state.runner = runner
                st.session_state.running = True

        if st.session_state.running and st.session_state.runner:
            runner = st.session_state.runner
            status_placeholder = st.empty()
            progress_bar = st.progress(0)
            cancel_col = st.columns([1])[0]
            if cancel_col.button("Cancel", key="cancel_seo"):
                runner.cancelled = True

            if not runner._thread or not runner._thread.is_alive():
                runner._thread = threading.Thread(target=runner.run, daemon=True)
                runner._thread.start()

            alive = True
            while alive:
                alive = runner._thread.is_alive()
                done = len(runner.results)
                total = len(runner.urls)
                pct = min(done / total, 1.0) if total else 0
                progress_bar.progress(pct, text=f"{done}/{total}")
                if runner.results:
                    last = runner.results[-1]
                    status_placeholder.info(f"Last: {last['url']} — {last['status']}")
                if not alive:
                    break
                time.sleep(0.3)

            st.session_state.running = False
            st.success(f"Done — {len(runner.results)} URL(s) extracted.")
            render_results(runner.results, "seo", runner.output_dir, key_prefix="seo_")

    # ── Settings Tab ──
    with tab_cfg:
        st.subheader("Configuration")
        with st.form("cfg_form"):
            new_width = st.number_input("Viewport width", value=CONFIG["viewport"]["width"], min_value=320, max_value=3840)
            new_height = st.number_input("Viewport height", value=CONFIG["viewport"]["height"], min_value=320, max_value=2160)
            new_stab = st.number_input("Stabilization (ms)", value=CONFIG["timing"]["stabilization_ms"], min_value=500, max_value=10000, step=100)
            new_min_delay = st.number_input("Inter-page delay min (s)", value=CONFIG["timing"]["inter_page_delay_min"], min_value=0.0, max_value=10.0)
            new_max_delay = st.number_input("Inter-page delay max (s)", value=CONFIG["timing"]["inter_page_delay_max"], min_value=0.0, max_value=10.0)
            if st.form_submit_button("Save"):
                CONFIG["viewport"]["width"] = int(new_width)
                CONFIG["viewport"]["height"] = int(new_height)
                CONFIG["timing"]["stabilization_ms"] = int(new_stab)
                CONFIG["timing"]["inter_page_delay_min"] = float(new_min_delay)
                CONFIG["timing"]["inter_page_delay_max"] = float(new_max_delay)
                with open(HERE / "config.yaml", "w", encoding="utf-8") as f:
                    import yaml
                    yaml.dump(CONFIG, f, default_flow_style=False)
                st.success("Config saved to config.yaml")

        st.subheader("Manage Output Folders")
        folders = sorted([p for p in HERE.iterdir() if p.is_dir() and (p / "data").exists() or (p / "photos").exists()], key=lambda p: p.stat().st_mtime, reverse=True)
        if not folders:
            st.info("No output folders yet.")
        else:
            selected = st.selectbox("Select folder to clean", options=[str(f.relative_to(HERE)) for f in folders])
            if selected and st.button("Delete selected folder"):
                target = HERE / selected
                shutil.rmtree(target)
                st.success(f"Deleted {selected}")
                st.rerun()

    # ── History Tab ──
    with tab_history:
        st.subheader("Run History")
        history = load_history()
        if not history:
            st.info("No runs yet.")
        else:
            selected_idx = st.selectbox(
                "Select a past run to browse",
                options=range(len(history)),
                format_func=lambda i: f"{history[i]['timestamp'][:19]} — {history[i]['kind']} — {history[i]['ok']}/{history[i]['total']} OK",
                key="history_selector",
            )
            entry = history[selected_idx]
            kind = entry["kind"]
            results = entry.get("results", [])
            output_dir = Path(entry.get("output_dir", ""))

            st.caption(f"Run at {entry['timestamp'][:19]} | {entry['total']} URLs | {entry['ok']} OK | {entry['fail']} fail")

            col_rerun, col_delete, _ = st.columns([1, 1, 4])
            with col_rerun:
                if st.button("Re-run this job", key="hist_rerun"):
                    urls_rerun = [r["url"] for r in results]
                    st.session_state.capture_urls = urls_rerun
                    if kind == "screenshot":
                        st.session_state.ss_urls_text = "\n".join(urls_rerun)
                        st.rerun()
                    else:
                        st.session_state.seo_urls_text = "\n".join(urls_rerun)
                        st.rerun()
            with col_delete:
                if st.button("Delete from history", key="hist_del_entry"):
                    delete_history_entry(selected_idx)
                    st.rerun()

            if results:
                render_results(results, kind, output_dir, key_prefix=f"hist_{selected_idx}_")


if __name__ == "__main__":
    main()
