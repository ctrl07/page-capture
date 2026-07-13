"""Page Capture — Desktop app for screenshots and SEO extraction."""

from __future__ import annotations

import csv
import io
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from extraction import (
    render_rules_editor,
)
from importers import (
    import_from_csv_file,
    import_from_sitemap_url,
    import_from_sitemap_xml,
    import_from_wp_xml,
    is_valid_url,
    parse_urls_text,
)
from page_capture import load_config
from runners import (
    HERE,
    CaptureRunner,
    ExtractionRunner,
    UnifiedRunner,
    build_runtime_config,
    build_zip,
    delete_history_entry,
    load_history,
)

CONFIG = load_config(HERE / "config.yaml")

# ── Session state init ──

def _init_session_state() -> None:
    defaults = {
        "runner": None,
        "running": False,
        "capture_urls": None,
        "extraction_rules": [],
        "extraction_runner": None,
        "unified_runner": None,
        "unified_running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Shared helpers ──

def _run_with_progress(runner: CaptureRunner | ExtractionRunner | UnifiedRunner, key_prefix: str, label: str = "") -> None:
    """Generic progress loop for any runner with _thread, results, cancelled."""
    status_placeholder = st.empty()
    progress_bar = st.progress(0)
    if st.button("Cancel", key=f"cancel_{key_prefix}"):
        runner.cancelled = True

    if not runner._thread or not runner._thread.is_alive():
        runner._thread = threading.Thread(target=runner.run, daemon=True)
        runner._thread.start()

    start_time = time.time()
    last_done = 0
    last_tick = start_time
    avg_secs_per_item = 0.0
    alive = True
    while alive:
        alive = runner._thread.is_alive()
        done = getattr(runner, "progress_done", len(getattr(runner, "results", [])))
        total = getattr(runner, "progress_total", len(getattr(runner, "urls", [])))
        pct = min(done / total, 1.0) if total else 0
        now = time.time()
        elapsed = now - start_time

        # Update rolling average of time-per-item
        if done > last_done:
            delta = now - last_tick
            items_done = done - last_done
            item_rate = delta / items_done
            if avg_secs_per_item == 0:
                avg_secs_per_item = item_rate
            else:
                # Exponential moving average: weight recent items 60%
                avg_secs_per_item = 0.4 * avg_secs_per_item + 0.6 * item_rate
            last_tick = now
            last_done = done

        # ETA
        eta_text = ""
        if done > 0 and total > done and avg_secs_per_item > 0:
            eta_secs = int(avg_secs_per_item * (total - done))
            if eta_secs >= 60:
                eta_text = f" | ETA ~{eta_secs // 60}m {eta_secs % 60}s"
            else:
                eta_text = f" | ETA ~{eta_secs}s"

        # Elapsed time
        elapsed_m = int(elapsed) // 60
        elapsed_s = int(elapsed) % 60
        elapsed_text = f"{elapsed_m}m {elapsed_s}s" if elapsed_m else f"{elapsed_s}s"

        progress_bar.progress(pct, text=f"{done}/{total} | {elapsed_text} elapsed{eta_text}")
        status_msg = runner.status if hasattr(runner, "status") and runner.status else label
        if status_msg:
            status_placeholder.caption(status_msg)
        if not alive:
            break
        time.sleep(0.3)


def render_results(results: list[dict], kind: str, output_dir: Path, key_prefix: str = "") -> None:
    ok_count = sum(1 for r in results if r.get("status") == "ok")
    fail_count = len(results) - ok_count

    tabs = st.tabs(["Summary", "Details", "Preview"])

    with tabs[0]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(results))
        c2.metric("OK", ok_count)
        c3.metric("Failed", fail_count)

    with tabs[1]:
        # ── Filters ──
        filter_key = f"{key_prefix}filter_status"
        search_key = f"{key_prefix}filter_search"
        if filter_key not in st.session_state:
            st.session_state[filter_key] = "All"
        if search_key not in st.session_state:
            st.session_state[search_key] = ""

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

        # ── Apply filters ──
        filtered = results
        if status_filter == "OK":
            filtered = [r for r in filtered if r.get("status") == "ok"]
        elif status_filter == "Failed":
            filtered = [r for r in filtered if r.get("status") != "ok"]
        if search.strip():
            q = search.strip().lower()
            filtered = [r for r in filtered if q in r.get("url", "").lower()]

        if not filtered:
            st.info("No results match the current filters.")
        else:
            df = pd.DataFrame(filtered)
            hide_cols = {"png", "pdf", "file"}
            dcols = [c for c in df.columns if c not in hide_cols]
            display_df = df[dcols] if dcols else df

            col_cfg: dict = {}
            if "url" in display_df.columns:
                col_cfg["url"] = st.column_config.LinkColumn("URL", pinned=True)
            if "status" in display_df.columns:
                col_cfg["status"] = st.column_config.TextColumn("Status")

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
                        st.text(f"{k}: {v}")

                notes_key = f"{key_prefix}notes_{idx}"
                notes_val = st.session_state.get(notes_key, "")
                st.text_area("Notes", value=notes_val, key=notes_key, height=80)

                if kind == "screenshot":
                    png_path = Path(row.get("file", ""))
                    if png_path.exists():
                        st.image(str(png_path), width="stretch")
                    pdf_path = Path(row.get("pdf", ""))
                    if pdf_path.exists():
                        with open(pdf_path, "rb") as f:
                            st.download_button(
                                "Download PDF", data=f,
                                file_name=pdf_path.name, mime="application/pdf",
                                key=f"{key_prefix}preview_pdf_{idx}",
                            )

        if kind == "screenshot" and filtered:
            zip_key = f"{key_prefix}zip_data"
            if zip_key not in st.session_state:
                st.session_state[zip_key] = build_zip(filtered, output_dir)
            st.download_button(
                "Download ZIP", data=st.session_state[zip_key],
                file_name="screenshots.zip", mime="application/zip",
                key=f"{key_prefix}dl_zip",
            )
        if kind in ("seo", "extraction") and filtered:
            all_keys = list(dict.fromkeys(k for r in filtered for k in r))
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(filtered)
            st.download_button(
                "Download CSV", data=csv_buf.getvalue().encode(),
                file_name=f"{kind}_results.csv", mime="text/csv",
                key=f"{key_prefix}dl_csv",
            )

    with tabs[2]:
        if kind == "screenshot":
            indexed = [
                (r.get("file", ""), i)
                for i, r in enumerate(results)
                if r.get("file") and Path(r.get("file", "")).exists()
            ]
            if not indexed:
                st.info("No screenshots available.")
            else:
                selected = st.selectbox(
                    "Choose screenshot", options=[f for f, _ in indexed],
                    format_func=lambda x: Path(x).name, key=f"{key_prefix}preview_sel",
                )
                if selected:
                    st.image(selected, width="stretch")
                    col_png, col_pdf = st.columns(2)
                    with col_png:
                        with open(selected, "rb") as f:
                            st.download_button(
                                "Download PNG", data=f,
                                file_name=Path(selected).name,
                                mime="image/png", key=f"{key_prefix}preview_dl",
                            )
                    sel_idx = next(i for f, i in indexed if f == selected)
                    pdf_file = results[sel_idx].get("pdf", "")
                    if pdf_file and Path(pdf_file).exists():
                        with col_pdf:
                            with open(pdf_file, "rb") as f:
                                st.download_button(
                                    "Download PDF", data=f,
                                    file_name=Path(pdf_file).name,
                                    mime="application/pdf", key=f"{key_prefix}preview_pdf_dl",
                                )
        else:
            st.info("Preview not available for this result type.")


