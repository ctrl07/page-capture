"""Results display components for capture runs."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd
import streamlit as st

from runners import FastRunnerLegacy, UnifiedRunner


def _empty_state(icon: str, title: str, message: str, action_label: str = "", action_callback=None) -> None:
    """Render a consistent empty state."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"# {icon}")
        st.markdown(f"## {title}")
        st.markdown(message)
        if action_label and action_callback:
            if st.button(action_label, type="primary", width="stretch"):
                action_callback()


def render_results(results: list[dict], kind: str, output_dir: Path, key_prefix: str = "") -> None:
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    fail_count = len(results) - ok_count

    tabs = st.tabs(["Summary", "Details", "Preview"])
    summary_tab, details_tab, preview_tab = tabs

    with summary_tab:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(results))
        c2.metric("OK", ok_count)
        c3.metric("Failed", fail_count)

    # Details Tab (filters + dataframe + item detail)
    filter_key = f"{key_prefix}filter_status"
    search_key = f"{key_prefix}filter_search"
    if filter_key not in st.session_state:
        st.session_state[filter_key] = "All"
    if search_key not in st.session_state:
        st.session_state[search_key] = ""

    with details_tab:
        fc1, fc2 = st.columns([1, 3])
        with fc1:
            status_filter = st.segmented_control(
                "Status", ["All", "OK", "Failed"],
                key=filter_key, label_visibility="collapsed",
            )
        with fc2:
            search = st.text_input(
                "Search URLs", key=search_key,
                placeholder="Filter by URL...",
                label_visibility="collapsed",
            )

        filtered = results
        if status_filter == "OK":
            filtered = [r for r in filtered if r.get("status") == "ok"]
        elif status_filter == "Failed":
            filtered = [r for r in filtered if r.get("status") != "ok"]
        if search.strip():
            q = search.strip().lower()
            filtered = [r for r in filtered if q in r.get("url", "").lower()]

        if not filtered:
            _empty_state(
                "🔍",
                "No results match",
                f"Try adjusting your filters or search.\n\n**Current filters:** Status: {status_filter}, Search: '{search}'",
            )
        else:
            df = pd.DataFrame(filtered)
            hide_cols = {"png", "pdf", "file"}
            dcols = [c for c in df.columns if c not in hide_cols]
            display_df = df[dcols] if dcols else df

            col_cfg: dict = {}
            if "url" in display_df.columns:
                col_cfg["url"] = st.column_config.LinkColumn("URL", pinned=True, width="large")
            if "status" in display_df.columns:
                col_cfg["status"] = st.column_config.TextColumn("Status", width="small")

            event = st.dataframe(
                display_df, width="stretch", hide_index=True,
                column_config=col_cfg or None,
                on_select="rerun", selection_mode="single-row",
                key=f"{key_prefix}df",
            )

            sel_rows = getattr(event, "selection", None)
            sel_rows = getattr(sel_rows, "rows", []) if sel_rows else []
            if sel_rows:
                idx = sel_rows[0]
                row = filtered[idx]
                st.markdown("---")
                st.markdown(f"**{row.get('url', '')}**")

                with st.expander("Details", expanded=True):
                    for k, v in row.items():
                        if k in ("png", "pdf", "file"):
                            continue
                        if isinstance(v, (dict, list)):
                            st.json(v)
                        else:
                            st.text(f"{k}: {v}")

                notes_key = f"{key_prefix}notes_{idx}"
                notes_val = st.session_state.get(notes_key, "")
                st.text_area("Notes", value=notes_val, key=notes_key, height=80)

            # Download buttons for filtered results
            st.markdown("---")
            if filtered:
                all_keys = list(dict.fromkeys(k for r in filtered for k in r))
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(filtered)
                st.download_button(
                    "Download Filtered (CSV)",
                    data=csv_buf.getvalue().encode(),
                    file_name=f"{kind}_results_filtered.csv",
                    mime="text/csv",
                    key=f"{key_prefix}dl_csv_filtered",
                    width="stretch",
                )

    with preview_tab:
        _empty_state(
            "📊",
            "Preview not available",
            "Preview is only available for screenshot results.",
        )


