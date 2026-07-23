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
)
from state import register_runner, unregister_runner

CONFIG = load_config(HERE / "config.yaml")

# ── Crawl4AI Quick-Start Presets ─────────────────────────────────────────────
CRAWL_PRESETS = {
    "Just my URLs": {
        "max_depth": 0, "max_pages": 100,
        "strip_query_params": True, "respect_robots_txt": True,
        "include_patterns": "", "exclude_patterns": "",
        "allowed_domains": "", "blocked_domains": "",
    },
    "Crawl entire site": {
        "max_depth": 3, "max_pages": 1000,
        "strip_query_params": True, "respect_robots_txt": True,
        "include_patterns": "", "exclude_patterns": "",
        "allowed_domains": "", "blocked_domains": "",
    },
    "Blogs & articles": {
        "max_depth": 2, "max_pages": 500,
        "strip_query_params": True, "respect_robots_txt": True,
        "include_patterns": "/blog/\n/news/\n/article/",
        "exclude_patterns": "/tag/\n/author/\n?page=",
        "allowed_domains": "", "blocked_domains": "",
    },
    "Products & shop": {
        "max_depth": 2, "max_pages": 2000,
        "strip_query_params": True, "respect_robots_txt": True,
        "include_patterns": "/product/\n/item/\n/p/\n/category/",
        "exclude_patterns": "/cart\n/checkout\n/account\n?sort=",
        "allowed_domains": "", "blocked_domains": "",
    },
}


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
    dl_cols = st.columns(3)
    dl_idx = 0

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
    """Render collector toggles for SEO and Custom Rules."""
    collectors = st.session_state.newrun_collectors

    tc1, tc2 = st.columns(2)
    with tc1:
        collectors["seo"] = st.toggle(
            "SEO data",
            value=collectors.get("seo", True),
            key="newrun_do_seo",
            help="Title, meta, headings, OG tags, schema, word count, links, alt text.",
        )
    with tc2:
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


