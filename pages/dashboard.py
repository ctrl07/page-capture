"""Dashboard page — last-run summary metrics and quick links."""

from __future__ import annotations

import streamlit as st

from runners import load_history


def page_dashboard() -> None:
    st.subheader("Dashboard")
    history = load_history()
    if not history:
        st.info("No runs yet. Start a crawl to see metrics here.")
        return

    c1, c2, c3, c4 = st.columns(4)
    total_runs = len(history)
    total_urls = sum(h.get("total", 0) for h in history)
    total_ok = sum(h.get("ok", 0) for h in history)
    total_fail = sum(h.get("fail", 0) for h in history)
    c1.metric("Total Runs", total_runs)
    c2.metric("URLs Crawled", total_urls)
    c3.metric("Succeeded", total_ok)
    c4.metric("Failed", total_fail)

    st.markdown("---")
    st.markdown("**Last 5 Runs**")
    for entry in history[:5]:
        ts = entry["timestamp"][:19]
        kind = entry.get("kind", "unknown")
        ok = entry.get("ok", 0)
        total = entry.get("total", 0)
        fail = entry.get("fail", 0)
        st.caption(f"{ts} | {kind} | {ok}/{total} OK | {fail} failed")