# ── Page functions ──

def _render_unified_results(runner: UnifiedRunner, key_prefix: str = "") -> None:
    output_dir = runner.output_dir
    collectors = [c["name"] for c in runner.collectors]
    labels = {
        "screenshot": "Screenshots", "seo": "Quick SEO",
        "extraction": "Custom Rules",
    }
    available = [c for c in collectors if runner.results.get(c)]
    if not available:
        st.info("No collector produced results.")
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

        # Download buttons in summary tab too
        dl_cols = st.columns(3)
        with dl_cols[0]:
            if runner.results.get("screenshot"):
                st.download_button(
                    "Screenshots ZIP",
                    data=build_zip(runner.results["screenshot"], output_dir),
                    file_name="screenshots.zip", mime="application/zip",
                    key=f"{key_prefix}zip", use_container_width=True,
                )
        with dl_cols[1]:
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
                    key=f"{key_prefix}dl_seo", use_container_width=True,
                )
        with dl_cols[2]:
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
                    key=f"{key_prefix}dl_ext", use_container_width=True,
                )


def page_import() -> None:
    st.subheader("Import URLs")
    source = st.radio("Source", [
        "Manual (text area)", "Sitemap URL", "Paste sitemap XML",
        "CSV file (upload)", "WordPress XML (upload)",
    ], horizontal=True, key="import_source")

    urls: list[str] = []

    if source == "Manual (text area)":
        raw = st.text_area("URLs (one per line)", height=200, placeholder="https://example.com\nhttps://example.org", key="import_manual")
        if raw:
            urls = parse_urls_text(raw)
    elif source == "Sitemap URL":
        sitemap_url = st.text_input("Sitemap URL", placeholder="https://example.com/sitemap.xml", key="import_sitemap_url")
        if sitemap_url and st.button("Fetch & Parse", key="import_sitemap_fetch"):
            with st.spinner("Fetching sitemap..."):
                try:
                    urls = import_from_sitemap_url(sitemap_url)
                    st.success(f"Found {len(urls)} URLs")
                except Exception as e:
                    st.error(f"Failed: {e}")
    elif source == "Paste sitemap XML":
        raw_xml = st.text_area("Paste sitemap XML", height=250, key="import_sitemap_xml")
        if raw_xml and st.button("Parse", key="import_sitemap_parse"):
            try:
                urls = import_from_sitemap_xml(raw_xml)
                st.success(f"Found {len(urls)} URLs")
            except Exception as e:
                st.error(f"Failed: {e}")
    elif source == "CSV file (upload)":
        uploaded = st.file_uploader("Upload CSV", type=["csv", "txt"], key="import_csv")
        if uploaded:
            raw = uploaded.read().decode("utf-8", errors="replace")
            pairs = import_from_csv_file(raw)
            if pairs:
                has_second = any(b is not None for _, b in pairs)
                if has_second:
                    st.info("CSV has two columns — only using first column for capture")
                urls = [a for a, _ in pairs]
                st.success(f"Found {len(urls)} URLs from CSV")
            else:
                st.error("No valid URLs found in CSV")
    elif source == "WordPress XML (upload)":
        uploaded = st.file_uploader("Upload WordPress XML export", type=["xml"], key="import_wp")
        if uploaded:
            raw = uploaded.read()
            try:
                posts = import_from_wp_xml(raw)
                urls = [p["url"] for p in posts]
                st.success(f"Found {len(urls)} posts/pages from WordPress export")
                with st.expander("Preview posts"):
                    st.dataframe(pd.DataFrame(posts)[["title", "url", "date", "category"]])
            except Exception as e:
                st.error(f"Failed: {e}")

    if urls:
        n_invalid = sum(1 for u in urls if not is_valid_url(u))
        st.caption(f"{len(urls)} URL(s) loaded" + (f", {n_invalid} invalid (will be skipped)" if n_invalid else ""))
        with st.expander("Preview loaded URLs"):
            st.dataframe(pd.DataFrame({"url": urls}), width="stretch", hide_index=True)
        if st.button("Add to URL Queue", key="to_unified"):
            existing = st.session_state.get("capture_urls") or []
            merged = list(dict.fromkeys(existing + urls))
            st.session_state.capture_urls = merged
            st.rerun()


