"""Settings page — config editor and output folder management."""

from __future__ import annotations

import shutil

import streamlit as st
import yaml

from runners import HERE

CONFIG_PATH = HERE / "config.yaml"


def _load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def page_settings() -> None:
    config = _load_config()

    st.subheader("Configuration")
    with st.form("cfg_form"):
        new_width = st.number_input("Viewport width", value=config["viewport"]["width"], min_value=320, max_value=3840)
        new_height = st.number_input("Viewport height", value=config["viewport"]["height"], min_value=320, max_value=2160)
        new_stab = st.number_input("Stabilization (ms)", value=config["timing"]["stabilization_ms"], min_value=500, max_value=10000, step=100)
        new_min_delay = st.number_input("Inter-page delay min (s)", value=config["timing"]["inter_page_delay_min"], min_value=0.0, max_value=10.0)
        new_max_delay = st.number_input("Inter-page delay max (s)", value=config["timing"]["inter_page_delay_max"], min_value=0.0, max_value=10.0)
        if st.form_submit_button("Save"):
            try:
                config["viewport"]["width"] = int(new_width)
                config["viewport"]["height"] = int(new_height)
                config["timing"]["stabilization_ms"] = int(new_stab)
                config["timing"]["inter_page_delay_min"] = float(new_min_delay)
                config["timing"]["inter_page_delay_max"] = float(new_max_delay)
                with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, default_flow_style=False)
                st.success("Config saved to config.yaml")
            except Exception as e:
                st.error(f"Failed to save: {e}")

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
                        try:
                            shutil.rmtree(HERE / selected)
                            st.session_state.pop("confirm_delete_folder", None)
                            st.success(f"Deleted {selected}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete: {e}")
                with c_no:
                    if st.button("Cancel", key="confirm_del_no"):
                        st.session_state.pop("confirm_delete_folder", None)
                        st.rerun()
