"""Page Capture — Desktop app for screenshots and SEO extraction."""

from __future__ import annotations

import csv
import io
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from seleniumbase import SB

from page_capture import load_config, PageCapture
from extraction import (
    EXTRACTION_TYPES,
    save_ruleset,
    load_ruleset,
    delete_ruleset,
    list_rulesets,
)
from importers import (
    import_from_sitemap_url,
    import_from_sitemap_xml,
    import_from_csv_file,
    import_from_wp_xml,
    parse_urls_text,
    is_valid_url,
)
from runners import (
    CaptureRunner,
    ExtractionRunner,
    UnifiedRunner,
    build_zip,
    build_runtime_config,
    load_history,
    delete_history_entry,
    HERE,
)

CONFIG = load_config(HERE / "config.yaml")

# ── Session state init ──

def _init_session_state() -> None:
    defaults = {
        "runner": None,
        "running": False,
        "capture_urls": None,
        "extraction_rules": [],
        "extraction_runner": None,
        "unified_runner": None,
        "unified_running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Shared helpers ──

def _run_with_progress(runner: CaptureRunner | ExtractionRunner | UnifiedRunner, key_prefix: str, label: str = "") -> None:
    """Generic progress loop for any runner with _thread, results, cancelled."""
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    if st.button("Cancel", key=f"cancel_{key_prefix}"):
        runner.cancelled = True

    if not runner._thread or not runner._thread.is_alive():
        runner._thread = threading.Thread(target=runner.run, daemon=True)
        runner._thread.start()

    start_time = time.time()
    alive = True
    while alive:
        alive = runner._thread.is_alive()
        done = getattr(runner, "progress_done", len(getattr(runner, "results", [])))
        total = getattr(runner, "progress_total", len(getattr(runner, "urls", [])))
        pct = min(done / total, 1.0) if total else 0
        elapsed = time.time() - start_time
        eta_text = ""
        if done > 0 and total > done:
            eta_secs = int(elapsed / done * (total - done))
            eta_text = f" | ETA ~{eta_secs}s"
        progress_bar.progress(pct, text=f"{done}/{total}{eta_text}")
        status_placeholder.info(runner.status if hasattr(runner, "status") else label)
        if not alive:
            break
        time.sleep(0.3)


def render_results(results: list[dict], kind: str, output_dir: Path, key_prefix: str = "") -> None:
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    fail_count = len(results) - ok_count

    tabs = st.tabs(["Summary", "Details", "Preview"])

    with tabs[0]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(results))
        c2.metric("OK", ok_count)
        c3.metric("Failed", fail_count)

    with tabs[1]:
        # ── Filters ──
        filter_key = f"{key_prefix}filter_status"
        search_key = f"{key_prefix}filter_search"
        if filter_key not in st.session_state:
            st.session_state[filter_key] = "All"
        if search_key not in st.session_state:
            st.session_state[search_key] = ""

        fc1, fc2 = st.columns([1, 3])
        with fc1:
            status_filter = st.segmented_control(
                "Status", ["All", "OK", "Failed"],
                key=filter_key, label_visibility="collapsed",
            )
        with fc2:
            search = st.text_input(
                "Search URLs", key=search_key,
                placeholder="Filter by URL...",
                label_visibility="collapsed",
            )

        # ── Apply filters ──
        filtered = results
        if status_filter == "OK":
            filtered = [r for r in filtered if r.get("status") == "ok"]
        elif status_filter == "Failed":
            filtered = [r for r in filtered if r.get("status") != "ok"]
        if search.strip():
            q = search.strip().lower()
            filtered = [r for r in filtered if q in r.get("url", "").lower()]

        if not filtered:
            st.info("No results match the current filters.")
        else:
            df = pd.DataFrame(filtered)
            hide_cols = {"png", "pdf", "file"}
            dcols = [c for c in df.columns if c not in hide_cols]
            display_df = df[dcols] if dcols else df

            col_cfg: dict = {}
            if "url" in display_df.columns:
                col_cfg["url"] = st.column_config.LinkColumn("URL", pinned=True)
            if "status" in display_df.columns:
                col_cfg["status"] = st.column_config.TextColumn("Status")

            event = st.dataframe(
                display_df, width="stretch", hide_index=True,
                column_config=col_cfg or None,
                on_select="rerun", selection_mode="single-row",
                key=f"{key_prefix}df",
            )

            sel_rows = getattr(event, "selection", None)
            sel_rows = getattr(sel_rows, "rows", []) if sel_rows else []
            if sel_rows:
                idx = sel_rows[0]
                row = filtered[idx]
                st.markdown("---")
                st.markdown(f"**{row.get('url', '')}**")
                with st.expander("Details", expanded=True):
                    for k, v in row.items():
                        if k in ("png", "pdf", "file"):
                            continue
                        st.text(f"{k}: {v}")

                notes_key = f"{key_prefix}notes_{idx}"
                notes_val = st.session_state.get(notes_key, "")
                st.text_area("Notes", value=notes_val, key=notes_key, height=80)

                if kind == "screenshot":
                    png_path = Path(row.get("file", ""))
                    if png_path.exists():
                        st.image(str(png_path), width="stretch")
                    pdf_path = Path(row.get("pdf", ""))
                    if pdf_path.exists():
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                "Download PDF", data=f,
                                file_name=pdf_path.name, mime="application/pdf",
                                key=f"{key_prefix}preview_pdf_{idx}",
                            )

        if kind == "screenshot" and ok_count > 0:
            st.download_button(
                "Download ZIP", data=build_zip(results, output_dir),
                file_name="screenshots.zip", mime="application/zip",
                key=f"{key_prefix}dl_zip",
            )
        if kind in ("seo", "extraction") and results:
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            st.download_button(
                "Download CSV", data=csv_buf.getvalue().encode(),
                file_name=f"{kind}_results.csv", mime="text/csv",
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
                    "Choose screenshot", options=png_files,
                    format_func=lambda x: Path(x).name, key=f"{key_prefix}preview_sel",
                )
                if selected:
                    st.image(selected, width="stretch")
                    col_png, col_pdf = st.columns(2)
                    with col_png:
                        with open(selected, "rb") as f:
                            st.download_button(
                                "Download PNG", data=f,
                                file_name=Path(selected).name,
                                mime="image/png", key=f"{key_prefix}preview_dl",
                            )
                    selected_idx = png_files.index(selected)
                    pdf_file = results[selected_idx].get("pdf", "") if selected_idx < len(results) else ""
                    if pdf_file and Path(pdf_file).exists():
                        with col_pdf:
                            with open(pdf_file, "rb") as f:
                                st.download_button(
                                    "Download PDF", data=f,
                                    file_name=Path(pdf_file).name,
                                    mime="application/pdf", key=f"{key_prefix}preview_pdf_dl",
                                )
        else:
            st.info("Preview not available for this result type.")


