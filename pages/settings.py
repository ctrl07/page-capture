"""Settings page — config editor and output folder management."""

from __future__ import annotations

import shutil
from datetime import datetime

import streamlit as st
import yaml

from runners import HERE

CONFIG_PATH = HERE / "config.yaml"


def _load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False)


def _render_config_editor(config: dict) -> None:
    """Render the viewport/timing configuration editor."""
    st.subheader("Viewport & Timing")

    with st.form("cfg_form"):
        col1, col2 = st.columns(2)
        with col1:
            new_width = st.number_input(
                "Viewport width",
                value=config["viewport"]["width"],
                min_value=320,
                max_value=3840,
                help="Browser viewport width in pixels",
            )
            new_stab = st.number_input(
                "Stabilization (ms)",
                value=config["timing"]["stabilization_ms"],
                min_value=500,
                max_value=10000,
                step=100,
                help="Wait time after scroll before capture",
            )
            new_min_delay = st.number_input(
                "Inter-page delay min (s)",
                value=config["timing"]["inter_page_delay_min"],
                min_value=0.0,
                max_value=10.0,
                help="Minimum random delay between pages",
            )
        with col2:
            new_height = st.number_input(
                "Viewport height",
                value=config["viewport"]["height"],
                min_value=320,
                max_value=2160,
                help="Browser viewport height in pixels",
            )
            new_max_delay = st.number_input(
                "Inter-page delay max (s)",
                value=config["timing"]["inter_page_delay_max"],
                min_value=0.0,
                max_value=10.0,
                help="Maximum random delay between pages",
            )
            new_scroll_interval = st.number_input(
                "Scroll interval (ms)",
                value=config["timing"].get("scroll_interval_ms", 600),
                min_value=100,
                max_value=5000,
                step=100,
                help="Time between scroll steps",
            )

        if st.form_submit_button("Save Configuration", type="primary", width="stretch"):
            try:
                config["viewport"]["width"] = int(new_width)
                config["viewport"]["height"] = int(new_height)
                config["timing"]["stabilization_ms"] = int(new_stab)
                config["timing"]["inter_page_delay_min"] = float(new_min_delay)
                config["timing"]["inter_page_delay_max"] = float(new_max_delay)
                config["timing"]["scroll_interval_ms"] = int(new_scroll_interval)
                _save_config(config)
                st.success("Config saved to config.yaml")
            except Exception as e:
                st.error(f"Failed to save: {e}")


def _render_output_folders() -> None:
    """Render output folder management."""
    st.subheader("Output Folders")

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
                st.session_state["confirm_delete_folder"] = selected

        with col3:
            # Show folder size
            total_size = sum(f.stat().st_size for f in folder_path.rglob("*") if f.is_file())
            st.metric("Size", f"{total_size / 1024 / 1024:.1f} MB")

        if st.session_state.get("confirm_delete_folder") == selected:
            st.warning(f"Delete `{selected}`? This cannot be undone.")
            c_yes, c_no, _ = st.columns([1, 1, 4])
            with c_yes:
                if st.button("Yes, delete", type="primary", key="confirm_del_yes"):
                    try:
                        shutil.rmtree(folder_path)
                        st.session_state.pop("confirm_delete_folder", None)
                        st.success(f"Deleted {selected}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to delete: {e}")
            with c_no:
                if st.button("Cancel", key="confirm_del_no"):
                    st.session_state.pop("confirm_delete_folder", None)
                    st.rerun()


def _render_about() -> None:
    """Render about/version info."""
    st.subheader("About")
    st.markdown("""
    **Page Capture** — Desktop website migration audit tool

    - Screenshots via SeleniumBase + CDP
    - SEO extraction via CSS selectors
    - Custom extraction rules
    - Fast crawl mode (curl_cffi)
    - PDF reports via fpdf2

    **Version:** 1.0.0
    **Python:** ≥3.10
    """)

    if st.button("Check for Updates", width="stretch"):
        st.info("Run `uv sync --upgrade` in terminal to update dependencies")


def page_settings() -> None:
    st.subheader("Settings")

    config = _load_config()

    tabs = st.tabs(["Configuration", "Output Folders", "About"])

    with tabs[0]:
        _render_config_editor(config)

    with tabs[1]:
        _render_output_folders()

    with tabs[2]:
        _render_about()