def render_unified_results(runner: UnifiedRunner | FastRunnerLegacy, key_prefix: str = "") -> None:
    output_dir = runner.output_dir
    collectors_attr = getattr(runner, "collectors", None)
    if collectors_attr:
        collectors = [c["name"] for c in collectors_attr]
    else:
        collectors = list(runner.results.keys())
    labels = {
        "seo": "Quick SEO",
        "extraction": "Custom Rules",
    }
    available = [c for c in collectors if c in runner.results]
    if not available:
        _empty_state(
            "📦",
            "No results available",
            "This run didn't produce any results. Check the run logs for errors.",
        )
        return

    tab_labels = [labels[c] if c in labels else c for c in available] + ["Summary"]
    tabs = st.tabs(tab_labels)
    for tab, kind in zip(tabs[:-1], available):
        with tab:
            render_results(runner.results[kind], kind, output_dir, key_prefix=f"{key_prefix}{kind}_")

    with tabs[-1]:
        total = sum(len(runner.results[c]) for c in available)
        ok = sum(1 for c in available for r in runner.results[c] if r.get("status") == "ok")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total steps", total)
        c2.metric("OK", ok)
        c3.metric("Failed", total - ok)
        st.caption(f"Output: `{output_dir}`")

        dl_cols = st.columns(2)
        with dl_cols[0]:
            if runner.results.get("seo"):
                all_keys = list(dict.fromkeys(k for r in runner.results["seo"] for k in r))
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(runner.results["seo"])
                st.download_button(
                    "SEO CSV",
                    data=csv_buf.getvalue().encode(),
                    file_name="seo_results.csv", mime="text/csv",
                    key=f"{key_prefix}dl_seo", width="stretch",
                )

                # Excel export (from data dir if available)
                data_dir = runner.output_dir / "data"
                xlsx_path = data_dir / "seo_results.xlsx"
                if xlsx_path.is_file():
                    with open(xlsx_path, "rb") as f:
                        st.download_button(
                            "Excel (.xlsx)",
                            data=f.read(),
                            file_name="seo_results.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"{key_prefix}dl_xlsx",
                            width="stretch",
                        )

                # JSON export
                json_path = data_dir / "seo_results.json"
                if json_path.is_file():
                    with open(json_path, "rb") as f:
                        st.download_button(
                            "JSON",
                            data=f.read(),
                            file_name="seo_results.json",
                            mime="application/json",
                            key=f"{key_prefix}dl_json",
                            width="stretch",
                        )

        with dl_cols[1]:
            if runner.results.get("extraction"):
                all_keys = list(dict.fromkeys(k for r in runner.results["extraction"] for k in r))
                csv_buf = io.StringIO()
                writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(runner.results["extraction"])
                st.download_button(
                    "Extraction CSV",
                    data=csv_buf.getvalue().encode(),
                    file_name="extraction_results.csv", mime="text/csv",
                    key=f"{key_prefix}dl_ext", width="stretch",
                )


def render_results_list(results: list[dict], kind: str, output_dir: Path, key_prefix: str = "") -> list[dict]:
    """List view with multi-row selection via dataframe."""
    df = pd.DataFrame(results)
    hide_cols = {"png", "pdf", "file"}
    dcols = [c for c in df.columns if c not in hide_cols]
    display_df = df[dcols] if dcols else df

    col_cfg: dict = {}
    if "url" in display_df.columns:
        col_cfg["url"] = st.column_config.LinkColumn("URL", pinned=True, width="large")
    if "status" in display_df.columns:
        col_cfg["status"] = st.column_config.TextColumn("Status", width="small")

    event = st.dataframe(
        display_df, width="stretch", hide_index=True,
        column_config=col_cfg or None,
        on_select="rerun", selection_mode="multi-row",
        key=f"{key_prefix}list_df",
    )

    sel_rows = getattr(event, "selection", None)
    sel_rows = getattr(sel_rows, "rows", []) if sel_rows else []
    if sel_rows:
        selected = [results[i] for i in sel_rows if i < len(results)]
        st.markdown(f"**{len(selected)} row(s) selected**")
        if kind in ("seo", "extraction"):
            csv_buf = io.StringIO()
            all_keys = list(dict.fromkeys(k for r in selected for k in r))
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(selected)
            st.download_button(
                "Download Selected (CSV)",
                data=csv_buf.getvalue().encode(),
                file_name=f"{kind}_selected.csv",
                mime="text/csv",
                key=f"{key_prefix}list_dl_csv",
                width="stretch",
            )
        return selected
    return []