# ── Page functions ──

def page_unified_crawl() -> None:
    """One batch, multiple collectors."""
    st.subheader("Unified Crawl")
    st.caption("Run screenshots, SEO, and custom extraction in a single browser session.")

    for key, default in (("unified_runner", None), ("unified_running", False)):
        if key not in st.session_state:
            st.session_state[key] = default

    seed_urls = ""
    if st.session_state.get("capture_urls"):
        seed_urls = "\n".join(st.session_state.capture_urls)

    with st.form("unified_form"):
        urls_text = st.text_area(
            "URLs (one per line)", height=150,
            placeholder="https://example.com\nhttps://example.org",
            value=seed_urls, key="unified_urls_text",
        )
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            do_screenshot = st.checkbox("Screenshots", value=True, key="unified_do_ss")
            ss_width = st.number_input("Width", value=CONFIG["viewport"]["width"], min_value=320, max_value=3840, key="unified_width")
            ss_height = st.number_input("Height", value=CONFIG["viewport"]["height"], min_value=320, max_value=2160, key="unified_height")
        with col_b:
            do_seo = st.checkbox("Quick SEO", value=True, key="unified_do_seo", help="Extracts title, meta description, H1/H2/H3, Open Graph tags, schema markup, word count, link counts, and images missing alt text.")
            delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="unified_delay")
        with col_c:
            do_extraction = st.checkbox("Custom Rules", value=False, key="unified_do_ext")
            output_name = st.text_input("Output folder name", value=f"unified_{datetime.now().strftime('%Y%m%d_%H%M%S')}", key="unified_output")

        rules = st.session_state.get("extraction_rules", [])
        if do_extraction and not rules:
            st.warning("Custom Rules is enabled but no rules are defined.")

        submitted = st.form_submit_button("Run Unified Crawl", disabled=st.session_state.unified_running)

    if submitted:
        urls = parse_urls_text(urls_text or "")
        invalid = [u for u in urls if not is_valid_url(u)]
        if not urls:
            st.warning("Enter at least one URL.")
        elif invalid:
            st.error(f"Invalid URLs: {', '.join(invalid)}")
        elif not any([do_screenshot, do_seo, do_extraction]):
            st.warning("Select at least one collector.")
        elif do_extraction and not rules:
            st.warning("Custom Rules selected but no rules defined.")
        else:
            output_dir = HERE / output_name
            output_dir.mkdir(parents=True, exist_ok=True)
            runtime_cfg = build_runtime_config(
                CONFIG,
                viewport={"width": int(ss_width), "height": int(ss_height)},
                stabilization_ms=int(delay * 1000),
            )
            collectors: list[dict] = []
            if do_screenshot:
                collectors.append({"name": "screenshot", "rules": None})
            if do_seo:
                collectors.append({"name": "seo", "rules": None})
            if do_extraction:
                collectors.append({"name": "extraction", "rules": rules})

            runner = UnifiedRunner(urls, collectors, rules, runtime_cfg, output_dir)
            st.session_state.unified_runner = runner
            st.session_state.unified_running = True
            st.session_state.capture_urls = urls

    if st.session_state.unified_running and st.session_state.unified_runner:
        runner = st.session_state.unified_runner
        _run_with_progress(runner, "unified")
        st.session_state.unified_running = False
        st.success(f"Done — {runner.progress_done}/{runner.progress_total} collector step(s) complete.")
        _render_unified_results(runner, key_prefix="unified_")


