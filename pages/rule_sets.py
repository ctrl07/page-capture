"""Rule Sets page — extraction rule editor (standalone, no run form)."""

from __future__ import annotations

import streamlit as st

from extraction import render_rules_editor
from page_capture import load_config
from runners import HERE, build_runtime_config

CONFIG = load_config(HERE / "config.yaml")


def page_rule_sets() -> None:
    st.subheader("Rule Sets")
    runtime_cfg = build_runtime_config(CONFIG, CONFIG["viewport"], CONFIG["timing"]["stabilization_ms"])
    render_rules_editor(allow_run=False, runtime_cfg=runtime_cfg)
