"""Page Capture — Desktop app for SEO extraction and website crawling.

Router: wires page functions into st.navigation with sidebar layout.
"""

from __future__ import annotations

import streamlit as st

from app_pages.blog_audit import page_blog_audit
from app_pages.capture import page_new_run
from app_pages.dashboard import page_dashboard
from app_pages.projects import page_projects
from app_pages.rule_sets import page_rule_sets
from app_pages.seo_analysis import page_seo_analysis
from app_pages.settings import page_settings
from state import init_session_state


def main() -> None:
    st.set_page_config(page_title="Page Capture", layout="wide", page_icon=":material/center_focus_strong:")
    init_session_state()

    with st.sidebar:
        st.title("Page Capture")
        st.caption("Screenshots, SEO & Stuff.")

        # Show active run status
        if st.session_state.get("unified_running") and st.session_state.get("unified_runner"):
            runner = st.session_state.unified_runner
            st.markdown("---")
            done = runner.progress_done
            total = runner.progress_total
            st.markdown(f"**Running Capture** — {done}/{total}")
            st.caption(runner.status if runner.status else "Processing...")
        elif st.session_state.get("blog_audit_running") and st.session_state.get("blog_audit_runner"):
            runner = st.session_state.blog_audit_runner
            st.markdown("---")
            done = runner.progress_done
            total = runner.progress_total
            st.markdown(f"**Running Blog Audit** — {done}/{total}")
            st.caption(runner.status if runner.status else "Processing...")

        pages = {
            "Capture": [
                st.Page(page_new_run, title="Capture", icon=":material/rocket_launch:", default=True),
                st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:"),
            ],
            "Tools": [
                st.Page(page_rule_sets, title="Rule Sets", icon=":material/tune:"),
                st.Page(page_seo_analysis, title="SEO Analysis", icon=":material/analytics:"),
                st.Page(page_blog_audit, title="Blog Audit", icon=":material/article:"),
            ],
            "Library": [
                st.Page(page_projects, title="Projects", icon=":material/folder:"),
                st.Page(page_settings, title="Settings", icon=":material/settings:"),
            ],
        }

    pg = st.navigation(pages, position="sidebar")
    pg.run()


main()