def _render_unified_results(runner: UnifiedRunner, key_prefix: str = "") -> None:
    output_dir = runner.output_dir
    collectors = [c["name"] for c in runner.collectors]
    labels = {
        "screenshot": "Screenshots", "seo": "Quick SEO",
        "extraction": "Custom Rules",
    }
    available = [c for c in collectors if runner.results.get(c)]
    if not available:
        st.info("No collector produced results.")
        return

    tab_labels = [labels[c] if c in labels else c for c in available] + ["Summary"]
    tabs = st.tabs(tab_labels)
    for tab, kind in zip(tabs[:-1], available):
        with tab:
            render_results(runner.results[kind], kind, output_dir, key_prefix=f"{key_prefix}{kind}_")

    with tabs[-1]:
        total = sum(len(runner.results[c]) for c in available)
        ok = sum(1 for c in available for r in runner.results[c] if r.get("status") == "ok")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total steps", total)
        c2.metric("OK", ok)
        c3.metric("Failed", total - ok)
        st.caption(f"Output: `{output_dir}`")
        if "screenshot" in runner.results and runner.results["screenshot"]:
            st.download_button(
                "Download Screenshots ZIP", data=build_zip(runner.results["screenshot"], output_dir),
                file_name="screenshots.zip", mime="application/zip", key=f"{key_prefix}zip",
            )


def page_import() -> None:
    st.subheader("Import URLs")
    source = st.radio("Source", [
        "Manual (text area)", "Sitemap URL", "Paste sitemap XML",
        "CSV file (upload)", "WordPress XML (upload)",
    ], horizontal=True, key="import_source")

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

    if urls:
        n_invalid = sum(1 for u in urls if not is_valid_url(u))
        st.caption(f"{len(urls)} URL(s) loaded" + (f", {n_invalid} invalid (will be skipped)" if n_invalid else ""))
        with st.expander("Preview loaded URLs"):
            st.dataframe(pd.DataFrame({"url": urls}), width="stretch", hide_index=True)
        if st.button("Send to Unified Crawl", key="to_unified"):
            st.session_state.capture_urls = urls
            st.rerun()


