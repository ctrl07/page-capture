"""Content page — view extracted main content from trafilatura."""

from __future__ import annotations

import json

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


def _content_diff(text1: str, text2: str) -> list[tuple[str, str]]:
    """Simple diff returning list of (type, line) where type is ' ', '+', '-'."""
    import difflib
    lines1 = text1.splitlines()
    lines2 = text2.splitlines()
    diff = list(difflib.unified_diff(lines1, lines2, lineterm=""))
    result = []
    for line in diff:
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        if line.startswith("-"):
            result.append(("-", line[1:]))
        elif line.startswith("+"):
            result.append(("+", line[1:]))
        else:
            result.append((" ", line[1:] if line.startswith(" ") else line))
    return result


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

    # ── Toolbar ────────────────────────────────────────────────────────
    with st.container(horizontal=True):
        st.markdown(f"**{len(filtered_rows)} page(s)**")
        c1, c2, c3 = st.columns([1, 1, 4])
        with c1:
            if st.button("Export All (.zip)", key="content_export_all", width="stretch"):
                _export_batch(filtered_rows, output_format)
        with c2:
            if st.button("Compare Two", key="content_compare", width="stretch"):
                st.session_state["content_compare_mode"] = True
                st.rerun()

    # Compare mode
    if st.session_state.get("content_compare_mode"):
        _render_compare_mode(filtered_rows, output_format, show_metadata)
        return

    # ── URL List ──────────────────────────────────────────────────────
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


def _export_batch(rows: list[dict], fmt: str) -> None:
    """Export all filtered rows as a zip file."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            url = r.get("url", "unknown")
            safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
            if fmt == "Clean Text":
                content = r.get("main_content", "")
                ext = "txt"
            elif fmt == "Markdown":
                content = r.get("main_content_formatted") or r.get("main_content", "")
                ext = "md"
            elif fmt == "JSON":
                content = json.dumps({
                    "url": url,
                    "title": r.get("title_trafilatura"),
                    "author": r.get("author"),
                    "date": r.get("publish_date"),
                    "sitename": r.get("sitename"),
                    "language": r.get("metadata_language"),
                    "content": r.get("main_content"),
                }, indent=2)
                ext = "json"
            else:
                content = r.get("content_html", "") or r.get("main_content", "")
                ext = "html"
            zf.writestr(f"{safe_name}.{ext}", content)

    buf.seek(0)
    st.download_button(
        f"Download {len(rows)} files (.zip)",
        data=buf.getvalue(),
        file_name=f"content_export_{fmt.lower().replace(' ', '_')}.zip",
        mime="application/zip",
        key="content_batch_download",
        width="stretch",
        type="primary",
    )


def _render_compare_mode(rows: list[dict], fmt: str, show_meta: bool) -> None:
    """Render side-by-side content comparison."""
    st.markdown("### Compare Two Pages")

    options = [r.get("url", "") for r in rows]
    c1, c2 = st.columns(2)
    with c1:
        url_a = st.selectbox("Page A", options, key="content_compare_a")
    with c2:
        url_b = st.selectbox("Page B", options, key="content_compare_b")

    if st.button("Exit Compare Mode", key="content_compare_exit"):
        st.session_state.pop("content_compare_mode", None)
        st.rerun()

    if url_a == url_b:
        st.warning("Select two different pages to compare")
        return

    row_a = next(r for r in rows if r.get("url") == url_a)
    row_b = next(r for r in rows if r.get("url") == url_b)

    # Get content based on format
    if fmt == "Clean Text":
        content_a = row_a.get("main_content", "")
        content_b = row_b.get("main_content", "")
    elif fmt == "Markdown":
        content_a = row_a.get("main_content_formatted") or row_a.get("main_content", "")
        content_b = row_b.get("main_content_formatted") or row_b.get("main_content", "")
    else:
        content_a = row_a.get("main_content", "")
        content_b = row_b.get("main_content", "")

    # Metadata comparison
    if show_meta:
        st.markdown("#### Metadata Comparison")
        mc1, mc2 = st.columns(2)
        with mc1:
            st.caption(f"**{url_a}**")
            st.caption(f"Words: {row_a.get('main_content_word_count', 0)}")
            st.caption(f"Lang: {row_a.get('metadata_language', '?')}")
            st.caption(f"Author: {row_a.get('author', '—')}")
        with mc2:
            st.caption(f"**{url_b}**")
            st.caption(f"Words: {row_b.get('main_content_word_count', 0)}")
            st.caption(f"Lang: {row_b.get('metadata_language', '?')}")
            st.caption(f"Author: {row_b.get('author', '—')}")

    # Diff view
    st.markdown("#### Content Diff")
    diff = _content_diff(content_a, content_b)

    # Show unified diff
    diff_lines = []
    for typ, line in diff:
        if typ == "-":
            diff_lines.append(f"- {line}")
        elif typ == "+":
            diff_lines.append(f"+ {line}")
        else:
            diff_lines.append(f"  {line}")

    if len(diff_lines) > 200:
        st.caption(f"Showing first 200 lines of {len(diff_lines)} diff lines")
        diff_lines = diff_lines[:200]

    st.code("\n".join(diff_lines), language="diff", line_numbers=True)
