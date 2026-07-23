"""Settings page — config editor with category sidebar and output folder management."""

from __future__ import annotations

import shutil
from datetime import datetime

import streamlit as st
import yaml

from runners import HERE

CONFIG_PATH = HERE / "config.yaml"

CATEGORIES = {
    "browser": {
        "icon": "🖥️",
        "label": "Browser & Capture",
        "fields": [
            ("viewport.width", "Viewport Width", "number", {"min_value": 320, "max_value": 3840, "step": 1}),
            ("viewport.height", "Viewport Height", "number", {"min_value": 320, "max_value": 2160, "step": 1}),
            ("timing.stabilization_ms", "Stabilization (ms)", "number", {"min_value": 500, "max_value": 10000, "step": 100}),
            ("timing.scroll_interval_ms", "Scroll Interval (ms)", "number", {"min_value": 100, "max_value": 5000, "step": 100}),
            ("timing.inter_page_delay_min", "Inter-page Delay Min (s)", "number", {"min_value": 0.0, "max_value": 10.0, "step": 0.1}),
            ("timing.inter_page_delay_max", "Inter-page Delay Max (s)", "number", {"min_value": 0.0, "max_value": 10.0, "step": 0.1}),
        ],
    },
    "network_idle": {
        "icon": "⏳",
        "label": "Network Idle",
        "fields": [
            ("timing.scroll_wait_for_idle", "Wait for Network Idle", "bool", {}),
            ("timing.scroll_idle_timeout_ms", "Idle Timeout (ms)", "number", {"min_value": 1000, "max_value": 30000, "step": 100}),
            ("timing.scroll_idle_poll_ms", "Poll Interval (ms)", "number", {"min_value": 50, "max_value": 1000, "step": 10}),
        ],
    },
    "fast": {
        "icon": "⚡",
        "label": "Fast Crawl (curl_cffi)",
        "fields": [
            ("fast.max_retries", "Max Retries", "number", {"min_value": 0, "max_value": 10, "step": 1}),
            ("fast.retry_on_status", "Retry on Status Codes", "text", {}),
            ("fast.max_workers", "Max Workers", "number", {"min_value": 1, "max_value": 32, "step": 1}),
            ("fast.timeout", "Request Timeout (s)", "number", {"min_value": 5, "max_value": 120, "step": 1}),
        ],
    },
    "crawl4ai": {
        "icon": "🤖",
        "label": "Crawl4AI",
        "fields": [
            ("crawl4ai.rate_limit_rps", "Rate Limit RPS", "number", {"min_value": 1, "max_value": 100, "step": 1}),
            ("crawl4ai.rate_limit_burst", "Burst Allowance", "number", {"min_value": 1, "max_value": 10, "step": 1}),
            ("crawl4ai.timeout", "Request Timeout (s)", "number", {"min_value": 10, "max_value": 300, "step": 5}),
            ("crawl4ai.wait_until", "Wait Condition", "select", {"options": ["load", "domcontentloaded", "networkidle", "commit"]}),
            ("crawl4ai.max_depth", "Max Depth", "number", {"min_value": 0, "max_value": 10, "step": 1}),
            ("crawl4ai.max_pages", "Max Pages", "number", {"min_value": 100, "max_value": 100000, "step": 100}),
            ("crawl4ai.strip_query_params", "Strip Query Params", "bool", {}),
            ("crawl4ai.respect_robots_txt", "Respect robots.txt", "bool", {}),
            ("crawl4ai.include_patterns", "Include Patterns", "textarea", {}),
            ("crawl4ai.exclude_patterns", "Exclude Patterns", "textarea", {}),
            ("crawl4ai.allowed_domains", "Allowed Domains", "textarea", {}),
            ("crawl4ai.blocked_domains", "Blocked Domains", "textarea", {}),
        ],
    },
    "trafilatura": {
        "icon": "📄",
        "label": "Trafilatura Extraction",
        "fields": [
            ("trafilatura.enabled", "Enabled", "bool", {}),
            ("trafilatura.output_format", "Output Format", "select", {"options": ["txt", "markdown", "json", "xml", "xmltei", "csv", "html"]}),
            ("trafilatura.include_comments", "Include Comments", "bool", {}),
            ("trafilatura.include_tables", "Include Tables", "bool", {}),
            ("trafilatura.include_images", "Include Images", "bool", {}),
            ("trafilatura.include_formatting", "Include Formatting", "bool", {}),
            ("trafilatura.include_links", "Include Links", "bool", {}),
            ("trafilatura.favor_precision", "Favor Precision", "bool", {}),
            ("trafilatura.favor_recall", "Favor Recall", "bool", {}),
            ("trafilatura.target_language", "Target Language", "text", {}),
            ("trafilatura.deduplicate", "Deduplicate", "bool", {}),
            ("trafilatura.with_metadata", "With Metadata", "bool", {}),
            ("trafilatura.only_with_metadata", "Only With Metadata", "bool", {}),
            ("trafilatura.max_tree_size", "Max Tree Size", "number", {"min_value": 0, "step": 1000}),
            ("trafilatura.author_blacklist", "Author Blacklist", "textarea", {}),
            ("trafilatura.prune_xpath", "Prune XPaths", "textarea", {}),
        ],
    },
    "output": {
        "icon": "💾",
        "label": "Output Folders",
        "fields": [],
    },
    "advanced": {
        "icon": "🔧",
        "label": "Advanced",
        "fields": [],
    },
}