def page_screenshots() -> None:
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
            ss_pdf = st.checkbox("Also save PDF", value=False, key="ss_pdf")
        with col5:
            output_name = st.text_input("Output folder name", value=f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        submitted = st.form_submit_button("Run Capture", disabled=st.session_state.running)

    if submitted:
        urls = parse_urls_text(urls_text or "")
        invalid = [u for u in urls if not is_valid_url(u)]
        if not urls:
            st.warning("Enter at least one URL.")
        elif invalid:
            st.error(f"Invalid URLs: {', '.join(invalid)}")
        else:
            output_dir = HERE / output_name
            output_dir.mkdir(parents=True, exist_ok=True)
            runtime_cfg = build_runtime_config(
                CONFIG,
                viewport={"width": int(ss_width), "height": int(ss_height)},
                stabilization_ms=int(ss_delay * 1000),
            )
            runner = CaptureRunner(urls, runtime_cfg, output_dir, "screenshot", generate_pdf=ss_pdf)
            st.session_state.runner = runner
            st.session_state.running = True

    if st.session_state.running and st.session_state.runner:
        runner = st.session_state.runner
        _run_with_progress(runner, "ss")
        st.session_state.running = False
        st.success(f"Done — {len(runner.results)} URL(s) processed.")
        render_results(runner.results, "screenshot", runner.output_dir, key_prefix="ss_")


def page_extraction() -> None:
    st.subheader("Data Extraction")
    extract_mode = st.radio("Mode", ["Quick SEO", "Custom Rules"], horizontal=True, key="extract_mode")

    if extract_mode == "Quick SEO":
        st.caption("Extracts title, meta description, H1/H2/H3, Open Graph tags, schema markup, word count, link counts, and images missing alt text.")
        default_seo = st.session_state.get("seo_urls_text", "")
        with st.form("seo_form"):
            urls_text_seo = st.text_area("URLs (one per line)", height=150, placeholder="https://example.com\nhttps://example.org", value=default_seo, key="seo_urls")
            seo_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="seo_delay")
            seo_output_name = st.text_input("Output folder name", value=f"seo_{datetime.now().strftime('%Y%m%d_%H%M%S')}", key="seo_output")
            seo_submitted = st.form_submit_button("Run SEO Extraction", disabled=st.session_state.running)

        if seo_submitted:
            urls_seo = parse_urls_text(urls_text_seo or "")
            invalid = [u for u in urls_seo if not is_valid_url(u)]
            if not urls_seo:
                st.warning("Enter at least one URL.")
            elif invalid:
                st.error(f"Invalid URLs: {', '.join(invalid)}")
            else:
                output_dir = HERE / seo_output_name
                output_dir.mkdir(parents=True, exist_ok=True)
                runtime_cfg = build_runtime_config(
                    CONFIG,
                    viewport={**CONFIG["viewport"]},
                    stabilization_ms=int(seo_delay * 1000),
                )
                runner = CaptureRunner(urls_seo, runtime_cfg, output_dir, "seo")
                st.session_state.runner = runner
                st.session_state.running = True

        if st.session_state.running and st.session_state.runner:
            runner = st.session_state.runner
            _run_with_progress(runner, "seo")
            st.session_state.running = False
            st.success(f"Done — {len(runner.results)} URL(s) extracted.")
            render_results(runner.results, "seo", runner.output_dir, key_prefix="seo_")
    else:
        _render_extraction_rules_tab()