def page_extraction() -> None:
    st.subheader("Data Extraction")
    extract_mode = st.radio("Mode", ["Quick SEO", "Custom Rules"], horizontal=True, key="extract_mode")

    if extract_mode == "Quick SEO":
        st.caption("Extracts title, meta description, H1/H2/H3, Open Graph tags, schema markup, word count, link counts, and images missing alt text.")
        default_seo = ""
        if st.session_state.get("capture_urls"):
            default_seo = "\n".join(st.session_state.capture_urls)
        with st.form("seo_form"):
            urls_text_seo = st.text_area("URLs (one per line)", height=150, placeholder="https://example.com\nhttps://example.org", value=default_seo, key="seo_urls")
            seo_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="seo_delay")
            seo_output_name = st.text_input("Output folder name", value=f"seo_{datetime.now().strftime('%Y%m%d_%H%M%S')}", key="seo_output")
            seo_submitted = st.form_submit_button("Run SEO Extraction", disabled=st.session_state.running or st.session_state.unified_running)

        if seo_submitted:
            urls_seo = parse_urls_text(urls_text_seo or "")
            invalid = [u for u in urls_seo if not is_valid_url(u)]
            if not urls_seo:
                st.warning("Enter at least one URL.")
            elif invalid:
                st.error(f"Invalid URLs: {', '.join(invalid)}")
            else:
                safe_name = re.sub(r"[^\w\-]", "_", seo_output_name.strip())
                output_dir = HERE / safe_name
                output_dir.mkdir(parents=True, exist_ok=True)
                runtime_cfg = build_runtime_config(
                    CONFIG,
                    viewport={**CONFIG["viewport"]},
                    stabilization_ms=int(seo_delay * 1000),
                )
                runner = CaptureRunner(urls_seo, runtime_cfg, output_dir, "seo")
                st.session_state.runner = runner
                st.session_state.running = True

        if st.session_state.running and st.session_state.runner:
            runner = st.session_state.runner
            _run_with_progress(runner, "seo")
            st.session_state.running = False
            if runner.cancelled:
                st.warning(f"Cancelled — {len(runner.results)} URL(s) extracted.")
            else:
                st.success(f"Done — {len(runner.results)} URL(s) extracted.")
            render_results(runner.results, "seo", runner.output_dir, key_prefix="seo_")
    else:
        runtime_cfg = build_runtime_config(CONFIG, CONFIG["viewport"], CONFIG["timing"]["stabilization_ms"])
        render_rules_editor(allow_run=False, runtime_cfg=runtime_cfg)

        rules = st.session_state.extraction_rules
        if not rules:
            st.info("Add at least one rule above, or load a saved rule set.")
            return

        default_urls = st.session_state.get("seo_urls", "")
        with st.form("extraction_form"):
            ext_urls = st.text_area("URLs (one per line)", height=120, placeholder="https://example.com\nhttps://example.org", value=default_urls, key="ext_urls")
            ext_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="ext_delay")
            ext_output = st.text_input("Output folder name", value=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}", key="ext_output")
            ext_submitted = st.form_submit_button("Run Extraction", disabled=st.session_state.running or st.session_state.unified_running)

        if ext_submitted:
            parsed = parse_urls_text(ext_urls or "")
            invalid = [u for u in parsed if not is_valid_url(u)]
            if not parsed:
                st.warning("Enter at least one URL.")
            elif invalid:
                st.error(f"Invalid URLs: {', '.join(invalid)}")
            else:
                safe_name = re.sub(r"[^\w\-]", "_", ext_output.strip())
                output_dir = HERE / safe_name
                output_dir.mkdir(parents=True, exist_ok=True)
                ext_runtime_cfg = build_runtime_config(
                    CONFIG,
                    viewport={**CONFIG["viewport"]},
                    stabilization_ms=int(ext_delay * 1000),
                )
                runner = ExtractionRunner(parsed, rules, ext_runtime_cfg, output_dir)
                st.session_state.extraction_runner = runner
                st.session_state.running = True

        if st.session_state.running and st.session_state.get("extraction_runner"):
            runner = st.session_state.extraction_runner
            _run_with_progress(runner, "ext")
            st.session_state.running = False
            if runner.cancelled:
                st.warning(f"Cancelled — {len(runner.results)} URL(s) extracted.")
            else:
                st.success(f"Done — {len(runner.results)} URL(s) extracted.")
            render_results(runner.results, "extraction", runner.output_dir, key_prefix="ext_")


