"""Dashboard — run management, preview, and re-queue."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from components.results_viewer import render_results_grid, render_results_list
from project import add_run_to_project, list_projects, remove_run_from_project
from runners import (
    build_zip,
    delete_history_entry,
    get_results,
    get_urls_from_results,
    load_history,
)


@st.dialog("Delete run")
def _delete_run_dialog(output_dir: str, entry_idx: int):
    st.write(f"Delete `{output_dir}`? This cannot be undone.")
    with st.container(horizontal=True):
        if st.button("Yes, delete", type="primary"):
            delete_history_entry(entry_idx)
            st.rerun()
        if st.button("Cancel"):
            st.rerun()


def _render_metrics(history: list[dict]) -> None:
    with st.container(horizontal=True):
        st.metric("Total Runs", len(history), border=True)
        st.metric("URLs Crawled", sum(h.get("total", 0) for h in history), border=True)
        st.metric("Succeeded", sum(h.get("ok", 0) for h in history), border=True)
        st.metric("Failed", sum(h.get("fail", 0) for h in history), border=True)


def _build_run_table(history: list[dict], search: str, kind_filter: str) -> pd.DataFrame:
    rows = []
    for i, entry in enumerate(history):
        if kind_filter != "All" and entry.get("kind", "").lower() != kind_filter.lower():
            continue
        if search.strip():
            q = search.strip().lower()
            by_collector = get_results(entry)
            urls = [r.get("url", "") for rows_c in by_collector.values() for r in rows_c]
            if not any(q in u.lower() for u in urls) and q not in entry.get("kind", "").lower():
                continue

        kind = entry.get("kind", "?")
        kind_label = {
            "unified": "Unified",
            "screenshot": "Screenshots",
            "seo": "Quick SEO",
            "fast_seo": "Fast SEO",
            "extraction": "Extraction",
            "blog_audit": "Blog Audit",
        }.get(kind, kind)

        total = entry.get("total", 0)
        ok = entry.get("ok", 0)
        fail = entry.get("fail", 0)
        success_rate = f"{(ok / total * 100):.0f}%" if total else "—"

        rows.append({
            "idx": i,
            "timestamp": entry.get("timestamp", "")[:19],
            "kind": kind_label,
            "urls": total,
            "ok": ok,
            "fail": fail,
            "success_rate": success_rate,
            "duration": entry.get("duration", "—"),
            "output_dir": entry.get("output_dir", ""),
        })

    if not rows:
        return pd.DataFrame(columns=["idx", "timestamp", "kind", "urls", "ok", "fail", "success_rate", "duration", "output_dir"])

    return pd.DataFrame(rows)


def _render_run_table(df: pd.DataFrame) -> int | None:
    if df.empty:
        st.info("No runs match the current filters.")
        return None

    col_config = {
        "idx": None,
        "timestamp": st.column_config.TextColumn("Date / Time", width="medium"),
        "kind": st.column_config.TextColumn("Type", width="small"),
        "urls": st.column_config.NumberColumn("URLs", width="small", format="%d"),
        "ok": st.column_config.NumberColumn("✓ OK", width="small", format="%d"),
        "fail": st.column_config.NumberColumn("✗ Fail", width="small", format="%d"),
        "success_rate": st.column_config.TextColumn("Success", width="small"),
        "duration": st.column_config.TextColumn("Duration", width="small"),
        "output_dir": st.column_config.TextColumn("Output Folder", width="medium"),
    }

    event = st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config=col_config,
        column_order=["timestamp", "kind", "urls", "ok", "fail", "success_rate", "duration", "output_dir"],
        on_select="rerun",
        selection_mode="single-row",
        key="dash_run_table",
    )

    sel_rows = getattr(event, "selection", None)
    sel_rows = getattr(sel_rows, "rows", []) if sel_rows else []
    if sel_rows:
        return df.iloc[sel_rows[0]]["idx"]
    return None


def _render_run_detail_drawer(entry: dict, selected_rows: dict[str, list[int]], key_prefix: str, entry_idx: int = 0) -> None:
    by_collector = get_results(entry)
    output_dir = Path(entry.get("output_dir", ""))
    collectors = entry.get("collectors", list(by_collector.keys()))
    labels = {"screenshot": "Screenshots", "seo": "Quick SEO", "extraction": "Custom Rules", "blog_audit": "Blog Audit"}
    available = [c for c in collectors if by_collector.get(c)]

    st.markdown("---")
    st.markdown(f"### Run Details — {entry.get('timestamp', '')[:19]}")

    with st.container(horizontal=True):
        st.metric("Total URLs", entry.get("total", 0), border=True)
        st.metric("Passed", entry.get("ok", 0), border=True)
        st.metric("Failed", entry.get("fail", 0), border=True)
        st.metric("Collectors", len(available), border=True)

    if entry.get("duration"):
        st.caption(f"Duration: {entry['duration']}")
    if entry.get("fast_mode"):
        st.caption(":material/bolt: Fast mode (curl_cffi)")
    if entry.get("extraction_rules"):
        st.caption(f"Extraction rules: {len(entry['extraction_rules'])} fields")

    # ── Project assignment ──────────────────────────────────────────────────
    projects = list_projects()
    current_project_ids = [
        p["id"] for p in projects
        if load_history().index(entry) in p.get("run_indices", [])
    ]
    entry_idx = load_history().index(entry)

    with st.container(border=True):
        st.markdown("**Project**")
        if current_project_ids:
            assigned = [p for p in projects if p["id"] in current_project_ids]
            st.caption(f"In: {', '.join(p['name'] for p in assigned)}")
        else:
            st.caption("Not assigned to any project")

        proj_names = ["(None)"] + [p["name"] for p in projects]
        selected = st.selectbox(
            "Add to project", proj_names,
            key=f"dash_proj_add_{entry_idx}",
            label_visibility="collapsed",
        )
        if selected and selected != "(None)":
            project = next(p for p in projects if p["name"] == selected)
            if add_run_to_project(project["id"], entry_idx):
                st.success(f"Added to '{selected}'")
                st.rerun()

        if current_project_ids:
            if st.button("Remove from current project", key=f"dash_proj_rm_{entry_idx}"):
                for pid in current_project_ids:
                    remove_run_from_project(pid, entry_idx)
                st.rerun()

    st.markdown("---")

    with st.container(horizontal=True):
        rerun_urls = []
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
            type="primary",
        ):
            st.session_state.capture_urls = rerun_urls
            if entry.get("collectors"):
                st.session_state.restore_collectors = entry["collectors"]
            if entry.get("extraction_rules"):
                st.session_state.restore_extraction_rules = entry["extraction_rules"]
            if entry.get("fast_mode"):
                st.session_state.restore_fast_mode = True
            if entry.get("kind") == "crawl4ai_seo":
                st.session_state.restore_crawl_config = entry.get("crawl_config", {})
            st.session_state["_newrun_from_dashboard"] = True
            st.rerun()

        all_urls = get_urls_from_results(entry)
        if st.button(
            f"Re-capture all ({len(all_urls)})",
            disabled=not all_urls,
            key=f"{key_prefix}recapture",
        ):
            st.session_state.capture_urls = all_urls
            if entry.get("collectors"):
                st.session_state.restore_collectors = entry["collectors"]
            if entry.get("extraction_rules"):
                st.session_state.restore_extraction_rules = entry["extraction_rules"]
            if entry.get("fast_mode"):
                st.session_state.restore_fast_mode = True
            if entry.get("kind") == "crawl4ai_seo":
                st.session_state.restore_crawl_config = entry.get("crawl_config", {})
            st.session_state["_newrun_from_dashboard"] = True
            st.rerun()

        if st.button("Delete", key=f"{key_prefix}del", type="secondary"):
            _delete_run_dialog(entry.get("output_dir", ""), entry_idx)

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
                key=f"{key_prefix}dl_csv",
            )

        has_screenshot = "screenshot" in by_collector and by_collector["screenshot"]
        if has_screenshot:
            st.download_button(
                "ZIP", data=build_zip(by_collector["screenshot"], output_dir),
                file_name="screenshots.zip", mime="application/zip",
                key=f"{key_prefix}dl_zip",
            )

    if not available:
        st.info("No collector results in this run.")
        return

    tabs = st.tabs([labels.get(c, c) for c in available] + ["Summary"])
    for tab, kind in zip(tabs[:-1], available):
        with tab:
            rows = by_collector[kind]
            view_key = f"{key_prefix}{kind}_view"
            filter_key = f"{key_prefix}{kind}_filter"
            search_key = f"{key_prefix}{kind}_search"
            sel_key = f"{key_prefix}{kind}_selected"

            vc1, vc2, vc3, vc4 = st.columns([1, 1, 2, 3])
            with vc1:
                view = st.segmented_control("View", ["Grid", "List"], key=view_key, label_visibility="collapsed")
            with vc2:
                status_filter = st.segmented_control("Filter", ["All", "OK", "Failed"], key=filter_key, label_visibility="collapsed")
            with vc3:
                url_search = st.text_input("Search", key=search_key, placeholder="Filter by URL...", label_visibility="collapsed")

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
                orig_indices = [rows.index(r) for r in sel]
                selected_rows[kind] = orig_indices
            elif sel_key in st.session_state and st.session_state[sel_key]:
                selected_rows[kind] = st.session_state[sel_key]
            else:
                selected_rows.pop(kind, None)

    with tabs[-1]:
        total = sum(len(by_collector[c]) for c in available)
        ok = sum(1 for c in available for r in by_collector[c] if r.get("status") == "ok")
        with st.container(horizontal=True):
            st.metric("Total steps", total, border=True)
            st.metric("OK", ok, border=True)
            st.metric("Failed", total - ok, border=True)
        st.caption(f"Output: `{output_dir}`")

        dl_cols = st.columns(3)
        with dl_cols[0]:
            if by_collector.get("screenshot"):
                st.download_button(
                    "Screenshots ZIP",
                    data=build_zip(by_collector["screenshot"], output_dir),
                    file_name="screenshots.zip", mime="application/zip",
                    key=f"{key_prefix}zip", width="stretch",
                )
        with dl_cols[1]:
            if by_collector.get("seo"):
                all_keys = list(dict.fromkeys(k for r in by_collector["seo"] for k in r))
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(by_collector["seo"])
                st.download_button(
                    "SEO CSV",
                    data=csv_buf.getvalue().encode(),
                    file_name="seo_results.csv", mime="text/csv",
                    key=f"{key_prefix}dl_seo", width="stretch",
                )
        with dl_cols[2]:
            if by_collector.get("extraction"):
                all_keys = list(dict.fromkeys(k for r in by_collector["extraction"] for k in r))
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(by_collector["extraction"])
                st.download_button(
                    "Extraction CSV",
                    data=csv_buf.getvalue().encode(),
                    file_name="extraction_results.csv", mime="text/csv",
                    key=f"{key_prefix}dl_ext", width="stretch",
                )


def page_dashboard() -> None:
    st.subheader("Dashboard")
    history = load_history()
    if not history:
        st.info("No runs yet. Start a capture to see metrics here.")
        return

    _render_metrics(history)
    st.markdown("---")

    fc1, fc2, fc3 = st.columns([2, 1, 1], gap="small")
    with fc1:
        search = st.text_input("Search", placeholder="Filter by URL...", key="dash_search", label_visibility="collapsed")
    with fc2:
        kind_filter = st.selectbox(
            "Kind", ["All", "unified", "screenshot", "seo", "fast_seo", "extraction"],
            key="dash_kind_filter", label_visibility="collapsed",
        )
    with fc3:
        project_filter = st.selectbox(
            "Project", ["All"] + [p["name"] for p in list_projects()],
            key="dash_project_filter", label_visibility="collapsed",
        )

    # Filter by project
    if project_filter != "All":
        project = next((p for p in list_projects() if p["name"] == project_filter), None)
        if project:
            project_indices = set(project.get("run_indices", []))
            history = [h for i, h in enumerate(history) if i in project_indices]

    df = _build_run_table(history, search, kind_filter)
    selected_idx = _render_run_table(df)

    if selected_idx is None:
        st.info("Select a run from the table to view details and actions.")
        return

    entry = history[selected_idx]
    st.caption(
        f"{entry['timestamp'][:19]} | {entry.get('total', 0)} URLs | "
        f"{entry.get('ok', 0)} OK | {entry.get('fail', 0)} failed | "
        f"`{entry.get('output_dir', '')}`"
    )

    selected_rows: dict[str, list[int]] = {}
    _render_run_detail_drawer(entry, selected_rows, key_prefix=f"dash_{selected_idx}_", entry_idx=selected_idx)