def page_settings() -> None:
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
            import yaml
            with open(HERE / "config.yaml", "w", encoding="utf-8") as f:
                yaml.dump(CONFIG, f, default_flow_style=False)
            st.success("Config saved to config.yaml")

    st.subheader("Manage Output Folders")
    folders = sorted(
        [p for p in HERE.iterdir() if p.is_dir() and ((p / "data").exists() or (p / "photos").exists())],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not folders:
        st.info("No output folders yet.")
    else:
        selected = st.selectbox("Select folder to clean", options=[str(f.relative_to(HERE)) for f in folders])
        if selected:
            if st.button("Delete selected folder", type="secondary"):
                st.session_state["confirm_delete_folder"] = selected
            if st.session_state.get("confirm_delete_folder") == selected:
                st.warning(f"Delete `{selected}`? This cannot be undone.")
                c_yes, c_no, _ = st.columns([1, 1, 4])
                with c_yes:
                    if st.button("Yes, delete", type="primary", key="confirm_del_yes"):
                        shutil.rmtree(HERE / selected)
                        st.session_state.pop("confirm_delete_folder", None)
                        st.success(f"Deleted {selected}")
                        st.rerun()
                with c_no:
                    if st.button("Cancel", key="confirm_del_no"):
                        st.session_state.pop("confirm_delete_folder", None)
                        st.rerun()


def page_history() -> None:
    st.subheader("Run History")
    history = load_history()
    if not history:
        st.info("No runs yet.")
        return

    search = st.text_input("Search", placeholder="Filter by URL or kind...", key="hist_search", label_visibility="collapsed")
    filtered_indices = list(range(len(history)))
    if search.strip():
        q = search.strip().lower()
        filtered_indices = [
            i for i in filtered_indices
            if q in history[i].get("kind", "").lower()
            or any(q in r.get("url", "").lower() for r in history[i].get("results", []))
            or any(q in r.get("source_url", "").lower() for r in history[i].get("results", []))
        ]

    if not filtered_indices:
        st.info("No runs match the search.")
        return

    selected_idx = st.selectbox(
        "Select a past run to browse", options=filtered_indices,
        format_func=lambda i: f"{history[i]['timestamp'][:19]} — {history[i]['kind']} — {history[i]['ok']}/{history[i]['total']} OK",
        key="history_selector",
    )
    entry = history[selected_idx]
    kind = entry["kind"]
    results = entry.get("results", [])
    output_dir = Path(entry.get("output_dir", ""))

    st.caption(f"Run at {entry['timestamp'][:19]} | {entry['total']} URLs | {entry['ok']} OK | {entry['fail']} fail")

    col_rerun, col_delete, col_csv, col_zip, _ = st.columns([1, 1, 1, 1, 2])
    with col_rerun:
        if st.button("Re-run this job", key="hist_rerun"):
            urls_rerun = [r.get("url", r.get("source_url", "")) for r in results if r.get("url") or r.get("source_url")]
            if urls_rerun:
                st.session_state.capture_urls = urls_rerun
                st.rerun()
    with col_delete:
        if st.button("Delete from history", key="hist_del_entry"):
            delete_history_entry(selected_idx)
            st.rerun()
    with col_csv:
        if results and kind in ("seo", "extraction"):
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            st.download_button(
                "Download CSV", data=csv_buf.getvalue().encode(),
                file_name=f"{kind}_results.csv", mime="text/csv",
                key=f"hist_{selected_idx}_dl_csv",
            )
    with col_zip:
        if kind == "screenshot" and results:
            st.download_button(
                "Download ZIP", data=build_zip(results, output_dir),
                file_name="screenshots.zip", mime="application/zip",
                key=f"hist_{selected_idx}_dl_zip",
            )

    if kind == "unified":
        _render_history_unified(entry, selected_idx)
    elif results:
        render_results(results, kind, output_dir, key_prefix=f"hist_{selected_idx}_")


def _render_history_unified(entry: dict, idx: int) -> None:
    output_dir = Path(entry.get("output_dir", ""))
    by_kind = entry.get("results_by_collector", {})
    collectors = entry.get("collectors", list(by_kind.keys()))
    labels = {
        "screenshot": "Screenshots", "seo": "Quick SEO",
        "extraction": "Custom Rules",
    }
    available = [c for c in collectors if by_kind.get(c)]
    if not available:
        st.info("No collector results in this run.")
        return
    hist_labels = [labels[c] if c in labels else c for c in available]
    tabs = st.tabs(hist_labels)
    for tab, kind in zip(tabs, available):
        with tab:
            render_results(by_kind[kind], kind, output_dir, key_prefix=f"hist_{idx}_{kind}_")



# ── Extraction rules editor ──

def _rule_editor_row(i: int, rule: dict) -> None:
    cols = st.columns([2, 3, 1.5, 1.5, 0.8, 0.5])
    with cols[0]:
        rule["name"] = st.text_input("Field", value=rule.get("name", ""), key=f"er_name_{i}", label_visibility="collapsed", placeholder="Field name")
    with cols[1]:
        rule["selector"] = st.text_input("Selector", value=rule.get("selector", ""), key=f"er_sel_{i}", label_visibility="collapsed", placeholder="CSS selector")
    with cols[2]:
        rule["type"] = st.selectbox("Type", EXTRACTION_TYPES, index=EXTRACTION_TYPES.index(rule.get("type", "text")), key=f"er_type_{i}", label_visibility="collapsed")
    with cols[3]:
        rule["attribute"] = st.text_input("Attr", value=rule.get("attribute", ""), key=f"er_attr_{i}", label_visibility="collapsed", placeholder="href/src/alt")
    with cols[4]:
        rule["multiple"] = st.checkbox("M", value=rule.get("multiple", False), key=f"er_multi_{i}", label_visibility="collapsed", help="Multiple values")
    with cols[5]:
        st.button("✕", key=f"er_del_{i}", on_click=lambda idx=i: st.session_state.extraction_rules.pop(idx))


def _render_extraction_rules_tab() -> None:
    st.caption("Define custom CSS selector rules to extract data from pages.")
    rules: list[dict] = st.session_state.get("extraction_rules", [])
    if "extraction_rules" not in st.session_state:
        st.session_state.extraction_rules = rules

    if rules:
        header_cols = st.columns([2, 3, 1.5, 1.5, 0.8])
        header_cols[0].markdown("**Field**")
        header_cols[1].markdown("**Selector**")
        header_cols[2].markdown("**Type**")
        header_cols[3].markdown("**Attr**")
        header_cols[4].markdown("**Multi**")

        for i in range(len(rules) - 1, -1, -1):
            if i >= len(st.session_state.extraction_rules):
                continue
            _rule_editor_row(i, st.session_state.extraction_rules[i])

        with st.expander("Regex (optional)", expanded=False):
            for i, rule in enumerate(st.session_state.extraction_rules):
                rule["regex"] = st.text_input(
                    f"Regex — {rule.get('name', f'Rule {i+1}')}",
                    value=rule.get("regex", ""), key=f"er_regex_{i}",
                    placeholder="Optional regex to extract from result",
                )

    if st.button("+ Add Rule", key="er_add_rule"):
        st.session_state.extraction_rules.append({
            "name": "", "selector": "", "type": "text", "attribute": "", "regex": "", "multiple": False,
        })
        st.rerun()

    if rules:
        with st.expander("Test Rules (live preview)", expanded=False):
            preview_url = st.text_input("Test URL", placeholder="https://example.com", key="er_preview_url")
            if preview_url and st.button("Test", key="er_preview_btn"):
                if not is_valid_url(preview_url):
                    st.error("Invalid URL.")
                else:
                    from extraction import extract_from_page
                    try:
                        runtime_cfg = build_runtime_config(CONFIG, CONFIG["viewport"], CONFIG["timing"]["stabilization_ms"])
                        with SB(uc=True, test=True, headless=False, window_size=f"{runtime_cfg['viewport']['width']},{runtime_cfg['viewport']['height']}") as sb:
                            page = PageCapture(sb, runtime_cfg)
                            page.open(preview_url)
                            page.scroll()
                            sb.sleep(runtime_cfg["timing"]["stabilization_ms"] / 1000)
                            page.hide_overlays()
                            data = extract_from_page(sb, rules)
                            if data:
                                for k, v in data.items():
                                    st.text(f"{k}: {v}")
                            else:
                                st.info("No data extracted. Check your selectors.")
                    except Exception as e:
                        st.error(f"Preview failed: {e}")

    st.markdown("---")
    col_save, col_load, col_del, _ = st.columns([1, 1, 1, 4])
    with col_save:
        rs_name = st.text_input("Rule set name", key="er_rs_name", placeholder="my-rules", label_visibility="collapsed")
        if st.button("Save", key="er_save") and rs_name.strip():
            save_ruleset(st.session_state.extraction_rules, rs_name.strip())
            st.success(f"Saved as {rs_name.strip()}.json")
    with col_load:
        rs_list = list_rulesets()
        if rs_list:
            selected_rs = st.selectbox("Load", [""] + rs_list, key="er_rs_load", label_visibility="collapsed")
            if selected_rs and st.button("Load", key="er_load"):
                st.session_state.extraction_rules = load_ruleset(selected_rs)
                st.rerun()
    with col_del:
        if rs_list:
            del_rs = st.selectbox("Delete", [""] + rs_list, key="er_rs_del", label_visibility="collapsed")
            if del_rs and st.button("Delete", key="er_del_rs"):
                delete_ruleset(del_rs)
                st.rerun()

    st.markdown("---")
    rules = st.session_state.extraction_rules
    if not rules:
        st.info("Add at least one extraction rule above.")
        return

    default_urls = st.session_state.get("seo_urls_text", "")
    with st.form("extraction_form"):
        ext_urls = st.text_area("URLs (one per line)", height=120, placeholder="https://example.com\nhttps://example.org", value=default_urls, key="ext_urls")
        ext_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="ext_delay")
        ext_output = st.text_input("Output folder name", value=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}", key="ext_output")
        ext_submitted = st.form_submit_button("Run Extraction", disabled=st.session_state.running)

    if ext_submitted:
        parsed = parse_urls_text(ext_urls or "")
        invalid = [u for u in parsed if not is_valid_url(u)]
        if not parsed:
            st.warning("Enter at least one URL.")
        elif invalid:
            st.error(f"Invalid URLs: {', '.join(invalid)}")
        else:
            output_dir = HERE / ext_output
            output_dir.mkdir(parents=True, exist_ok=True)
            runtime_cfg = build_runtime_config(
                CONFIG,
                viewport={**CONFIG["viewport"]},
                stabilization_ms=int(ext_delay * 1000),
            )
            runner = ExtractionRunner(parsed, rules, runtime_cfg, output_dir)
            st.session_state.extraction_runner = runner
            st.session_state.running = True

    if st.session_state.running and st.session_state.get("extraction_runner"):
        runner = st.session_state.extraction_runner
        _run_with_progress(runner, "ext")
        st.session_state.running = False
        st.success(f"Done — {len(runner.results)} URL(s) extracted.")
        render_results(runner.results, "extraction", runner.output_dir, key_prefix="ext_")