def page_settings() -> None:
    st.subheader("Configuration")
    with st.form("cfg_form"):
        new_width = st.number_input("Viewport width", value=CONFIG["viewport"]["width"], min_value=320, max_value=3840)
        new_height = st.number_input("Viewport height", value=CONFIG["viewport"]["height"], min_value=320, max_value=2160)
        new_stab = st.number_input("Stabilization (ms)", value=CONFIG["timing"]["stabilization_ms"], min_value=500, max_value=10000, step=100)
        new_min_delay = st.number_input("Inter-page delay min (s)", value=CONFIG["timing"]["inter_page_delay_min"], min_value=0.0, max_value=10.0)
        new_max_delay = st.number_input("Inter-page delay max (s)", value=CONFIG["timing"]["inter_page_delay_max"], min_value=0.0, max_value=10.0)
        if st.form_submit_button("Save"):
            try:
                CONFIG["viewport"]["width"] = int(new_width)
                CONFIG["viewport"]["height"] = int(new_height)
                CONFIG["timing"]["stabilization_ms"] = int(new_stab)
                CONFIG["timing"]["inter_page_delay_min"] = float(new_min_delay)
                CONFIG["timing"]["inter_page_delay_max"] = float(new_max_delay)
                with open(HERE / "config.yaml", "w", encoding="utf-8") as f:
                    yaml.dump(CONFIG, f, default_flow_style=False)
                st.success("Config saved to config.yaml")
            except Exception as e:
                st.error(f"Failed to save: {e}")

    st.subheader("Manage Output Folders")
    folders = sorted(
        [p for p in HERE.iterdir() if p.is_dir() and ((p / "data").exists() or (p / "photos").exists())],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not folders:
        st.info("No output folders yet.")
    else:
        selected = st.selectbox("Select folder to clean", options=[str(f.relative_to(HERE)) for f in folders])
        if selected:
            if st.button("Delete selected folder", type="secondary"):
                st.session_state["confirm_delete_folder"] = selected
            if st.session_state.get("confirm_delete_folder") == selected:
                st.warning(f"Delete `{selected}`? This cannot be undone.")
                c_yes, c_no, _ = st.columns([1, 1, 4])
                with c_yes:
                    if st.button("Yes, delete", type="primary", key="confirm_del_yes"):
                        try:
                            shutil.rmtree(HERE / selected)
                            st.session_state.pop("confirm_delete_folder", None)
                            st.success(f"Deleted {selected}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete: {e}")
                with c_no:
                    if st.button("Cancel", key="confirm_del_no"):
                        st.session_state.pop("confirm_delete_folder", None)
                        st.rerun()


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



# ── Extraction rules page (standalone) ──

def page_rule_sets() -> None:
    st.subheader("Rule Sets")
    runtime_cfg = build_runtime_config(CONFIG, CONFIG["viewport"], CONFIG["timing"]["stabilization_ms"])
    render_rules_editor(allow_run=False, runtime_cfg=runtime_cfg)

    st.markdown("---")
    rules = st.session_state.extraction_rules
    if not rules:
        st.info("Add at least one extraction rule above.")
        return

    default_urls = st.session_state.get("seo_urls", "")
    with st.form("extraction_form"):
        ext_urls = st.text_area("URLs (one per line)", height=120, placeholder="https://example.com\nhttps://example.org", value=default_urls, key="ext_urls")
        ext_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="ext_delay")
        ext_output = st.text_input("Output folder name", value=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}", key="ext_output")
        ext_submitted = st.form_submit_button("Run Extraction", disabled=st.session_state.running or st.session_state.unified_running)

    if ext_submitted:
        parsed = parse_urls_text(ext_urls or "")
        invalid = [u for u in parsed if not is_valid_url(u)]
        if not parsed:
            st.warning("Enter at least one URL.")
        elif invalid:
            st.error(f"Invalid URLs: {', '.join(invalid)}")
        else:
            safe_name = re.sub(r"[^\w\-]", "_", ext_output.strip())
            output_dir = HERE / safe_name
            output_dir.mkdir(parents=True, exist_ok=True)
            runtime_cfg = build_runtime_config(
                CONFIG,
                viewport={**CONFIG["viewport"]},
                stabilization_ms=int(ext_delay * 1000),
            )
            runner = ExtractionRunner(parsed, rules, runtime_cfg, output_dir)
            st.session_state.extraction_runner = runner
            st.session_state.running = True

    if st.session_state.running and st.session_state.get("extraction_runner"):
        runner = st.session_state.extraction_runner
        _run_with_progress(runner, "ext")
        st.session_state.running = False
        if runner.cancelled:
            st.warning(f"Cancelled — {len(runner.results)} URL(s) extracted.")
        else:
            st.success(f"Done — {len(runner.results)} URL(s) extracted.")
        render_results(runner.results, "extraction", runner.output_dir, key_prefix="ext_")


