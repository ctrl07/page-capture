"""History page — browse, re-run, and delete past runs."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import streamlit as st

from components.results_viewer import render_results
from runners import build_zip, delete_history_entry, load_history


def _render_history_unified(entry: dict, idx: int) -> None:
    output_dir = Path(entry.get("output_dir", ""))
    by_kind = entry.get("results_by_collector", {})
    collectors = entry.get("collectors", list(by_kind.keys()))
    labels = {
        "screenshot": "Screenshots", "seo": "Quick SEO",
        "extraction": "Custom Rules",
    }
    available = [c for c in collectors if by_kind.get(c)]
    if not available:
        st.info("No collector results in this run.")
        return
    hist_labels = [labels[c] if c in labels else c for c in available]
    tabs = st.tabs(hist_labels)
    for tab, kind in zip(tabs, available):
        with tab:
            render_results(by_kind[kind], kind, output_dir, key_prefix=f"hist_{idx}_{kind}_")


def page_history() -> None:
    st.subheader("Run History")
    history = load_history()
    if not history:
        st.info("No runs yet.")
        return

    search = st.text_input("Search", placeholder="Filter by URL or kind...", key="hist_search", label_visibility="collapsed")
    filtered_indices = list(range(len(history)))
    if search.strip():
        q = search.strip().lower()
        filtered_indices = [
            i for i in filtered_indices
            if q in history[i].get("kind", "").lower()
            or any(q in r.get("url", "").lower() for r in history[i].get("results", []))
            or any(q in r.get("source_url", "").lower() for r in history[i].get("results", []))
        ]

    if not filtered_indices:
        st.info("No runs match the search.")
        return

    selected_idx = st.selectbox(
        "Select a past run to browse", options=filtered_indices,
        format_func=lambda i: f"{history[i]['timestamp'][:19]} — {history[i]['kind']} — {history[i]['ok']}/{history[i]['total']} OK",
        key="history_selector",
    )
    entry = history[selected_idx]
    kind = entry["kind"]
    results = entry.get("results", [])
    output_dir = Path(entry.get("output_dir", ""))

    st.caption(f"Run at {entry['timestamp'][:19]} | {entry['total']} URLs | {entry['ok']} OK | {entry['fail']} fail")

    col_rerun, col_delete, col_csv, col_zip, _ = st.columns([1, 1, 1, 1, 2])
    with col_rerun:
        if st.button("Re-run this job", key="hist_rerun"):
            urls_rerun = [r.get("url", r.get("source_url", "")) for r in results if r.get("url") or r.get("source_url")]
            if urls_rerun:
                st.session_state.capture_urls = urls_rerun
                # Restore collector toggles from history
                if entry.get("collectors"):
                    st.session_state.restore_collectors = entry["collectors"]
                elif kind == "unified":
                    st.session_state.restore_collectors = ["screenshot", "seo"]
                elif kind == "screenshot":
                    st.session_state.restore_collectors = ["screenshot"]
                elif kind == "seo":
                    st.session_state.restore_collectors = ["seo"]
                elif kind == "extraction":
                    st.session_state.restore_collectors = ["extraction"]
                st.rerun()
    with col_delete:
        if st.button("Delete from history", key="hist_del_entry"):
            delete_history_entry(selected_idx)
            st.rerun()
    with col_csv:
        if results and kind in ("seo", "extraction"):
            all_keys = list(dict.fromkeys(k for r in results for k in r))
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
            st.download_button(
                "Download CSV", data=csv_buf.getvalue().encode(),
                file_name=f"{kind}_results.csv", mime="text/csv",
                key=f"hist_{selected_idx}_dl_csv",
            )
    with col_zip:
        if kind == "screenshot" and results:
            st.download_button(
                "Download ZIP", data=build_zip(results, output_dir),
                file_name="screenshots.zip", mime="application/zip",
                key=f"hist_{selected_idx}_dl_zip",
            )

    if kind == "unified":
        _render_history_unified(entry, selected_idx)
    elif results:
        render_results(results, kind, output_dir, key_prefix=f"hist_{selected_idx}_")
