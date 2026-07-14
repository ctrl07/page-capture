"""Unified Capture page — import, configure, run, monitor, results."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

import streamlit as st

from components.progress import run_with_progress
from components.results_viewer import render_unified_results
from extraction import get_standard_seo_fields, render_seo_fields_selector
from importers import (
    import_from_csv_file,
    import_from_sitemap_url,
    import_from_wp_xml,
    parse_urls_text,
)
from page_capture import load_config
from runners import (
    HERE,
    FastRunner,
    UnifiedRunner,
    build_runtime_config,
    build_zip,
)
from state import register_runner, unregister_runner

CONFIG = load_config(HERE / "config.yaml")


def _render_active_run() -> None:
    """Show the currently running job with live progress."""
    runner = st.session_state.unified_runner
    st.info(f"Running — **{runner.status}**")
    run_with_progress(runner, "newrun")
    st.session_state.unified_running = False
    st.session_state.newrun_just_finished = True
    unregister_runner(runner)
    st.rerun()


def _render_run_complete(runner) -> None:
    """Show completed run results with prominent download buttons."""
    st.session_state.newrun_just_finished = False

    # Support both UnifiedRunner (results dict) and FastRunner (results["seo"])
    results_by_collector: dict[str, list[dict]] = {}
    if hasattr(runner, "results"):
        if isinstance(runner.results, dict):
            results_by_collector = runner.results
        else:
            results_by_collector = {"seo": runner.results}

    ok = sum(
        1 for rows in results_by_collector.values() for r in rows if r.get("status") == "ok"
    )
    total = sum(len(rows) for rows in results_by_collector.values())
    failed = total - ok

    collectors = getattr(runner, "collectors", [{"name": "seo"}])

    # Big metrics row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("URLs", len(runner.urls))
    m2.metric("Passed", ok)
    m3.metric("Failed", failed)
    m4.metric("Collectors", len(collectors))

    st.markdown("---")

    # ── Download buttons — front and center ──
    st.markdown("### Download Results")
    dl_cols = st.columns(4)
    dl_idx = 0

    if results_by_collector.get("screenshot"):
        with dl_cols[dl_idx]:
            zip_data = build_zip(results_by_collector["screenshot"], runner.output_dir)
            st.download_button(
                "Screenshots ZIP",
                data=zip_data,
                file_name="screenshots.zip",
                mime="application/zip",
                key="newrun_dl_zip",
                width="stretch",
                type="primary",
            )
        dl_idx += 1

    if results_by_collector.get("seo"):
        with dl_cols[dl_idx]:
            all_keys = list(dict.fromkeys(k for r in results_by_collector["seo"] for k in r))
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results_by_collector["seo"])
            st.download_button(
                "SEO CSV",
                data=csv_buf.getvalue().encode(),
                file_name="seo_results.csv",
                mime="text/csv",
                key="newrun_dl_seo_csv",
                width="stretch",
                type="primary",
            )
        dl_idx += 1

    if results_by_collector.get("extraction"):
        with dl_cols[dl_idx]:
            all_keys = list(dict.fromkeys(k for r in results_by_collector["extraction"] for k in r))
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results_by_collector["extraction"])
            st.download_button(
                "Extraction CSV",
                data=csv_buf.getvalue().encode(),
                file_name="extraction_results.csv",
                mime="text/csv",
                key="newrun_dl_ext_csv",
                width="stretch",
                type="primary",
            )
        dl_idx += 1

    # SEO Analysis CTA
    if results_by_collector.get("seo"):
        st.markdown("---")
        st.markdown("**SEO Analysis**")
        st.caption("Run a full SEO health check on these results.")
        if st.button("Open SEO Analysis", key="newrun_open_analysis", type="secondary", width="stretch"):
            st.session_state["_navigate_to_seo_analysis"] = True
            st.rerun()

    # Output folder
    st.caption(f"Output saved to: `{runner.output_dir}`")

    st.markdown("---")

    # ── Detailed results by collector ──
    render_unified_results(runner, key_prefix="newrun_")

    # Run again
    st.markdown("---")
    if st.button("Capture Again", key="newrun_run_again"):
        st.session_state.newrun_just_finished = False
        st.rerun()


def page_new_run() -> None:
    st.subheader("New Capture")

    for key, default in [
        ("newrun_collectors", {"screenshot": True, "seo": True, "extraction": False}),
        ("newrun_output", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # ── Restore from dashboard re-run ──
    if st.session_state.get("_newrun_from_dashboard"):
        st.session_state.pop("newrun_just_finished", None)
        st.session_state.pop("_newrun_from_dashboard", None)
        restore = st.session_state.pop("restore_collectors", None)
        if restore and isinstance(restore, list):
            collectors_dict = st.session_state.newrun_collectors
            for name in collectors_dict:
                collectors_dict[name] = name in restore
            st.session_state.newrun_collectors = collectors_dict
        restore_rules = st.session_state.pop("restore_extraction_rules", None)
        if restore_rules:
            st.session_state.extraction_rules = restore_rules
        restore_fast = st.session_state.pop("restore_fast_mode", None)
        if restore_fast:
            st.session_state.newrun_fast_mode = True

    # ── If a run is active or just finished, show it full-width ──
    if st.session_state.unified_running and st.session_state.unified_runner:
        _render_active_run()
        return
    if st.session_state.get("newrun_just_finished"):
        runner = st.session_state.unified_runner
        _render_run_complete(runner)
        return

    # ── Setup form: everything on one page ──
    collectors = st.session_state.newrun_collectors

    # URL input — the most important thing
    existing_urls = st.session_state.get("capture_urls") or []
    url_count = len(existing_urls)

    url_source = st.radio(
        "URL source",
        ["Paste URLs", "Sitemap", "CSV upload", "WordPress XML"],
        horizontal=True, key="newrun_url_source",
        label_visibility="collapsed",
    )

    imported_urls: list[str] = []
    if url_source == "Paste URLs":
        raw = st.text_area(
            "URLs (one per line)", height=140,
            placeholder="https://example.com\nhttps://example.com/about\nhttps://example.com/contact",
            key="newrun_paste",
        )
        if raw:
            imported_urls = parse_urls_text(raw)
    elif url_source == "Sitemap":
        sm_col1, sm_col2 = st.columns([3, 1])
        with sm_col1:
            sm_url = st.text_input("Sitemap URL", placeholder="https://example.com/sitemap.xml", key="newrun_sm", label_visibility="collapsed")
        with sm_col2:
            if sm_url and st.button("Fetch", key="newrun_sm_fetch"):
                with st.spinner("Fetching..."):
                    try:
                        imported_urls = import_from_sitemap_url(sm_url)
                        st.success(f"Found {len(imported_urls)} URLs")
                    except Exception as e:
                        st.error(f"Failed: {e}")
    elif url_source == "CSV upload":
        uploaded = st.file_uploader("Upload CSV", type=["csv", "txt"], key="newrun_csv", label_visibility="collapsed")
        if uploaded:
            raw = uploaded.read().decode("utf-8", errors="replace")
            pairs = import_from_csv_file(raw)
            if pairs:
                imported_urls = [a for a, _ in pairs]
                st.success(f"Found {len(imported_urls)} URLs from CSV")
            else:
                st.error("No valid URLs found in CSV")
    elif url_source == "WordPress XML":
        uploaded = st.file_uploader("Upload WordPress XML", type=["xml"], key="newrun_wp", label_visibility="collapsed")
        if uploaded:
            raw = uploaded.read()
            try:
                posts = import_from_wp_xml(raw)
                imported_urls = [p["url"] for p in posts]
                st.success(f"Found {len(imported_urls)} posts/pages")
            except Exception as e:
                st.error(f"Failed: {e}")

    # Merge imported into queue
    if imported_urls:
        if st.button(f"Add {len(imported_urls)} URL(s) to queue", key="newrun_add_urls", type="secondary"):
            merged = list(dict.fromkeys(existing_urls + imported_urls))
            st.session_state.capture_urls = merged
            st.rerun()

    # Show current queue
    if url_count:
        st.success(f"**{url_count}** URL(s) in queue")
        with st.expander("View URLs", expanded=False):
            for u in existing_urls[:100]:
                st.text(u)
            if url_count > 100:
                st.caption(f"... and {url_count - 100} more")
        c1, c2, _ = st.columns([1, 1, 4])
        with c1:
            if st.button("Clear queue", key="newrun_clear"):
                st.session_state.capture_urls = []
                st.rerun()
    elif not imported_urls:
        st.info("Paste URLs above, or import from a sitemap/CSV/WordPress XML.")

    st.markdown("---")

    # Collectors + settings in a compact row
    col_collect, col_settings = st.columns([1, 1])
    with col_collect:
        st.markdown("**Collectors**")
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            collectors["screenshot"] = st.checkbox("Screenshots", value=collectors.get("screenshot", True), key="newrun_do_ss")
        with cc2:
            collectors["seo"] = st.checkbox("SEO data", value=collectors.get("seo", True), key="newrun_do_seo",
                help="Title, meta, headings, OG tags, schema, word count, links, alt text.")
        with cc3:
            collectors["extraction"] = st.checkbox("Custom rules", value=collectors.get("extraction", False), key="newrun_do_ext")
        st.session_state.newrun_collectors = collectors

        if collectors["extraction"]:
            rules = st.session_state.get("extraction_rules", [])
            if not rules:
                st.warning("No extraction rules loaded. Go to **Rule Sets** first.")

        if collectors["seo"]:
            with st.expander("Configure SEO fields", expanded=False):
                seo_fields = render_seo_fields_selector(key_prefix="newrun_seo_fields")
            st.session_state["newrun_seo_fields_enabled"] = seo_fields
        else:
            st.session_state["newrun_seo_fields_enabled"] = get_standard_seo_fields()

    with col_settings:
        st.markdown("**Settings**")
        s1, s2 = st.columns(2)
        with s1:
            ss_width = st.number_input("Width", value=CONFIG["viewport"]["width"], min_value=320, max_value=3840, key="newrun_width")
            ss_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="newrun_delay")
        with s2:
            ss_height = st.number_input("Height", value=CONFIG["viewport"]["height"], min_value=320, max_value=2160, key="newrun_height")
            output_name = st.text_input("Folder name", value=st.session_state.newrun_output, key="newrun_output_name")
            st.session_state.newrun_output = output_name

        fast_mode = st.checkbox(
            "Fast mode (curl_cffi)",
            value=st.session_state.get("newrun_fast_mode", False),
            key="newrun_fast_mode",
            help="Crawl SEO data via curl_cffi (8 concurrent) after solving Turnstile once. Faster but no screenshots.",
        )
        if fast_mode:
            st.info("Screenshots disabled in fast mode — use SEO / Custom Rules collectors only.")
            collectors["screenshot"] = False

        generate_pdf = st.checkbox(
            "Generate PDFs",
            value=st.session_state.get("newrun_generate_pdf", False),
            key="newrun_generate_pdf",
            help="Convert each screenshot PNG to a lossless PDF alongside it.",
        )
        if generate_pdf and not collectors.get("screenshot"):
            st.warning("PDFs require screenshots — enable the Screenshots collector.")
            generate_pdf = False

    st.markdown("---")

    # Run button — prominent
    active_collectors = [k for k, v in collectors.items() if v]
    can_run = existing_urls and active_collectors
    btn_disabled = st.session_state.unified_running or not can_run

    reasons = []
    if not existing_urls:
        reasons.append("add URLs")
    if not active_collectors:
        reasons.append("select a collector")
    if collectors.get("extraction") and not st.session_state.get("extraction_rules"):
        reasons.append("load extraction rules")

    if reasons:
        st.caption(f"To start: {', '.join(reasons)}")

    if st.button("Start Capture", disabled=btn_disabled, type="primary", key="newrun_start", width="stretch"):
        safe_name = re.sub(r"[^\w\-]", "_", output_name.strip())
        output_dir = HERE / safe_name
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_cfg = build_runtime_config(
            CONFIG,
            viewport={"width": int(ss_width), "height": int(ss_height)},
            stabilization_ms=int(ss_delay * 1000),
        )

        fast_mode = st.session_state.get("newrun_fast_mode", False)

        if fast_mode:
            # Fast mode: FastRunner for SEO (no screenshots)
            runner = FastRunner(
                existing_urls, runtime_cfg, output_dir,
                seo_fields=st.session_state.get("newrun_seo_fields_enabled"),
            )
        else:
            # Standard mode: UnifiedRunner with browser
            collector_list: list[dict] = []
            if collectors["screenshot"]:
                collector_list.append({"name": "screenshot", "rules": None})
            if collectors["seo"]:
                collector_list.append({"name": "seo", "rules": None})
            if collectors["extraction"]:
                collector_list.append({"name": "extraction", "rules": st.session_state.get("extraction_rules", [])})

            runner = UnifiedRunner(existing_urls, collector_list, runtime_cfg, output_dir,
                                   seo_fields=st.session_state.get("newrun_seo_fields_enabled"),
                                   generate_pdf=st.session_state.get("newrun_generate_pdf", False))
        st.session_state.unified_runner = runner
        st.session_state.unified_running = True
        register_runner(runner)
        st.rerun()