# ── Dashboard ──

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


# ── New Run page (unified workflow) ──

def page_new_run() -> None:
    st.subheader("New Run")

    for key, default in [
        ("newrun_collectors", {"screenshot": True, "seo": True, "extraction": False}),
        ("newrun_output", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    # ── If a run is active or just finished, show it full-width ──
    if st.session_state.unified_running and st.session_state.unified_runner:
        _render_active_run()
        return
    if st.session_state.get("newrun_just_finished"):
        runner = st.session_state.unified_runner
        _render_run_complete(runner)
        return

    # ── Setup form: everything on one page ──
    collectors = st.session_state.newrun_collectors

    # URL input — the most important thing
    existing_urls = st.session_state.get("capture_urls") or []
    url_count = len(existing_urls)

    url_source = st.radio(
        "URL source",
        ["Paste URLs", "Sitemap", "CSV upload", "WordPress XML"],
        horizontal=True, key="newrun_url_source",
        label_visibility="collapsed",
    )

    imported_urls: list[str] = []
    if url_source == "Paste URLs":
        raw = st.text_area(
            "URLs (one per line)", height=140,
            placeholder="https://example.com\nhttps://example.com/about\nhttps://example.com/contact",
            key="newrun_paste",
        )
        if raw:
            imported_urls = parse_urls_text(raw)
    elif url_source == "Sitemap":
        sm_col1, sm_col2 = st.columns([3, 1])
        with sm_col1:
            sm_url = st.text_input("Sitemap URL", placeholder="https://example.com/sitemap.xml", key="newrun_sm", label_visibility="collapsed")
        with sm_col2:
            if sm_url and st.button("Fetch", key="newrun_sm_fetch"):
                with st.spinner("Fetching..."):
                    try:
                        imported_urls = import_from_sitemap_url(sm_url)
                        st.success(f"Found {len(imported_urls)} URLs")
                    except Exception as e:
                        st.error(f"Failed: {e}")
    elif url_source == "CSV upload":
        uploaded = st.file_uploader("Upload CSV", type=["csv", "txt"], key="newrun_csv", label_visibility="collapsed")
        if uploaded:
            raw = uploaded.read().decode("utf-8", errors="replace")
            pairs = import_from_csv_file(raw)
            if pairs:
                imported_urls = [a for a, _ in pairs]
                st.success(f"Found {len(imported_urls)} URLs from CSV")
            else:
                st.error("No valid URLs found in CSV")
    elif url_source == "WordPress XML":
        uploaded = st.file_uploader("Upload WordPress XML", type=["xml"], key="newrun_wp", label_visibility="collapsed")
        if uploaded:
            raw = uploaded.read()
            try:
                posts = import_from_wp_xml(raw)
                imported_urls = [p["url"] for p in posts]
                st.success(f"Found {len(imported_urls)} posts/pages")
            except Exception as e:
                st.error(f"Failed: {e}")

    # Merge imported into queue
    if imported_urls:
        if st.button(f"Add {len(imported_urls)} URL(s) to queue", key="newrun_add_urls", type="secondary"):
            merged = list(dict.fromkeys(existing_urls + imported_urls))
            st.session_state.capture_urls = merged
            st.rerun()

    # Show current queue
    if url_count:
        st.success(f"**{url_count}** URL(s) in queue")
        with st.expander("View URLs", expanded=False):
            for u in existing_urls[:100]:
                st.text(u)
            if url_count > 100:
                st.caption(f"... and {url_count - 100} more")
        c1, c2, _ = st.columns([1, 1, 4])
        with c1:
            if st.button("Clear queue", key="newrun_clear"):
                st.session_state.capture_urls = []
                st.rerun()
    elif not imported_urls:
        st.info("Paste URLs above, or import from a sitemap/CSV/WordPress XML.")

    st.markdown("---")

    # Collectors + settings in a compact row
    col_collect, col_settings = st.columns([1, 1])
    with col_collect:
        st.markdown("**Collectors**")
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            collectors["screenshot"] = st.checkbox("Screenshots", value=collectors.get("screenshot", True), key="newrun_do_ss")
        with cc2:
            collectors["seo"] = st.checkbox("SEO data", value=collectors.get("seo", True), key="newrun_do_seo",
                help="Title, meta, headings, OG tags, schema, word count, links, alt text.")
        with cc3:
            collectors["extraction"] = st.checkbox("Custom rules", value=collectors.get("extraction", False), key="newrun_do_ext")
        st.session_state.newrun_collectors = collectors

        if collectors["extraction"]:
            rules = st.session_state.get("extraction_rules", [])
            if not rules:
                st.warning("No extraction rules loaded. Go to **Rule Sets** first.")

    with col_settings:
        st.markdown("**Settings**")
        s1, s2 = st.columns(2)
        with s1:
            ss_width = st.number_input("Width", value=CONFIG["viewport"]["width"], min_value=320, max_value=3840, key="newrun_width")
            ss_delay = st.number_input("Delay (s)", value=CONFIG["timing"]["stabilization_ms"] / 1000, min_value=0.0, max_value=60.0, key="newrun_delay")
        with s2:
            ss_height = st.number_input("Height", value=CONFIG["viewport"]["height"], min_value=320, max_value=2160, key="newrun_height")
            output_name = st.text_input("Folder name", value=st.session_state.newrun_output, key="newrun_output_name")
            st.session_state.newrun_output = output_name

    st.markdown("---")

    # Run button — prominent
    active_collectors = [k for k, v in collectors.items() if v]
    can_run = existing_urls and active_collectors
    btn_disabled = st.session_state.unified_running or st.session_state.running or not can_run

    reasons = []
    if not existing_urls:
        reasons.append("add URLs")
    if not active_collectors:
        reasons.append("select a collector")
    if collectors.get("extraction") and not st.session_state.get("extraction_rules"):
        reasons.append("load extraction rules")

    if reasons:
        st.caption(f"To start: {', '.join(reasons)}")

    if st.button("Start Run", disabled=btn_disabled, type="primary", key="newrun_start", use_container_width=True):
        safe_name = re.sub(r"[^\w\-]", "_", output_name.strip())
        output_dir = HERE / safe_name
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_cfg = build_runtime_config(
            CONFIG,
            viewport={"width": int(ss_width), "height": int(ss_height)},
            stabilization_ms=int(ss_delay * 1000),
        )

        collector_list: list[dict] = []
        if collectors["screenshot"]:
            collector_list.append({"name": "screenshot", "rules": None})
        if collectors["seo"]:
            collector_list.append({"name": "seo", "rules": None})
        if collectors["extraction"]:
            collector_list.append({"name": "extraction", "rules": st.session_state.get("extraction_rules", [])})

        runner = UnifiedRunner(existing_urls, collector_list, runtime_cfg, output_dir)
        st.session_state.unified_runner = runner
        st.session_state.unified_running = True
        st.rerun()


def _render_active_run() -> None:
    """Show the currently running job with live progress."""
    runner = st.session_state.unified_runner
    st.info(f"Running — **{runner.status}**")
    _run_with_progress(runner, "newrun")
    st.session_state.unified_running = False
    st.session_state.newrun_just_finished = True
    st.rerun()


def _render_run_complete(runner) -> None:
    """Show completed run results with prominent download buttons."""
    st.session_state.newrun_just_finished = False

    ok = sum(
        1 for rows in runner.results.values() for r in rows if r.get("status") == "ok"
    )
    total = sum(len(rows) for rows in runner.results.values())
    failed = total - ok

    # Big metrics row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("URLs", len(runner.urls))
    m2.metric("Passed", ok)
    m3.metric("Failed", failed)
    m4.metric("Collectors", len(runner.collectors))

    st.markdown("---")

    # ── Download buttons — front and center ──
    st.markdown("### Download Results")
    dl_cols = st.columns(4)
    dl_idx = 0

    if runner.results.get("screenshot"):
        with dl_cols[dl_idx]:
            zip_data = build_zip(runner.results["screenshot"], runner.output_dir)
            st.download_button(
                "Screenshots ZIP",
                data=zip_data,
                file_name="screenshots.zip",
                mime="application/zip",
                key="newrun_dl_zip",
                use_container_width=True,
                type="primary",
            )
        dl_idx += 1

    if runner.results.get("seo"):
        with dl_cols[dl_idx]:
            all_keys = list(dict.fromkeys(k for r in runner.results["seo"] for k in r))
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(runner.results["seo"])
            st.download_button(
                "SEO CSV",
                data=csv_buf.getvalue().encode(),
                file_name="seo_results.csv",
                mime="text/csv",
                key="newrun_dl_seo_csv",
                use_container_width=True,
                type="primary",
            )
        dl_idx += 1

    if runner.results.get("extraction"):
        with dl_cols[dl_idx]:
            all_keys = list(dict.fromkeys(k for r in runner.results["extraction"] for k in r))
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(runner.results["extraction"])
            st.download_button(
                "Extraction CSV",
                data=csv_buf.getvalue().encode(),
                file_name="extraction_results.csv",
                mime="text/csv",
                key="newrun_dl_ext_csv",
                use_container_width=True,
                type="primary",
            )
        dl_idx += 1

    # Output folder
    st.caption(f"Output saved to: `{runner.output_dir}`")

    st.markdown("---")

    # ── Detailed results by collector ──
    _render_unified_results(runner, key_prefix="newrun_")

    # Run again
    st.markdown("---")
    if st.button("Run Again", key="newrun_run_again"):
        st.session_state.newrun_just_finished = False
        st.rerun()


# ── Router ──

def main() -> None:
    st.set_page_config(page_title="Page Capture", layout="wide", page_icon=":material/center_focus_strong:")
    _init_session_state()

    pages = {
        "Capture": [
            st.Page(page_new_run, title="New Run", icon=":material/rocket_launch:", default=True),
            st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:"),
            st.Page(page_extraction, title="Data Extraction", icon=":material/data_object:"),
        ],
        "Tools": [
            st.Page(page_import, title="Import URLs", icon=":material/input:"),
            st.Page(page_rule_sets, title="Rule Sets", icon=":material/tune:"),
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

        st.markdown("---")
        urls = st.session_state.get("capture_urls") or []
        n = len(urls)
        if n:
            st.markdown(f"**URL Queue** — {n} loaded")
            with st.expander("View URLs", expanded=False):
                for u in urls[:50]:
                    st.text(u)
                if n > 50:
                    st.caption(f"... and {n - 50} more")
            if st.button("Clear queue", key="sb_clear_urls"):
                st.session_state.capture_urls = []
                st.rerun()
        else:
            st.caption("URL Queue — empty")

    pg = st.navigation(pages, position="sidebar")
    pg.run()


main()
