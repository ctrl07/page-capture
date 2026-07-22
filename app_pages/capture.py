"""Page Capture — New capture workflow with split layout."""
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
    import_from_sitemap_url,
    import_from_wp_xml,
    parse_urls_text,
)
from page_capture import load_config
from runners import (
    HERE,
    Crawl4AIRunner,
    FastRunnerLegacy,
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

    with st.container(horizontal=True):
        st.metric("URLs", len(runner.urls), border=True)
        st.metric("Passed", ok, border=True)
        st.metric("Failed", failed, border=True)
        st.metric("Collectors", len(collectors), border=True)

    st.markdown("---")

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

    if results_by_collector.get("seo"):
        st.markdown("---")
        st.markdown("**SEO Analysis**")
        st.caption("Run a full SEO health check on these results.")
        if st.button("Open SEO Analysis", key="newrun_open_analysis", type="secondary", width="stretch"):
            st.session_state["_navigate_to_seo_analysis"] = True
            st.rerun()

    st.caption(f"Output saved to: `{runner.output_dir}`")

    st.markdown("---")

    render_unified_results(runner, key_prefix="newrun_")

    st.markdown("---")
    if st.button("Capture Again", key="newrun_run_again"):
        st.session_state.newrun_just_finished = False
        st.rerun()


def _render_url_source_panel() -> list[str]:
    """Render URL input panel, return list of imported URLs."""
    existing_urls = st.session_state.get("capture_urls") or []
    url_count = len(existing_urls)

    url_source = st.radio(
        "URL source",
        ["Paste URLs", "Sitemap", "WordPress XML"],
        horizontal=True,
        key="newrun_url_source",
        label_visibility="collapsed",
    )

    imported_urls: list[str] = []

    if url_source == "Paste URLs":
        raw = st.text_area(
            "URLs (one per line)",
            height=140,
            placeholder="https://example.com\nhttps://example.com/about\nhttps://example.com/contact",
            key="newrun_paste",
        )
        if raw:
            imported_urls = parse_urls_text(raw)

    elif url_source == "Sitemap":
        sm_col1, sm_col2 = st.columns([3, 1])
        with sm_col1:
            sm_url = st.text_input(
                "Sitemap URL",
                placeholder="https://example.com/sitemap.xml",
                key="newrun_sm",
                label_visibility="collapsed",
            )
        with sm_col2:
            if sm_url and st.button("Fetch", key="newrun_sm_fetch", width="stretch"):
                with st.spinner("Fetching..."):
                    try:
                        imported_urls = import_from_sitemap_url(sm_url)
                        st.success(f"Found {len(imported_urls)} URLs")
                    except Exception as e:
                        st.error(f"Failed: {e}")

    elif url_source == "WordPress XML":
        uploaded = st.file_uploader(
            "Upload WordPress XML",
            type=["xml"],
            key="newrun_wp",
            label_visibility="collapsed",
        )
        if uploaded:
            raw = uploaded.read()
            try:
                posts = import_from_wp_xml(raw)
                imported_urls = [p["url"] for p in posts]
                st.success(f"Found {len(imported_urls)} posts/pages")
            except Exception as e:
                st.error(f"Failed: {e}")

    if imported_urls:
        if st.button(f"Add {len(imported_urls)} URL(s) to queue", key="newrun_add_urls", type="secondary", width="stretch"):
            merged = list(dict.fromkeys(existing_urls + imported_urls))
            st.session_state.capture_urls = merged
            st.rerun()

    if url_count:
        st.success(f"**{url_count}** URL(s) in queue")
        view_exp = st.expander("View URLs", expanded=False)
        if view_exp.open:
            with view_exp:
                for u in existing_urls[:100]:
                    st.text(u)
                if url_count > 100:
                    st.caption(f"... and {url_count - 100} more")
        if st.button("Clear queue", key="newrun_clear"):
            st.session_state.capture_urls = []
            st.rerun()
    elif not imported_urls:
        st.info("Paste URLs above, or import from a sitemap or WordPress XML.")

    return existing_urls


def _render_collectors_panel() -> dict[str, bool]:
    """Render collector toggles for SEO and Custom Rules (Screenshots is separate)."""
    collectors = st.session_state.newrun_collectors

    with st.container(horizontal=True, gap="small"):
        collectors["seo"] = st.toggle(
            "SEO data",
            value=collectors.get("seo", True),
            key="newrun_do_seo",
            help="Title, meta, headings, OG tags, schema, word count, links, alt text.",
        )
        collectors["extraction"] = st.toggle(
            "Custom rules",
            value=collectors.get("extraction", False),
            key="newrun_do_ext",
        )

    st.session_state.newrun_collectors = collectors

    if collectors["extraction"]:
        rules = st.session_state.get("extraction_rules", [])
        if not rules:
            st.warning("No extraction rules loaded. Go to **Rule Sets** first.")

    if collectors["seo"]:
        seo_exp = st.expander("Configure SEO fields", expanded=False, on_change="rerun")
        if seo_exp.open:
            with seo_exp:
                render_seo_fields_selector(key_prefix="newrun_seo_fields")
    else:
        st.session_state["newrun_seo_fields_enabled"] = get_standard_seo_fields()

    return collectors


def _render_screenshot_section() -> None:
    """Render screenshot toggle with PDF option in its own section."""
    collectors = st.session_state.newrun_collectors
    st.markdown("**Screenshots**")

    col_ss, col_pdf = st.columns(2)
    with col_ss:
        collectors["screenshot"] = st.toggle(
            "Capture",
            value=collectors.get("screenshot", True),
            key="newrun_do_ss",
        )
    with col_pdf:
        generate_pdf = st.toggle(
            "Generate PDFs",
            value=st.session_state.get("newrun_generate_pdf", False),
            key="newrun_generate_pdf",
            help="Convert each screenshot PNG to a lossless PDF alongside it.",
        )

    st.session_state.newrun_collectors = collectors

    if generate_pdf and not collectors.get("screenshot"):
        st.warning("PDFs require screenshots — enable the Screenshots collector.")


def _render_settings_panel() -> tuple[dict, str, dict]:
    """Render settings panel, return (viewport, crawl_mode, crawl_config)."""
    st.markdown("**Settings**")
    s1, s2 = st.columns(2)
    with s1:
        ss_width = st.number_input(
            "Width",
            value=CONFIG["viewport"]["width"],
            min_value=320,
            max_value=3840,
            key="newrun_width",
        )
        st.number_input(
            "Delay (s)",
            value=CONFIG["timing"]["stabilization_ms"] / 1000,
            min_value=0.0,
            max_value=60.0,
            key="newrun_delay",
        )
    with s2:
        ss_height = st.number_input(
            "Height",
            value=CONFIG["viewport"]["height"],
            min_value=320,
            max_value=2160,
            key="newrun_height",
        )
        output_name = st.text_input(
            "Folder name",
            value=st.session_state.newrun_output,
            key="newrun_output_name",
        )
        st.session_state.newrun_output = output_name

    crawl_mode = st.segmented_control(
        "Crawl mode",
        options=["unified", "fast", "crawl4ai"],
        default=st.session_state.get("newrun_crawl_mode", "unified"),
        key="newrun_crawl_mode",
        format_func=lambda x: {"unified": "Normal", "fast": "Fast", "crawl4ai": "Crawl4AI"}[x],
        help="Normal: SeleniumBase (screenshots + SEO + extraction)\n"
             "Fast: curl_cffi (SEO only, 8 concurrent)\n"
             "Crawl4AI: Playwright async (SEO only, structured output)",
    )

    # Disable screenshot collector for fast modes
    if crawl_mode in ("Fast", "Crawl4AI"):
        st.info("Screenshots disabled in Fast/Crawl4AI modes — use SEO / Custom Rules collectors only.")
        collectors = st.session_state.newrun_collectors
        collectors["screenshot"] = False
        st.session_state.newrun_collectors = collectors

    # Crawl4AI specific configuration panel
    crawl_config = {}
    if crawl_mode == "crawl4ai":
        crawl_exp = st.expander("Crawl4AI Configuration", expanded=True, on_change="rerun")
        if crawl_exp.open:
            with crawl_exp:
                cc1, cc2 = st.columns(2)
                with cc1:
                    st.number_input(
                        "Max Depth",
                        min_value=0,
                        max_value=10,
                        value=st.session_state.get("newrun_max_depth", CONFIG["crawl4ai"]["max_depth"]),
                        key="newrun_max_depth",
                        help="0 = initial URLs only, 1+ = follow links up to N hops",
                    )
                    st.number_input(
                        "Max Pages",
                        min_value=1,
                        max_value=10000,
                        value=st.session_state.get("newrun_max_pages", CONFIG["crawl4ai"]["max_pages"]),
                        key="newrun_max_pages",
                        help="Maximum total pages to crawl (safety limit)",
                    )
                    st.toggle(
                        "Strip Query Parameters",
                        value=st.session_state.get("newrun_strip_query_params", CONFIG["crawl4ai"]["strip_query_params"]),
                        key="newrun_strip_query_params",
                        help="Remove URL parameters before deduplication",
                    )
                    st.toggle(
                        "Respect Robots.txt",
                        value=st.session_state.get("newrun_respect_robots_txt", CONFIG["crawl4ai"]["respect_robots_txt"]),
                        key="newrun_respect_robots_txt",
                        help="Check and obey robots.txt rules",
                    )
                with cc2:
                    st.text_area(
                        "Include Patterns (regex)",
                        value="\n".join(st.session_state.get("newrun_include_patterns", CONFIG["crawl4ai"]["include_patterns"])),
                        key="newrun_include_patterns",
                        help="Only crawl URLs matching these patterns (one per line)",
                        height=70,
                    )
                    st.text_area(
                        "Exclude Patterns (regex)",
                        value="\n".join(st.session_state.get("newrun_exclude_patterns", CONFIG["crawl4ai"]["exclude_patterns"])),
                        key="newrun_exclude_patterns",
                        help="Skip URLs matching these patterns (one per line)",
                        height=70,
                    )
                    st.text_area(
                        "Allowed Domains",
                        value="\n".join(st.session_state.get("newrun_allowed_domains", CONFIG["crawl4ai"]["allowed_domains"])),
                        key="newrun_allowed_domains",
                        help="Only crawl URLs from these domains (one per line)",
                        height=70,
                    )
                    st.text_area(
                        "Blocked Domains",
                        value="\n".join(st.session_state.get("newrun_blocked_domains", CONFIG["crawl4ai"]["blocked_domains"])),
                        key="newrun_blocked_domains",
                        help="Skip URLs from these domains (one per line)",
                        height=70,
                    )

                raw_include = st.session_state.get("newrun_include_patterns", "")
                raw_exclude = st.session_state.get("newrun_exclude_patterns", "")
                raw_allowed = st.session_state.get("newrun_allowed_domains", "")
                raw_blocked = st.session_state.get("newrun_blocked_domains", "")

                crawl_config = {
                    "max_depth": st.session_state.get("newrun_max_depth", CONFIG["crawl4ai"]["max_depth"]),
                    "max_pages": st.session_state.get("newrun_max_pages", CONFIG["crawl4ai"]["max_pages"]),
                    "include_patterns": [p.strip() for p in raw_include.split("\n") if p.strip()] if raw_include else [],
                    "exclude_patterns": [p.strip() for p in raw_exclude.split("\n") if p.strip()] if raw_exclude else [],
                    "strip_query_params": st.session_state.get("newrun_strip_query_params", CONFIG["crawl4ai"]["strip_query_params"]),
                    "respect_robots_txt": st.session_state.get("newrun_respect_robots_txt", CONFIG["crawl4ai"]["respect_robots_txt"]),
                    "allowed_domains": [d.strip() for d in raw_allowed.split("\n") if d.strip()] if raw_allowed else [],
                    "blocked_domains": [d.strip() for d in raw_blocked.split("\n") if d.strip()] if raw_blocked else [],
                }

    viewport = {"width": int(ss_width), "height": int(ss_height)}
    return viewport, crawl_mode, crawl_config


def _render_run_button(existing_urls: list[str], collectors: dict[str, bool], crawl_config: dict | None = None) -> None:
    """Render the primary run button with validation."""
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

    crawl_mode = st.session_state.get("newrun_crawl_mode", "unified")

    if st.button(
        "Start Capture",
        disabled=btn_disabled,
        type="primary",
        key="newrun_start",
        width="stretch",
    ):
        safe_name = re.sub(r"[^\w\-]", "_", st.session_state.newrun_output.strip())
        output_dir = HERE / safe_name
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_cfg = build_runtime_config(
            CONFIG,
            viewport={"width": int(st.session_state.newrun_width), "height": int(st.session_state.newrun_height)},
            stabilization_ms=int(st.session_state.newrun_delay * 1000),
        )

        if crawl_mode == "crawl4ai":
            runner = Crawl4AIRunner(
                existing_urls,
                runtime_cfg,
                output_dir,
                seo_fields=st.session_state.get("newrun_seo_fields_enabled"),
                crawl_config=crawl_config or {},
            )
        elif crawl_mode == "fast":
            runner = FastRunnerLegacy(
                existing_urls,
                runtime_cfg,
                output_dir,
                seo_fields=st.session_state.get("newrun_seo_fields_enabled"),
            )
        else:
            collector_list: list[dict] = []
            if collectors["screenshot"]:
                collector_list.append({"name": "screenshot", "rules": None})
            if collectors["seo"]:
                collector_list.append({"name": "seo", "rules": None})
            if collectors["extraction"]:
                collector_list.append({"name": "extraction", "rules": st.session_state.get("extraction_rules", [])})

            runner = UnifiedRunner(
                existing_urls,
                collector_list,
                runtime_cfg,
                output_dir,
                seo_fields=st.session_state.get("newrun_seo_fields_enabled"),
                generate_pdf=st.session_state.get("newrun_generate_pdf", False),
            )

        st.session_state.unified_runner = runner
        st.session_state.unified_running = True
        register_runner(runner)
        st.rerun()


def page_new_run() -> None:
    st.subheader("New Capture")

    for key, default in [
        ("newrun_collectors", {"screenshot": False, "seo": True, "extraction": False}),
        ("newrun_output", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

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
        restore_crawl_mode = st.session_state.pop("restore_crawl_mode", None)
        if restore_crawl_mode:
            st.session_state.newrun_crawl_mode = restore_crawl_mode
        restore_crawl_config = st.session_state.pop("restore_crawl_config", None)
        if restore_crawl_config and isinstance(restore_crawl_config, dict):
            for k, v in restore_crawl_config.items():
                skey = f"newrun_{k}"
                st.session_state[skey] = v

    if st.session_state.unified_running and st.session_state.unified_runner:
        _render_active_run()
        return
    if st.session_state.get("newrun_just_finished"):
        runner = st.session_state.unified_runner
        _render_run_complete(runner)
        return

    left, right = st.columns([1, 1], gap="large")

    with left:
        with st.container(border=True):
            st.markdown("### URLs")
            existing_urls = _render_url_source_panel()

    with right:
        with st.container(border=True):
            st.markdown("### Collectors")
            _render_collectors_panel()

            st.markdown("---")
            _render_screenshot_section()

            st.markdown("---")
            st.markdown("### Settings")
            viewport, crawl_mode, crawl_config = _render_settings_panel()

            st.markdown("---")
            _render_run_button(existing_urls, st.session_state.newrun_collectors, crawl_config)
