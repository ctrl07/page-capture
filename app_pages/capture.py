"""Page Capture — New capture workflow with 4-step wizard."""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from multiprocessing import cpu_count

import streamlit as st

from components.progress import run_with_progress
from components.results_viewer import render_unified_results
from extraction import get_standard_seo_fields, render_seo_fields_selector
from importers import (
    import_from_csv_file,
    parse_urls_text,
)
from page_capture import load_config
from runners import (
    HERE,
    FastRunnerLegacy,
    UnifiedRunner,
    build_runtime_config,
)
from state import register_runner, unregister_runner

CONFIG = load_config(HERE / "config.yaml")

# ── Fast Crawl Quick-Start Presets ─────────────────────────────────────────────
FAST_CRAWL_PRESETS = {
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


def _smart_crawl_mode(urls: list[str]) -> str:
    """Auto-select crawl mode based on URL count."""
    if len(urls) <= 10:
        return "fast"
    return "unified"


def _smart_fast_workers() -> int:
    """Auto-detect optimal worker count."""
    return min(8, max(4, cpu_count()))


def _smart_output_name() -> str:
    """Generate smart output folder name."""
    return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


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
        if st.button("Open SEO Health", key="newrun_open_analysis", type="secondary", width="stretch"):
            st.session_state["_navigate_to_seo_health"] = True
            st.rerun()

    st.caption(f"Output saved to: `{runner.output_dir}`")

    st.markdown("---")

    render_unified_results(runner, key_prefix="newrun_")

    st.markdown("---")
    if st.button("Capture Again", key="newrun_run_again"):
        st.session_state.newrun_just_finished = False
        st.rerun()


def _step_1_urls() -> list[str]:
    """Step 1: URL input."""
    st.markdown("### Step 1: URLs to Capture")
    existing_urls = st.session_state.get("capture_urls") or []
    url_count = len(existing_urls)

    url_source = st.radio(
        "URL source",
        ["Paste URLs", "Import CSV"],
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

    elif url_source == "Import CSV":
        uploaded = st.file_uploader(
            "Upload CSV file",
            type=["csv"],
            key="newrun_csv",
            label_visibility="collapsed",
        )
        if uploaded:
            raw = uploaded.read()
            try:
                pairs = import_from_csv_file(raw)
                imported_urls = [a for a, _ in pairs]
                st.success(f"Found {len(imported_urls)} URLs from CSV")
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
        st.info("Paste URLs above, or import from CSV.")

    # Sitemap auto-discovery toggle (for fast mode)
    if url_count > 0:
        st.checkbox(
            "Auto-discover URLs from sitemap.xml",
            key="newrun_auto_discover_sitemap",
            value=False,
            help="Fetch /sitemap.xml from seed URLs and add discovered URLs to crawl (Fast mode only)",
        )

    return existing_urls


def _step_2_collectors() -> dict[str, bool]:
    """Step 2: Collector selection."""
    st.markdown("### Step 2: Collectors")
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
        seo_exp = st.expander("Configure SEO fields", expanded=False)
        if seo_exp.open:
            with seo_exp:
                render_seo_fields_selector(key_prefix="newrun_seo_fields")
    else:
        st.session_state["newrun_seo_fields_enabled"] = get_standard_seo_fields()

    return collectors


def _step_3_crawl_mode(urls: list[str]) -> tuple[str, dict, dict]:
    """Step 3: Crawl mode selection with smart default."""
    st.markdown("### Step 3: Crawl Mode")

    # Smart default
    default_mode = st.session_state.get("newrun_crawl_mode") or _smart_crawl_mode(urls)

    crawl_mode = st.segmented_control(
        "Mode",
        options=["unified", "fast"],
        default=default_mode,
        key="newrun_crawl_mode",
        format_func=lambda x: {"unified": "Normal", "fast": "Fast"}[x],
        help=(
            "Normal: SeleniumBase (SEO + extraction, browser-rendered)\n"
            "Fast: curl_cffi (SEO only, 8 concurrent, no JS)"
        ),
    ) or "fast"

    crawl_config = {}
    fast_config = {}

    # Fast mode specific configuration
    if crawl_mode == "fast":
        with st.container(border=True):
            st.markdown("**Fast Crawl Settings**")

            # Quick Setup
            preset_names = list(FAST_CRAWL_PRESETS.keys())
            preset = st.selectbox(
                "Quick setup (you can still customize below):",
                ["Custom", *preset_names],
                key="newrun_fast_crawl_preset",
                label_visibility="collapsed",
                help="Choose a preset to auto-fill the settings below, then tweak anything you like.",
            )
            if preset != "Custom":
                for k, v in FAST_CRAWL_PRESETS[preset].items():
                    st.session_state[f"newrun_{k}"] = v
                st.session_state.pop("newrun_fast_crawl_preset", None)
                st.rerun()

            # Settings Grid
            fc1, fc2 = st.columns(2)
            with fc1:
                depth = st.session_state.get("newrun_max_depth", CONFIG.get("fast", {}).get("max_depth", 0))
                st.number_input(
                    "🔗 Max depth",
                    min_value=0, max_value=10, value=depth,
                    key="newrun_max_depth",
                    help="0 = Only scan the URLs you entered. 1 = Also scan links found on those pages. 2+ = Deep crawl.",
                )
                depth_label = {0: "🔵 Just your URLs", 1: "🟡 One level deep",
                               2: "🟠 Two levels deep"}.get(depth, "🔴 Deep crawl (many pages)")
                st.caption(depth_label)

                st.number_input(
                    "📄 Maximum pages to scan",
                    min_value=1, max_value=100000,
                    value=st.session_state.get("newrun_max_pages", CONFIG.get("fast", {}).get("max_pages", 1000)),
                    key="newrun_max_pages",
                    help="Safety limit to prevent accidentally scanning too many pages.",
                )

                if depth > 2:
                    st.warning("Following links 3+ levels deep can scan thousands of pages and may take a long time.")
                if st.session_state.get("newrun_max_pages", CONFIG.get("fast", {}).get("max_pages", 1000)) > 5000:
                    st.warning("Scanning over 5,000 pages can get your IP blocked by some websites. Increase only if needed.")

                st.toggle(
                    "🧹 Ignore tracking codes (?utm_source=, ?ref=, etc.)",
                    value=st.session_state.get("newrun_strip_query_params", CONFIG.get("fast", {}).get("strip_query_params", True)),
                    key="newrun_strip_query_params",
                    help="Removes things like ?utm_source=facebook so pages with different tracking codes aren't scanned twice.",
                )
                st.toggle(
                    "🤖 Follow site crawling rules (recommended)",
                    value=st.session_state.get("newrun_respect_robots_txt", CONFIG.get("fast", {}).get("respect_robots_txt", False)),
                    key="newrun_respect_robots_txt",
                    help="Most websites have a 'robots.txt' file that tells crawlers which pages to skip. Enabling this is polite and helps avoid being blocked.",
                )

                st.text_area(
                    "✅ Only scan URLs containing...",
                    value="\n".join(st.session_state.get("newrun_include_patterns", CONFIG.get("fast", {}).get("include_patterns", []))),
                    key="newrun_include_patterns",
                    help="One per line. Only pages whose web address contains these words will be scanned. Leave empty to scan all URLs.\n\nExample:\n  /blog/\n  /news/",
                    height=80,
                )
                st.text_area(
                    "❌ Skip URLs containing...",
                    value="\n".join(st.session_state.get("newrun_exclude_patterns", CONFIG.get("fast", {}).get("exclude_patterns", []))),
                    key="newrun_exclude_patterns",
                    help="One per line. Pages whose web address contains these words will be skipped.\n\nExample:\n  /tag/\n  ?page=",
                    height=80,
                )

            with fc2:
                if urls:
                    from urllib.parse import urlparse as _urlparse
                    detected = set()
                    for u in urls:
                        try:
                            detected.add(_urlparse(u).netloc)
                        except Exception:
                            pass
                    if detected:
                        st.caption(f"Detected website(s): {', '.join(sorted(detected))}")

                st.text_area(
                    "🌐 Stay on these websites only",
                    value="\n".join(st.session_state.get("newrun_allowed_domains", CONFIG.get("fast", {}).get("allowed_domains", []))),
                    key="newrun_allowed_domains",
                    help="One domain per line. Only pages from these websites will be scanned.\nLeave empty to automatically stay on the same website(s) as your starting URLs.\n\nExample:\n  example.com\n  blog.example.com",
                    height=80,
                )
                st.text_area(
                    "🚫 Skip these websites",
                    value="\n".join(st.session_state.get("newrun_blocked_domains", CONFIG.get("fast", {}).get("blocked_domains", []))),
                    key="newrun_blocked_domains",
                    help="One domain per line. Pages from these websites will never be scanned.\n\nExample:\n  facebook.com\n  twitter.com",
                    height=80,
                )

                raw_allowed = st.session_state.get("newrun_allowed_domains", "")
                if not raw_allowed.strip() and depth > 0:
                    st.info("ℹ️ We'll automatically stay on the same website(s) as your starting URLs.")

            # Scope Estimate
            st.markdown("---")
            url_count = len(urls)
            if url_count == 0:
                st.info("Add URLs in Step 1 to see an estimate of how many pages will be scanned.")
            else:
                depth = st.session_state.get("newrun_max_depth", CONFIG.get("fast", {}).get("max_depth", 0))
                if depth == 0:
                    estimated = url_count
                elif depth == 1:
                    estimated = min(url_count * 10, 10000)
                elif depth == 2:
                    estimated = min(url_count * 50, 50000)
                else:
                    estimated = min(url_count * (10 ** depth), 100000)
                max_p = st.session_state.get("newrun_max_pages", CONFIG.get("fast", {}).get("max_pages", 1000))
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
                "max_depth": st.session_state.get("newrun_max_depth", CONFIG.get("fast", {}).get("max_depth", 0)),
                "max_pages": st.session_state.get("newrun_max_pages", CONFIG.get("fast", {}).get("max_pages", 1000)),
                "include_patterns": [p.strip() for p in raw_include.split("\n") if p.strip()] if raw_include else [],
                "exclude_patterns": [p.strip() for p in raw_exclude.split("\n") if p.strip()] if raw_exclude else [],
                "strip_query_params": st.session_state.get("newrun_strip_query_params", CONFIG.get("fast", {}).get("strip_query_params", True)),
                "respect_robots_txt": st.session_state.get("newrun_respect_robots_txt", CONFIG.get("fast", {}).get("respect_robots_txt", False)),
                "allowed_domains": [d.strip() for d in raw_allowed.split("\n") if d.strip()] if raw_allowed else [],
                "blocked_domains": [d.strip() for d in raw_blocked.split("\n") if d.strip()] if raw_blocked else [],
                "auto_discover_sitemap": st.session_state.get("newrun_auto_discover_sitemap", False),
            }

    # Fast mode specific configuration
    if crawl_mode == "fast":
        with st.container(border=True):
            st.markdown("**Fast Mode Settings**")

            fc1, fc2 = st.columns(2)
            with fc1:
                st.number_input(
                    "🔁 Max retries",
                    min_value=0, max_value=10,
                    value=st.session_state.get("newrun_max_retries", CONFIG.get("fast", {}).get("max_retries", 3)),
                    key="newrun_max_retries",
                    help="Number of retry attempts for failed URLs (rate limits, server errors)."
                )
                st.text_input(
                    "🔢 Retry on HTTP status codes",
                    value=st.session_state.get("newrun_retry_on_status", CONFIG.get("fast", {}).get("retry_on_status", "429,500,502,503,504")),
                    key="newrun_retry_on_status",
                    help="Comma-separated HTTP status codes to retry (e.g., 429,500,502,503,504). 404/403 are not retried by default."
                )
            with fc2:
                st.number_input(
                    "⚡ Max concurrent workers",
                    min_value=1, max_value=32,
                    value=st.session_state.get("newrun_max_workers", _smart_fast_workers()),
                    key="newrun_max_workers",
                    help="Maximum number of concurrent requests."
                )
                st.number_input(
                    "⏱️ Request timeout (seconds)",
                    min_value=5, max_value=120,
                    value=st.session_state.get("newrun_timeout", CONFIG.get("fast", {}).get("timeout", 30)),
                    key="newrun_timeout",
                    help="Timeout for each HTTP request in seconds."
                )

            raw_retry = st.session_state.get("newrun_retry_on_status", CONFIG.get("fast", {}).get("retry_on_status", "429,500,502,503,504"))
            fast_config = {
                "max_retries": st.session_state.get("newrun_max_retries", CONFIG.get("fast", {}).get("max_retries", 3)),
                "retry_on_status": [int(x.strip()) for x in raw_retry.split(",") if x.strip().isdigit()] if raw_retry else [],
                "max_workers": st.session_state.get("newrun_max_workers", _smart_fast_workers()),
                "timeout": st.session_state.get("newrun_timeout", CONFIG.get("fast", {}).get("timeout", 30.0)),
            }

    # Show smart default badge
    if crawl_mode == "fast":
        st.caption(":material/bolt: Fast mode — SEO only, no JavaScript rendering")
    else:
        st.caption(":material/desktop_windows: Normal mode — full browser, SEO + extraction")

    return crawl_mode, crawl_config, fast_config


def _step_4_advanced() -> dict:
    """Step 4: Advanced settings (collapsible)."""
    st.markdown("### Step 4: Advanced Settings")

    with st.expander("Viewport & Timing", expanded=False):
        s1, s2 = st.columns(2)
        with s1:
            st.metric("Width", CONFIG["viewport"]["width"])
            st.number_input(
                "Stabilization (ms)",
                value=CONFIG["timing"]["stabilization_ms"],
                min_value=500,
                max_value=10000,
                step=100,
                key="newrun_stabilization",
                help="Wait time after scroll before capture",
            )
            st.number_input(
                "Inter-page delay min (s)",
                value=CONFIG["timing"]["inter_page_delay_min"],
                min_value=0.0,
                max_value=10.0,
                key="newrun_min_delay",
                help="Minimum random delay between pages",
            )
        with s2:
            st.metric("Height", CONFIG["viewport"]["height"])
            st.number_input(
                "Scroll interval (ms)",
                value=CONFIG["timing"]["scroll_interval_ms"],
                min_value=100,
                max_value=5000,
                key="newrun_scroll_interval",
                help="Delay between scroll steps",
            )
            st.number_input(
                "Inter-page delay max (s)",
                value=CONFIG["timing"]["inter_page_delay_max"],
                min_value=0.0,
                max_value=10.0,
                key="newrun_max_delay",
                help="Maximum random delay between pages",
            )

    with st.expander("Network Idle (scroll wait)", expanded=False):
        st.toggle(
            "Wait for network idle",
            value=CONFIG["timing"]["scroll_wait_for_idle"],
            key="newrun_wait_idle",
            help="Poll for pending fetch/XHR + image loads before advancing scroll",
        )
        st.number_input(
            "Idle timeout (ms)",
            value=CONFIG["timing"]["scroll_idle_timeout_ms"],
            min_value=1000,
            max_value=30000,
            key="newrun_idle_timeout",
        )
        st.number_input(
            "Poll interval (ms)",
            value=CONFIG["timing"]["scroll_idle_poll_ms"],
            min_value=50,
            max_value=1000,
            key="newrun_idle_poll",
        )

    with st.expander("Overlay Hiding", expanded=False):
        st.toggle(
            "Auto-hide cookie banners, chat, modals",
            value=True,
            key="newrun_hide_overlays",
        )
        st.caption("Uses built-in selectors for common overlays")

    with st.expander("Trafilatura (content extraction)", expanded=False):
        st.toggle(
            "Enable trafilatura",
            value=CONFIG.get("trafilatura", {}).get("enabled", True),
            key="newrun_trafilatura_enabled",
        )
        st.selectbox(
            "Output format",
            ["txt", "markdown", "json", "xml", "xmltei", "csv", "html"],
            index=0,
            key="newrun_trafilatura_format",
        )
        st.toggle("Include tables", value=True, key="newrun_trafilatura_tables")
        st.toggle("Favor precision", value=True, key="newrun_trafilatura_precision")

    with st.expander("Output", expanded=False):
        output_name = st.text_input(
            "Folder name",
            value=st.session_state.newrun_output,
            key="newrun_output_name",
        )
        st.session_state.newrun_output = output_name

    return {}


def _render_run_button(existing_urls: list[str], collectors: dict[str, bool], crawl_config: dict | None = None, fast_config: dict | None = None) -> None:
    """Render the primary run button with validation."""
    active_collectors = [k for k, v in collectors.items() if v]
    can_run = existing_urls and active_collectors
    btn_disabled = st.session_state.unified_running or not can_run

    reasons = []
    if not existing_urls:
        reasons.append("add URLs in Step 1")
    if not active_collectors:
        reasons.append("select a collector in Step 2")
    if collectors.get("extraction") and not st.session_state.get("extraction_rules"):
        reasons.append("load extraction rules in Rule Sets")

    if reasons:
        st.caption(f"To start: {', '.join(reasons)}")

    crawl_mode = st.session_state.get("newrun_crawl_mode", "fast")

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
            stabilization_ms=int(st.session_state.get("newrun_stabilization", CONFIG["timing"]["stabilization_ms"])),
        )

        if crawl_mode == "fast":
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


