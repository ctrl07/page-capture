"""Content page — view extracted main content from trafilatura."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from runners import load_history


def _get_content_runs():
    """Get all runs that have trafilatura content data."""
    history = load_history()
    content_runs = []
    for i, h in enumerate(history):
        kind = h.get("kind", "")
        if kind in ("fast_seo", "unified", "seo"):
            # Check if any results have main_content field
            results = h.get("results", [])
            if results and any(r.get("main_content") for r in results):
                content_runs.append((i, h))
            # Also check results_by_collector for unified runs
            elif kind == "unified":
                by_collector = h.get("results_by_collector", {})
                for rows in by_collector.values():
                    if any(r.get("main_content") for r in rows):
                        content_runs.append((i, h))
                        break
    return content_runs


def _extract_content_rows(entry: dict) -> list[dict]:
    """Extract all rows with main_content from a history entry."""
    rows = []
    kind = entry.get("kind", "")
    if kind == "unified":
        by_collector = entry.get("results_by_collector", {})
        for collector, collector_rows in by_collector.items():
            for r in collector_rows:
                if r.get("main_content"):
                    r["_collector"] = collector
                    rows.append(r)
    else:
        results = entry.get("results", [])
        for r in results:
            if r.get("main_content"):
                rows.append(r)
    return rows


def page_content() -> None:
    st.subheader("Content")
    st.caption("View clean extracted main content from crawled pages (trafilatura).")

    # ── Source Selection ──────────────────────────────────────────────
    source_tabs = st.tabs(["Current Run", "History"])

    content_rows = []

    with source_tabs[0]:
        if st.session_state.get("unified_runner"):
            runner = st.session_state.unified_runner
            if runner.results:
                if hasattr(runner, "results") and isinstance(runner.results, dict):
                    for collector, rows in runner.results.items():
                        for r in rows:
                            if r.get("main_content"):
                                r["_collector"] = collector
                                content_rows.append(r)
                else:
                    for r in runner.results:
                        if r.get("main_content"):
                            content_rows.append(r)

            if content_rows:
                _ = "Current run"
                _ = str(runner.output_dir)
                st.success(f"Using current run — {len(content_rows)} pages with content")
            else:
                st.info("Current run has no trafilatura content data")
        else:
            st.info("No active run")

    with source_tabs[1]:
        content_runs = _get_content_runs()
        if content_runs:
            labels = [
                f"{h['timestamp'][:19]} — {h.get('kind', '?').upper()} — {len(_extract_content_rows(h))} pages"
                for _, h in content_runs
            ]
            selected = st.selectbox("Select a run", labels, key="content_run_select")
            if selected:
                idx = labels.index(selected)
                _, entry = content_runs[idx]
                content_rows = _extract_content_rows(entry)
                st.success(f"Loaded {len(content_rows)} pages with content")
        else:
            st.info("No runs with trafilatura content data found")

    if not content_rows:
        return

    # ── Format & Filter Controls ──────────────────────────────────────
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
        with c1:
            output_format = st.selectbox(
                "Format",
                ["Clean Text", "Markdown", "JSON", "Raw HTML"],
                key="content_format",
                help="How to display the content",
            )
        with c2:
            languages = sorted(set(r.get("metadata_language", "") for r in content_rows if r.get("metadata_language")))
            lang_filter = st.selectbox(
                "Language",
                ["All"] + languages,
                key="content_lang_filter",
            )
        with c3:
            show_metadata = st.toggle("Show metadata", value=True, key="content_show_meta")
        with c4:
            search = st.text_input("Search URLs", placeholder="Filter by URL...", key="content_search")

    # Filter rows
    filtered_rows = content_rows
    if lang_filter != "All":
        filtered_rows = [r for r in filtered_rows if r.get("metadata_language") == lang_filter]
    if search.strip():
        q = search.strip().lower()
        filtered_rows = [r for r in filtered_rows if q in r.get("url", "").lower()]

    if not filtered_rows:
        st.info("No pages match the current filters")
        return

    # ── URL List ──────────────────────────────────────────────────────
    st.markdown(f"**{len(filtered_rows)} page(s)**")

    # Build display dataframe
    df_data = []
    for r in filtered_rows:
        url = r.get("url", "")
        wc = r.get("main_content_word_count", 0)
        lang = r.get("metadata_language", "?")
        title = r.get("title_trafilatura") or r.get("title", "")[:60]
        author = r.get("author", "")
        date = r.get("publish_date", "")
        df_data.append({
            "url": url,
            "title": title,
            "words": wc,
            "lang": lang,
            "author": author,
            "date": date,
        })

    df = pd.DataFrame(df_data)

    # Configure columns
    col_cfg = {
        "url": st.column_config.LinkColumn("URL", pinned=True, width="large"),
        "title": st.column_config.TextColumn("Title", width="large"),
        "words": st.column_config.NumberColumn("Words", width="small", format="%d"),
        "lang": st.column_config.TextColumn("Lang", width="small"),
        "author": st.column_config.TextColumn("Author", width="medium"),
        "date": st.column_config.TextColumn("Published", width="small"),
    }

    event = st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config=col_cfg,
        on_select="rerun",
        selection_mode="single-row",
        key="content_url_table",
    )

    sel_rows = getattr(event, "selection", None)
    sel_rows = getattr(sel_rows, "rows", []) if sel_rows else []

    if not sel_rows:
        st.info("Click a row to view content")
        return

    # ── Content Viewer ────────────────────────────────────────────────
    selected_row = filtered_rows[sel_rows[0]]
    url = selected_row.get("url", "")

    st.markdown("---")
    st.markdown(f"### {url}")

    # Metadata section
    if show_metadata:
        with st.expander("Metadata", expanded=True):
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Words", selected_row.get("main_content_word_count", 0))
            with m2:
                st.metric("Language", selected_row.get("metadata_language", "?"))
            with m3:
                st.caption(f"Author: {selected_row.get('author', '—')}")
            with m4:
                st.caption(f"Published: {selected_row.get('publish_date', '—')}")

            st.caption(f"Site: {selected_row.get('sitename', '—')}")
            st.caption(f"Fingerprint: {selected_row.get('fingerprint', '—')[:16]}...")

    # Content display
    if output_format == "Clean Text":
        content = selected_row.get("main_content", "")
        st.text_area("Content", value=content, height=400, key=f"content_text_{url}")
    elif output_format == "Markdown":
        content = selected_row.get("main_content_formatted") or selected_row.get("main_content", "")
        st.markdown(content)
    elif output_format == "JSON":
        st.json({
            "url": url,
            "title": selected_row.get("title_trafilatura"),
            "author": selected_row.get("author"),
            "date": selected_row.get("publish_date"),
            "sitename": selected_row.get("sitename"),
            "language": selected_row.get("metadata_language"),
            "categories": selected_row.get("categories", "").split(" | ") if selected_row.get("categories") else [],
            "tags": selected_row.get("tags", "").split(" | ") if selected_row.get("tags") else [],
            "content": selected_row.get("main_content"),
            "fingerprint": selected_row.get("fingerprint"),
        })
    elif output_format == "Raw HTML":
        content = selected_row.get("content_html", "") or selected_row.get("main_content", "")
        st.code(content, language="html", line_numbers=True)

    # Download buttons
    c1, c2 = st.columns(2)
    with c1:
        content = selected_row.get("main_content", "")
        st.download_button(
            "Download .txt",
            data=content.encode(),
            file_name=f"{url.replace('https://', '').replace('/', '_')}.txt",
            mime="text/plain",
            key=f"dl_txt_{url}",
            width="stretch",
        )
    with c2:
        content = selected_row.get("main_content_formatted") or selected_row.get("main_content", "")
        st.download_button(
            "Download .md",
            data=content.encode(),
            file_name=f"{url.replace('https://', '').replace('/', '_')}.md",
            mime="text/markdown",
            key=f"dl_md_{url}",
            width="stretch",
        )