# ── Dashboard ──

def page_dashboard() -> None:
    st.subheader("Dashboard")
    history = load_history()
    if not history:
        st.info("No runs yet. Start a crawl to see metrics here.")
        return

    c1, c2, c3, c4 = st.columns(4)
    total_runs = len(history)
    total_urls = sum(h.get("total", 0) for h in history)
    total_ok = sum(h.get("ok", 0) for h in history)
    total_fail = sum(h.get("fail", 0) for h in history)
    c1.metric("Total Runs", total_runs)
    c2.metric("URLs Crawled", total_urls)
    c3.metric("Succeeded", total_ok)
    c4.metric("Failed", total_fail)

    st.markdown("---")
    st.markdown("**Last 5 Runs**")
    for entry in history[:5]:
        ts = entry["timestamp"][:19]
        kind = entry.get("kind", "unknown")
        ok = entry.get("ok", 0)
        total = entry.get("total", 0)
        fail = entry.get("fail", 0)
        st.caption(f"{ts} | {kind} | {ok}/{total} OK | {fail} failed")


# ── Router ──

def main() -> None:
    st.set_page_config(page_title="Page Capture", layout="wide", page_icon=":material/center_focus_strong:")
    _init_session_state()

    pages = {
        "Capture": [
            st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:", default=True),
            st.Page(page_unified_crawl, title="Unified Crawl", icon=":material/rocket_launch:"),
            st.Page(page_screenshots, title="Screenshots", icon=":material/photo_camera:"),
            st.Page(page_extraction, title="Data Extraction", icon=":material/data_object:"),
        ],
        "Tools": [
            st.Page(page_import, title="Import URLs", icon=":material/input:"),
        ],
        "Library": [
            st.Page(page_history, title="History", icon=":material/history:"),
            st.Page(page_settings, title="Settings", icon=":material/settings:"),
        ],
    }

    with st.sidebar:
        st.title("Page Capture")
        st.caption("Screenshots, SEO extraction, custom rules.")

    pg = st.navigation(pages, position="sidebar")
    pg.run()


main()