def _render_settings_panel() -> tuple[dict, str, dict, dict]:
    """Render settings panel, return (viewport, crawl_mode, crawl_config, fast_config)."""
    st.markdown("**Settings**")
    s1, s2 = st.columns(2)
    with s1:
        st.metric("Width", CONFIG["viewport"]["width"])
        st.number_input(
            "Delay (s)",
            value=CONFIG["timing"]["stabilization_ms"] / 1000,
            min_value=0.0,
            max_value=60.0,
            key="newrun_delay",
        )
    with s2:
        st.metric("Height", CONFIG["viewport"]["height"])
        output_name = st.text_input(
            "Folder name",
            value=st.session_state.newrun_output,
            key="newrun_output_name",
        )
        st.session_state.newrun_output = output_name

    crawl_mode = st.segmented_control(
        "Crawl mode",
        options=["unified", "fast", "crawl4ai"],
        default=st.session_state.get("newrun_crawl_mode", "fast"),
        key="newrun_crawl_mode",
        format_func=lambda x: {"unified": "Normal", "fast": "Fast", "crawl4ai": "Crawl4AI"}[x],
        help="Normal: SeleniumBase (SEO + extraction)\n"
             "Fast (default): curl_cffi (SEO only, 8 concurrent)\n"
             "Crawl4AI: Playwright async (SEO only, structured output)",
    ) or "fast"

    # Crawl4AI specific configuration panel
    crawl_config = {}
    fast_config = {}

    # Get seed URLs once for all modes (used for scope estimation)
    seed_urls = st.session_state.get("capture_urls", [])

    if crawl_mode == "crawl4ai":
        with st.container(border=True):
            st.markdown("**Crawl Settings**")

            # ── Quick Setup ──
            preset_names = list(CRAWL_PRESETS.keys())
            preset = st.selectbox(
                "Quick setup (you can still customize below):",
                ["Custom", *preset_names],
                key="newrun_crawl_preset",
                label_visibility="collapsed",
                help="Choose a preset to auto-fill the settings below, then tweak anything you like.",
            )
            if preset != "Custom":
                for k, v in CRAWL_PRESETS[preset].items():
                    st.session_state[f"newrun_{k}"] = v
                st.session_state.pop("newrun_crawl_preset", None)
                st.rerun()

            # ── Settings Grid ──
            cc1, cc2 = st.columns(2)
            with cc1:
                depth = st.session_state.get("newrun_max_depth", CONFIG["crawl4ai"]["max_depth"])
                st.number_input(
                    "🔗 How many links to follow",
                    min_value=0, max_value=10, value=depth,
                    key="newrun_max_depth",
                    help="0 = Only scan the URLs you entered. "
                         "1 = Also scan links found on those pages. "
                         "2 = Also scan links found on those pages, and so on.",
                )
                depth_label = {0: "🔵 Just your URLs", 1: "🟡 One level deep",
                               2: "🟠 Two levels deep"}.get(depth, "🔴 Deep crawl (many pages)")
                st.caption(depth_label)

                st.number_input(
                    "📄 Maximum pages to scan",
                    min_value=1, max_value=100000,
                    value=st.session_state.get("newrun_max_pages", CONFIG["crawl4ai"]["max_pages"]),
                    key="newrun_max_pages",
                    help="Safety limit to prevent accidentally scanning too many pages.",
                )

                if depth > 2:
                    st.warning("Following links 3+ levels deep can scan thousands of pages and may take a long time.")
                if st.session_state.get("newrun_max_pages", CONFIG["crawl4ai"]["max_pages"]) > 5000:
                    st.warning("Scanning over 5,000 pages can get your IP blocked by some websites. Increase only if needed.")

                st.toggle(
                    "🧹 Ignore tracking codes (?utm_source=, ?ref=, etc.)",
                    value=st.session_state.get("newrun_strip_query_params", CONFIG["crawl4ai"]["strip_query_params"]),
                    key="newrun_strip_query_params",
                    help="Removes things like ?utm_source=facebook so pages with different tracking codes aren't scanned twice.",
                )
                st.toggle(
                    "🤖 Follow site crawling rules (recommended)",
                    value=st.session_state.get("newrun_respect_robots_txt", CONFIG["crawl4ai"]["respect_robots_txt"]),
                    key="newrun_respect_robots_txt",
                    help="Most websites have a 'robots.txt' file that tells crawlers which pages to skip. "
                         "Enabling this is polite and helps avoid being blocked.",
                )

                st.text_area(
                    "✅ Only scan URLs containing...",
                    value="\n".join(st.session_state.get("newrun_include_patterns", CONFIG["crawl4ai"]["include_patterns"])),
                    key="newrun_include_patterns",
                    help="One per line. Only pages whose web address contains these words will be scanned. "
                         "Leave empty to scan all URLs.\n\n"
                         "Example:\n  /blog/\n  /news/",
                    height=80,
                )
                st.text_area(
                    "❌ Skip URLs containing...",
                    value="\n".join(st.session_state.get("newrun_exclude_patterns", CONFIG["crawl4ai"]["exclude_patterns"])),
                    key="newrun_exclude_patterns",
                    help="One per line. Pages whose web address contains these words will be skipped.\n\n"
                         "Example:\n  /tag/\n  ?page=",
                    height=80,
                )

            with cc2:
                if seed_urls:
                    from urllib.parse import urlparse as _urlparse
                    detected = set()
                    for u in seed_urls:
                        try:
                            detected.add(_urlparse(u).netloc)
                        except Exception:
                            pass
                    if detected:
                        st.caption(f"Detected website(s): {', '.join(sorted(detected))}")

                st.text_area(
                    "🌐 Stay on these websites only",
                    value="\n".join(st.session_state.get("newrun_allowed_domains", CONFIG["crawl4ai"]["allowed_domains"])),
                    key="newrun_allowed_domains",
                    help="One domain per line. Only pages from these websites will be scanned.\n"
                         "Leave empty to automatically stay on the same website(s) as your starting URLs.\n\n"
                         "Example:\n  example.com\n  blog.example.com",
                    height=80,
                )
                st.text_area(
                    "🚫 Skip these websites",
                    value="\n".join(st.session_state.get("newrun_blocked_domains", CONFIG["crawl4ai"]["blocked_domains"])),
                    key="newrun_blocked_domains",
                    help="One domain per line. Pages from these websites will never be scanned.\n\n"
                         "Example:\n  facebook.com\n  twitter.com",
                    height=80,
                )

                raw_allowed = st.session_state.get("newrun_allowed_domains", "")
                if not raw_allowed.strip() and depth > 0:
                    st.info("ℹ️ We'll automatically stay on the same website(s) as your starting URLs.")

            # ── Scope Estimate ──
            st.markdown("---")
            url_count = len(seed_urls)
            if url_count == 0:
                st.info("Add URLs above to see an estimate of how many pages will be scanned.")
            else:
                if depth == 0:
                    estimated = url_count
                elif depth == 1:
                    estimated = min(url_count * 10, 10000)
                elif depth == 2:
                    estimated = min(url_count * 50, 50000)
                else:
                    estimated = min(url_count * (10 ** depth), 100000)
                max_p = st.session_state.get("newrun_max_pages", CONFIG["crawl4ai"]["max_pages"])
                estimated = min(estimated, max_p)

                secs = estimated * 2
                if secs < 60:
                    time_str = f"~{int(secs)} sec"
                elif secs < 3600:
                    time_str = f"~{int(secs // 60)} min"
                else:
                    time_str = f"~{secs / 3600:.1f} hr"

                st.caption(f"📊 Estimated: **{estimated} page(s)** | {time_str}")

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

    # Fast mode specific configuration panel
    fast_config = {}
    if crawl_mode == "fast":
        with st.container(border=True):
            st.markdown("**Fast Mode Settings**")

            fc1, fc2 = st.columns(2)
            with fc1:
                st.number_input(
                    "🔁 Max retries",
                    min_value=0, max_value=10, value=st.session_state.get("newrun_max_retries", CONFIG["fast"]["max_retries"]),
                    key="newrun_max_retries",
                    help="Number of retry attempts for failed URLs (rate limits, server errors)."
                )
                st.text_input(
                    "🔢 Retry on HTTP status codes",
                    value=st.session_state.get("newrun_retry_on_status", CONFIG["fast"]["retry_on_status"]),
                    key="newrun_retry_on_status",
                    help="Comma-separated HTTP status codes to retry (e.g., 429,500,502,503,504). 404/403 are not retried by default."
                )
            with fc2:
                st.number_input(
                    "⚡ Max concurrent workers",
                    min_value=1, max_value=32, value=st.session_state.get("newrun_max_workers", CONFIG["fast"]["max_workers"]),
                    key="newrun_max_workers",
                    help="Maximum number of concurrent requests."
                )
                st.number_input(
                    "⏱️ Request timeout (seconds)",
                    min_value=5, max_value=120, value=st.session_state.get("newrun_timeout", CONFIG["fast"]["timeout"]),
                    key="newrun_timeout",
                    help="Timeout for each HTTP request in seconds."
                )

            raw_retry = st.session_state.get("newrun_retry_on_status", CONFIG["fast"]["retry_on_status"])
            fast_config = {
                "max_retries": st.session_state.get("newrun_max_retries", CONFIG["fast"]["max_retries"]),
                "retry_on_status": [int(x.strip()) for x in raw_retry.split(",") if x.strip().isdigit()] if raw_retry else [],
                "max_workers": st.session_state.get("newrun_max_workers", CONFIG["fast"]["max_workers"]),
                "timeout": st.session_state.get("newrun_timeout", CONFIG["fast"]["timeout"]),
            }

    viewport = {"width": int(CONFIG["viewport"]["width"]), "height": int(CONFIG["viewport"]["height"])}
    return viewport, crawl_mode, crawl_config, fast_config