def _load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def _get_nested(d: dict, path: str):
    for key in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(key, {})
    return d


def _set_nested(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def _render_category(config: dict, cat_key: str) -> bool:
    cat = CATEGORIES[cat_key]
    modified = False

    with st.form(f"cfg_form_{cat_key}", border=True):
        st.markdown(f"### {cat['icon']} {cat['label']}")

        for path, label, ftype, kwargs in cat["fields"]:
            current = _get_nested(config, path)

            if ftype == "number":
                new_val = st.number_input(label, value=current, **kwargs)
            elif ftype == "text":
                new_val = st.text_input(label, value=str(current) if current else "", **kwargs)
            elif ftype == "bool":
                new_val = st.checkbox(label, value=bool(current), **kwargs)
            elif ftype == "select":
                opts = kwargs.get("options", [])
                idx = opts.index(current) if current in opts else 0
                new_val = st.selectbox(label, opts, index=idx, **kwargs)
            elif ftype == "textarea":
                val = "\n".join(current) if isinstance(current, list) else str(current or "")
                new_val = st.text_area(label, value=val, height=100, **kwargs)
                new_val = [x.strip() for x in new_val.split("\n") if x.strip()]
            else:
                continue

            if new_val != current:
                _set_nested(config, path, new_val)
                modified = True

        if st.form_submit_button("Save", type="primary", width="stretch"):
            _save_config(config)
            st.success("Config saved")
            st.rerun()

    return modified


def _render_output_folders(config: dict) -> None:
    st.markdown("### 💾 Output Folders")

    folders = sorted(
        [p for p in HERE.iterdir() if p.is_dir() and ((p / "data").exists() or (p / "photos").exists())],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not folders:
        st.info("No output folders yet. Run a capture to create one.")
        return

    folder_names = [str(f.relative_to(HERE)) for f in folders]
    selected = st.selectbox("Select folder to manage", options=folder_names)

    if selected:
        folder_path = HERE / selected
        st.caption(f"Path: `{folder_path}`")
        st.caption(f"Modified: {datetime.fromtimestamp(folder_path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Open in Explorer", key="open_folder"):
                import subprocess
                subprocess.run(["explorer", str(folder_path)], check=False)

        with col2:
            if st.button("Delete Folder", type="secondary", key="del_folder"):
                _confirm_delete_folder(folder_path, selected)

        with col3:
            total_size = sum(f.stat().st_size for f in folder_path.rglob("*") if f.is_file())
            st.metric("Size", f"{total_size / 1024 / 1024:.1f} MB")


@st.dialog("Delete folder")
def _confirm_delete_folder(folder_path, selected):
    st.write(f"Delete `{selected}`? This cannot be undone.")
    with st.container(horizontal=True):
        if st.button("Yes, delete", type="primary"):
            try:
                shutil.rmtree(folder_path)
                st.success(f"Deleted {selected}")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to delete: {e}")
        if st.button("Cancel"):
            st.rerun()


def _render_about() -> None:
    st.markdown("### ℹ️ About")
    st.markdown("""
    **Page Capture** — Desktop website migration audit tool

    - Screenshots via SeleniumBase + CDP
    - SEO extraction via CSS selectors
    - Custom extraction rules
    - Fast crawl mode (curl_cffi)
    - Content extraction (trafilatura)
    - PDF reports via fpdf2

    **Version:** 1.0.0
    **Python:** ≥3.10
    """)

    if st.button("Check for Updates", width="stretch"):
        st.info("Run `uv sync --upgrade` in terminal to update dependencies")


def page_settings() -> None:
    st.subheader("Settings")

    config = _load_config()

    # Sidebar category navigation
    with st.sidebar:
        st.markdown("---")
        st.markdown("### Settings Categories")
        cat_keys = list(CATEGORIES.keys())
        cat_labels = [f"{CATEGORIES[k]['icon']} {CATEGORIES[k]['label']}" for k in cat_keys]
        selected_idx = st.radio(
            "Category",
            range(len(cat_keys)),
            format_func=lambda i: cat_labels[i],
            key="settings_cat",
            label_visibility="collapsed",
        )
        selected_cat = cat_keys[selected_idx]

    # Main content
    if selected_cat == "output":
        _render_output_folders(config)
    elif selected_cat == "advanced":
        st.markdown("### 🔧 Advanced")
        st.caption("Overlay hiding selectors (managed in config.yaml directly)")
        st.caption("Edit config.yaml for hide/hide_visibility sections")
        st.markdown("---")
        _render_about()
    else:
        _render_category(config, selected_cat)
        st.markdown("---")
        _render_about()
