"""Dashboard — run management, preview, and re-queue."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import streamlit as st

from components.results_viewer import render_results_grid, render_results_list
from runners import (
    build_zip,
    delete_history_entry,
    get_results,
    get_urls_from_results,
    load_history,
)


def _render_metrics(history: list[dict]) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Runs", len(history))
    c2.metric("URLs Crawled", sum(h.get("total", 0) for h in history))
    c3.metric("Succeeded", sum(h.get("ok", 0) for h in history))
    c4.metric("Failed", sum(h.get("fail", 0) for h in history))


def _render_run_list(history: list[dict], search: str, kind_filter: str) -> list[int]:
    filtered: list[int] = []
    for i, entry in enumerate(history):
        if kind_filter != "All" and entry.get("kind", "").lower() != kind_filter.lower():
            continue
        if search.strip():
            q = search.strip().lower()
            by_collector = get_results(entry)
            urls = [r.get("url", "") for rows in by_collector.values() for r in rows]
            if not any(q in u.lower() for u in urls) and q not in entry.get("kind", "").lower():
                continue
        filtered.append(i)
    return filtered


def _render_action_bar(
    entry: dict,
    selected_rows: dict[str, list[int]],
    key_prefix: str,
) -> None:
    by_collector = get_results(entry)
    output_dir = Path(entry.get("output_dir", ""))

    c_rerun, c_recapture, c_del, c_csv, c_zip, _ = st.columns([2, 2, 1, 1, 1, 3])

    with c_rerun:
        rerun_urls: list[str] = []
        for kind, rows in selected_rows.items():
            for idx in rows:
                collector_rows = by_collector.get(kind, [])
                if idx < len(collector_rows):
                    u = collector_rows[idx].get("url", "")
                    if u:
                        rerun_urls.append(u)
        rerun_urls = list(dict.fromkeys(rerun_urls))
        if st.button(
            f"Re-run selected ({len(rerun_urls)})",
            disabled=not rerun_urls,
            key=f"{key_prefix}rerun_sel",
            width="stretch",
            type="primary",
        ):
            st.session_state.capture_urls = rerun_urls
            if entry.get("collectors"):
                st.session_state.restore_collectors = entry["collectors"]
            if entry.get("extraction_rules"):
                st.session_state.restore_extraction_rules = entry["extraction_rules"]
            if entry.get("fast_mode"):
                st.session_state.restore_fast_mode = True
            st.session_state["_newrun_from_dashboard"] = True
            st.rerun()

    with c_recapture:
        all_urls = get_urls_from_results(entry)
        if st.button(
            f"Re-capture all ({len(all_urls)})",
            disabled=not all_urls,
            key=f"{key_prefix}recapture",
            width="stretch",
        ):
            st.session_state.capture_urls = all_urls
            if entry.get("collectors"):
                st.session_state.restore_collectors = entry["collectors"]
            if entry.get("extraction_rules"):
                st.session_state.restore_extraction_rules = entry["extraction_rules"]
            if entry.get("fast_mode"):
                st.session_state.restore_fast_mode = True
            st.session_state["_newrun_from_dashboard"] = True
            st.rerun()

    with c_del:
        if st.button("Delete", key=f"{key_prefix}del", width="stretch"):
            st.session_state["_dash_delete_idx"] = True

    with c_csv:
        all_results = [r for rows in by_collector.values() for r in rows]
        has_csv = any(kind in ("seo", "extraction") for kind in by_collector)
        if has_csv and all_results:
            all_keys = list(dict.fromkeys(k for r in all_results for k in r))
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_results)
            st.download_button(
                "CSV", data=csv_buf.getvalue().encode(),
                file_name="results.csv", mime="text/csv",
                key=f"{key_prefix}dl_csv", width="stretch",
            )

    with c_zip:
        has_screenshot = "screenshot" in by_collector and by_collector["screenshot"]
        if has_screenshot:
            st.download_button(
                "ZIP", data=build_zip(by_collector["screenshot"], output_dir),
                file_name="screenshots.zip", mime="application/zip",
                key=f"{key_prefix}dl_zip", width="stretch",
            )


def _render_collector_tabs(
    entry: dict,
    selected_rows: dict[str, list[int]],
    key_prefix: str,
) -> None:
    by_collector = get_results(entry)
    output_dir = Path(entry.get("output_dir", ""))
    collectors = entry.get("collectors", list(by_collector.keys()))
    labels = {"screenshot": "Screenshots", "seo": "Quick SEO", "extraction": "Custom Rules"}
    available = [c for c in collectors if by_collector.get(c)]
    if not available:
        st.info("No collector results in this run.")
        return

    tab_labels = [labels.get(c, c) for c in available]
    tabs = st.tabs(tab_labels)
    for tab, kind in zip(tabs, available):
        with tab:
            rows = by_collector[kind]
            view_key = f"{key_prefix}{kind}_view"
            filter_key = f"{key_prefix}{kind}_filter"
            search_key = f"{key_prefix}{kind}_search"
            sel_key = f"{key_prefix}{kind}_selected"

            vc1, vc2, vc3, vc4 = st.columns([1, 1, 2, 3])
            with vc1:
                view = st.segmented_control(
                    "View", ["Grid", "List"], key=view_key, label_visibility="collapsed",
                )
            with vc2:
                status_filter = st.segmented_control(
                    "Filter", ["All", "OK", "Failed"], key=filter_key, label_visibility="collapsed",
                )
            with vc3:
                url_search = st.text_input(
                    "Search", key=search_key, placeholder="Filter by URL...",
                    label_visibility="collapsed",
                )

            filtered = rows
            if status_filter == "OK":
                filtered = [r for r in filtered if r.get("status") == "ok"]
            elif status_filter == "Failed":
                filtered = [r for r in filtered if r.get("status") != "ok"]
            if url_search.strip():
                q = url_search.strip().lower()
                filtered = [r for r in filtered if q in r.get("url", "").lower()]

            if not filtered:
                st.info("No results match the current filters.")
                continue

            if view == "Grid":
                sel = render_results_grid(filtered, kind, output_dir, key_prefix=f"{key_prefix}{kind}_")
            else:
                sel = render_results_list(filtered, kind, output_dir, key_prefix=f"{key_prefix}{kind}_")

            if sel:
                # Map filtered indices back to original indices
                orig_indices = [rows.index(r) for r in sel]
                selected_rows[kind] = orig_indices
            elif sel_key in st.session_state and st.session_state[sel_key]:
                selected_rows[kind] = st.session_state[sel_key]
            else:
                selected_rows.pop(kind, None)


def page_dashboard() -> None:
    st.subheader("Dashboard")
    history = load_history()
    if not history:
        st.info("No runs yet. Start a capture to see metrics here.")
        return

    _render_metrics(history)
    st.markdown("---")

    fc1, fc2, fc3 = st.columns([2, 1, 1])
    with fc1:
        search = st.text_input(
            "Search", placeholder="Filter by URL...", key="dash_search", label_visibility="collapsed",
        )
    with fc2:
        kind_filter = st.selectbox(
            "Kind", ["All", "unified", "screenshot", "seo", "fast_seo", "extraction"],
            key="dash_kind_filter", label_visibility="collapsed",
        )
    with fc3:
        pass

    filtered_indices = _render_run_list(history, search, kind_filter)
    if not filtered_indices:
        st.info("No runs match the search.")
        return

    selected_run = st.selectbox(
        "Select a run", options=filtered_indices,
        format_func=lambda i: f"{history[i]['timestamp'][:19]} — {history[i].get('kind','?')} — {history[i].get('ok',0)}/{history[i].get('total',0)} OK",
        key="dash_run_selector",
    )
    entry = history[selected_run]
    st.caption(
        f"{entry['timestamp'][:19]} | {entry.get('total',0)} URLs | "
        f"{entry.get('ok',0)} OK | {entry.get('fail',0)} failed | "
        f"`{entry.get('output_dir','')}`"
    )

    if st.session_state.get("_dash_delete_idx"):
        delete_history_entry(selected_run)
        st.session_state.pop("_dash_delete_idx", None)
        st.rerun()

    selected_rows: dict[str, list[int]] = {}
    _render_action_bar(entry, selected_rows, key_prefix=f"dash_{selected_run}_")
    st.markdown("---")
    _render_collector_tabs(entry, selected_rows, key_prefix=f"dash_{selected_run}_")