def _render_run_button(existing_urls: list[str], collectors: dict[str, bool], crawl_config: dict | None = None, fast_config: dict | None = None) -> None:
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
            viewport={"width": int(CONFIG["viewport"]["width"]), "height": int(CONFIG["viewport"]["height"])},
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
            fc = fast_config or {}
            runner = FastRunnerLegacy(
                existing_urls,
                runtime_cfg,
                output_dir,
                seo_fields=st.session_state.get("newrun_seo_fields_enabled"),
                max_retries=fc.get("max_retries", 3),
                retry_on_status=fc.get("retry_on_status", [429, 500, 502, 503, 504]),
                max_workers=fc.get("max_workers", 8),
                timeout=fc.get("timeout", 30.0),
            )
        else:
            collector_list: list[dict] = []
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
            )

        st.session_state.unified_runner = runner
        st.session_state.unified_running = True
        register_runner(runner)
        st.rerun()


def page_new_run() -> None:
    st.subheader("New Capture")

    for key, default in [
        ("newrun_collectors", {"seo": True, "extraction": False}),
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
        restore_fast_mode = st.session_state.pop("restore_fast_mode", None)
        if restore_fast_mode:
            st.session_state.newrun_crawl_mode = "fast"
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
            st.markdown("### Settings")
            viewport, crawl_mode, crawl_config, fast_config = _render_settings_panel()

            st.markdown("---")
            _render_run_button(existing_urls, st.session_state.newrun_collectors, crawl_config, fast_config)