def page_new_capture() -> None:
    st.subheader("New Capture")

    for key, default in [
        ("newrun_collectors", {"seo": True, "extraction": False}),
        ("newrun_output", _smart_output_name()),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    if st.session_state.get("_newrun_from_history"):
        st.session_state.pop("newrun_just_finished", None)
        st.session_state.pop("_newrun_from_history", None)
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

    # 4-step vertical wizard
    st.markdown("---")

    # Step 1: URLs
    with st.container(border=True):
        urls = _step_1_urls()

    st.markdown("")

    # Step 2: Collectors
    with st.container(border=True):
        collectors = _step_2_collectors()

    st.markdown("")

    # Step 3: Crawl Mode
    with st.container(border=True):
        crawl_mode, crawl_config, fast_config = _step_3_crawl_mode(urls)

    st.markdown("")

    # Step 4: Advanced (collapsible)
    with st.container(border=True):
        _step_4_advanced()

    st.markdown("---")

    # Primary action
    _render_run_button(urls, collectors, crawl_config, fast_config)

    st.markdown("")

    # Secondary actions
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Save as Template", key="newrun_save_template", width="stretch"):
            st.toast("Template saving coming soon")
    with c2:
        if st.button("Load Template", key="newrun_load_template", width="stretch"):
            st.toast("Template loading coming soon")
    with c3:
        if st.button("Reset Form", key="newrun_reset", width="stretch"):
            for key in list(st.session_state.keys()):
                if key.startswith("newrun_"):
                    del st.session_state[key]
            st.rerun()
