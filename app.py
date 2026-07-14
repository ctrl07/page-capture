"""Page Capture — Desktop app for screenshots and SEO extraction.

Router: wires page functions into st.navigation with sidebar layout.
"""

from __future__ import annotations

import streamlit as st

from pages.capture import page_new_run
from pages.dashboard import page_dashboard
from pages.history import page_history
from pages.rule_sets import page_rule_sets
from pages.seo_analysis import page_seo_analysis
from pages.settings import page_settings
from state import init_session_state


def main() -> None:
    st.set_page_config(page_title="Page Capture", layout="wide", page_icon=":material/center_focus_strong:")
    init_session_state()

    pages = {
        "Capture": [
            st.Page(page_new_run, title="Capture", icon=":material/rocket_launch:", default=True),
            st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:"),
        ],
        "Tools": [
            st.Page(page_rule_sets, title="Rule Sets", icon=":material/tune:"),
            st.Page(page_seo_analysis, title="SEO Analysis", icon=":material/analytics:"),
        ],
        "Library": [
            st.Page(page_history, title="History", icon=":material/history:"),
            st.Page(page_settings, title="Settings", icon=":material/settings:"),
        ],
    }

    with st.sidebar:
        st.title("Page Capture")
        st.caption("Screenshots, SEO extraction, custom rules.")

        # Show active run status
        if st.session_state.get("unified_running") and st.session_state.get("unified_runner"):
            runner = st.session_state.unified_runner
            st.markdown("---")
            done = runner.progress_done
            total = runner.progress_total
            st.markdown(f"**Running** — {done}/{total}")
            st.caption(runner.status if runner.status else "Processing...")

    pg = st.navigation(pages, position="sidebar")
    pg.run()


main()
