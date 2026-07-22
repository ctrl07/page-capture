"""Blog Audit — Compare blog posts between source and target sites."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from components.progress import run_with_progress
from extraction import list_rulesets
from page_capture import load_config
from runners import HERE, BlogAuditRunner, build_runtime_config
from state import register_runner, unregister_runner

CONFIG = load_config(HERE / "config.yaml")

_BLOG_AUDIT_KIND = "blog_audit"


def _render_active_run() -> None:
    """Show the currently running blog audit with live progress."""
    runner = st.session_state.blog_audit_runner
    st.info(f"Running blog audit — **{runner.status}**")
    run_with_progress(runner, "blog_audit")
    st.session_state.blog_audit_running = False
    st.session_state.blog_audit_just_finished = True
    unregister_runner(runner)
    st.rerun()


def _render_audit_results(runner: BlogAuditRunner) -> None:
    """Show completed audit results."""
    st.session_state.blog_audit_just_finished = False
    items = runner.results.get("audit", [])

    ok_count = sum(1 for r in items if r.get("status") == "ok")
    total = len(items)
    failed = total - ok_count
    avg_score = round(sum(r.get("overall_score", 0) for r in items) / max(total, 1), 1)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Posts", total, border=True)
    c2.metric("Passed", ok_count, border=True)
    c3.metric("Failed", failed, border=True)
    c4.metric("Avg Score", f"{avg_score}%", border=True)

    st.markdown("---")
    st.markdown("### Download Results")
    dl_cols = st.columns(3)
    with dl_cols[0]:
        st.download_button(
            "Audit CSV",
            data=_build_csv(items),
            file_name=f"blog_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key="audit_dl_csv",
            width="stretch",
            type="primary",
        )
    with dl_cols[1]:
        st.download_button(
            "Audit JSON",
            data=json.dumps(items, indent=2, default=str).encode(),
            file_name=f"blog_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            key="audit_dl_json",
            width="stretch",
        )
    with dl_cols[2]:
        st.markdown(f"Output: `{runner.output_dir}`")

    st.markdown("---")
    _render_audit_detail_table(items, runner.output_dir)

    st.markdown("---")
    if st.button("Audit Again", key="audit_run_again", width="stretch"):
        st.session_state.blog_audit_just_finished = False
        st.rerun()


def _build_csv(items: list[dict]) -> bytes:
    flat = []
    for item in items:
        row = {
            "source_url": item.get("source_url", ""),
            "target_url": item.get("target_url", ""),
            "overall_score": item.get("overall_score", 0),
            "status": item.get("status", ""),
        }
        fields = item.get("fields", {})
        for fname, finfo in fields.items():
            if isinstance(finfo, dict):
                row[f"{fname}_score"] = finfo.get("score", 0)
                row[f"{fname}_match"] = finfo.get("match", False)
                if "source" in finfo:
                    src = finfo["source"]
                    row[f"{fname}_source"] = src if isinstance(src, str) else json.dumps(src, default=str)
                if "target" in finfo:
                    tgt = finfo["target"]
                    row[f"{fname}_target"] = tgt if isinstance(tgt, str) else json.dumps(tgt, default=str)
        issues = item.get("issues", [])
        row["issue_count"] = len(issues)
        if issues:
            row["critical_issues"] = sum(1 for i in issues if i.get("severity") == "critical")
            row["high_issues"] = sum(1 for i in issues if i.get("severity") == "high")
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(row.keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerow(row)
        flat.append(row)
    buf = io.StringIO()
    if flat:
        all_keys = list(dict.fromkeys(k for r in flat for k in r))
        writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat)
    return buf.getvalue().encode("utf-8")


def _render_audit_detail_table(items: list[dict], output_dir: Path) -> None:
    if not items:
        st.info("No audit results to display.")
        return

    rows = []
    for item in items:
        issues = item.get("issues", [])
        critical = sum(1 for i in issues if i.get("severity") == "critical")
        high = sum(1 for i in issues if i.get("severity") == "high")
        rows.append({
            "source_url": item.get("source_url", ""),
            "target_url": item.get("target_url", ""),
            "score": item.get("overall_score", 0),
            "status": item.get("status", ""),
            "critical": critical,
            "high": high,
            "issues": len(issues),
            "_item": item,
        })

    df = pd.DataFrame(rows)
    display_df = df.drop(columns=["_item"], errors="ignore")

    col_cfg = {
        "score": st.column_config.NumberColumn("Score", format="%.1f%%", width="small"),
        "status": st.column_config.TextColumn("Status", width="small"),
        "critical": st.column_config.NumberColumn("Critical", width="small"),
        "high": st.column_config.NumberColumn("High", width="small"),
        "issues": st.column_config.NumberColumn("Issues", width="small"),
    }
    if "source_url" in display_df.columns:
        col_cfg["source_url"] = st.column_config.LinkColumn("Source URL", pinned=True, width="large")
    if "target_url" in display_df.columns:
        col_cfg["target_url"] = st.column_config.LinkColumn("Target URL", width="large")

    filter_col, search_col = st.columns([1, 3])
    with filter_col:
        status_filter = st.segmented_control(
            "Status", ["All", "Passed", "Failed"],
            key="audit_filter_status", label_visibility="collapsed",
        )
    with search_col:
        search = st.text_input(
            "Search URLs", key="audit_filter_search",
            placeholder="Filter by URL...", label_visibility="collapsed",
        )

    filtered = rows
    if status_filter == "Passed":
        filtered = [r for r in filtered if r["status"] == "ok"]
    elif status_filter == "Failed":
        filtered = [r for r in filtered if r["status"] != "ok"]
    if search.strip():
        q = search.strip().lower()
        filtered = [r for r in filtered if q in r["source_url"].lower() or q in r["target_url"].lower()]

    if not filtered:
        st.info("No results match your filters.")
        return

    filtered_df = pd.DataFrame(filtered).drop(columns=["_item"], errors="ignore")
    event = st.dataframe(
        filtered_df, width="stretch", hide_index=True,
        column_config=col_cfg or None,
        on_select="rerun", selection_mode="single-row",
        key="audit_detail_df",
    )

    sel_rows = getattr(event, "selection", None)
    sel_rows = getattr(sel_rows, "rows", []) if sel_rows else []
    if sel_rows:
        idx = sel_rows[0]
        if idx < len(filtered):
            _render_post_detail(filtered[idx]["_item"])


def _render_post_detail(item: dict) -> None:
    """Show a single post's audit details with side-by-side field comparison."""
    st.markdown("### Post Comparison")

    cols = st.columns([2, 1, 2])
    cols[0].markdown(f"**Source:** [{item.get('source_url', '')}]({item.get('source_url', '')})")
    cols[1].markdown(f"**Score: {item.get('overall_score', 0)}%**")
    cols[2].markdown(f"**Target:** [{item.get('target_url', '')}]({item.get('target_url', '')})")

    fields = item.get("fields", {})
    issues = item.get("issues", [])

    severity_colors = {"critical": ":red-background", "high": ":orange-background", "medium": ":blue-background"}

    fnames_ordered = ["title", "h1", "meta_description", "slug", "published_date", "author", "categories", "tags", "featured_image", "content"]
    tabs_inner = st.tabs(["Fields", "Issues", "Content"])

    with tabs_inner[0]:
        for fname in fnames_ordered:
            if fname not in fields:
                continue
            finfo = fields[fname]
            src_val = finfo.get("source", finfo.get("source_len", ""))
            tgt_val = finfo.get("target", finfo.get("target_len", ""))
            score = finfo.get("score", 0)
            match = finfo.get("match", False)

            badge = ":green-background[Match]" if match else f":red-background[Mismatch ({score}%)]"

            with st.container(border=True):
                sc1, sc2, sc3 = st.columns([4, 1, 4])
                sc1.markdown(f"**{fname}** (Source)")
                sc2.markdown(f"**{badge}**", help=f"Similarity: {score}%")
                sc3.markdown(f"**{fname}** (Target)")

                src_display = str(src_val)[:500] if isinstance(src_val, str) else (json.dumps(src_val, default=str)[:500] if src_val else "")
                tgt_display = str(tgt_val)[:500] if isinstance(tgt_val, str) else (json.dumps(tgt_val, default=str)[:500] if tgt_val else "")

                if isinstance(src_val, str) and isinstance(tgt_val, str) and len(src_val) > 500:
                    src_display += "..."
                    tgt_display += "..."

                sc1.code(src_display, line_wrap=True)
                sc3.code(tgt_display, line_wrap=True)

    with tabs_inner[1]:
        if issues:
            for issue in issues:
                sev = issue.get("severity", "medium")
                bg = severity_colors.get(sev, "")
                st.markdown(
                    f"{bg if bg else ''} **{sev.upper()}** — {issue.get('field', '')}: "
                    f"{issue.get('message', '')}{'</span>' if bg else ''}",
                    unsafe_allow_html=True,
                )
        else:
            st.success("No issues found for this post.")

    with tabs_inner[2]:
        src_content = fields.get("content", {})
        st.markdown("**Source Content**")
        src_len = src_content.get("source_len", 0)
        tgt_len = src_content.get("target_len", 0)
        st.caption(f"Source: {src_len:,} chars | Target: {tgt_len:,} chars | Score: {src_content.get('score', 0)}%")


def _pair_urls(source_text: str, target_text: str) -> list[tuple[str, str]]:
    """Pair source and target URLs by their path (ignoring domain)."""
    src_lines = [ln.strip() for ln in source_text.strip().split("\n") if ln.strip()]
    tgt_lines = [ln.strip() for ln in target_text.strip().split("\n") if ln.strip()]

    if len(src_lines) == 1 and len(tgt_lines) >= 1:
        base_src = src_lines[0].rstrip("/")
        pairs = []
        for tgt_url in tgt_lines:
            tgt_path = tgt_url.rstrip("/")
            src_url = base_src + tgt_url[len(tgt_lines[0]):]
            pairs.append((src_url, tgt_url))
        return pairs

    if len(src_lines) == len(tgt_lines):
        return list(zip(src_lines, tgt_lines))

    pairs = []
    src_by_path = {}
    for url in src_lines:
        path = "/" + url.rstrip("/").split("/", 3)[-1] if url.count("/") >= 3 else url
        src_by_path[path] = url

    for tgt_url in tgt_lines:
        tgt_path = "/" + tgt_url.rstrip("/").split("/", 3)[-1] if tgt_url.count("/") >= 3 else tgt_url
        src_url = src_by_path.get(tgt_path, "")
        if src_url:
            pairs.append((src_url, tgt_url))

    if not pairs and len(src_lines) == len(tgt_lines):
        pairs = list(zip(src_lines, tgt_lines))

    return pairs


def page_blog_audit() -> None:
    st.subheader("Blog Audit")
    st.caption("Compare blog posts between source (old provider) and target (new CMS) sites.")

    for key, default in [
        ("blog_audit_source_urls", ""),
        ("blog_audit_target_urls", ""),
        ("blog_audit_output", f"blog_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}"),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    if st.session_state.blog_audit_running and st.session_state.blog_audit_runner:
        _render_active_run()
        return
    if st.session_state.get("blog_audit_just_finished"):
        runner = st.session_state.blog_audit_runner
        _render_audit_results(runner)
        return

    left, right = st.columns([1, 1], gap="large")

    with left:
        with st.container(border=True):
            st.markdown("### Source Site (Live)")
            st.caption("Enter one URL per line. These are the blog posts from the previous provider.")
            st.text_area(
                "Source URLs",
                key="blog_audit_source_urls",
                placeholder="https://old-provider.com/blog/post-1\nhttps://old-provider.com/blog/post-2\n...",
                height=250,
                label_visibility="collapsed",
            )

    with right:
        with st.container(border=True):
            st.markdown("### Target Site (New CMS)")
            st.caption("Enter the corresponding target URLs for each source post.")
            st.text_area(
                "Target URLs",
                key="blog_audit_target_urls",
                placeholder="https://new-cms.com/blog/post-1\nhttps://new-cms.com/blog/post-2\n...",
                height=250,
                label_visibility="collapsed",
            )

    st.markdown("---")
    settings_cols = st.columns(4)
    with settings_cols[0]:
        delay = st.slider("Page delay (s)", 0.5, 5.0, 1.0, key="blog_audit_delay")
    with settings_cols[1]:
        st.caption("Viewport: %dx%d" % (CONFIG["viewport"]["width"], CONFIG["viewport"]["height"]))
    with settings_cols[2]:
        st.text_input("Output name", key="blog_audit_output", label_visibility="collapsed")
    with settings_cols[3]:
        all_rs = list_rulesets()
        blog_rs = [r for r in all_rs if "_blog" in r or r == "generic_blog"]
        blog_rs.sort()
        if "generic_blog" in blog_rs:
            blog_rs.remove("generic_blog")
            blog_rs.insert(0, "generic_blog")
        st.selectbox("Ruleset", blog_rs, key="blog_audit_ruleset", label_visibility="collapsed")

    st.markdown("---")

    source_urls_text = st.session_state.blog_audit_source_urls.strip()
    target_urls_text = st.session_state.blog_audit_target_urls.strip()
    source_lines = [ln.strip() for ln in source_urls_text.split("\n") if ln.strip()]
    target_lines = [ln.strip() for ln in target_urls_text.split("\n") if ln.strip()]

    can_run = bool(source_lines) and bool(target_lines)

    reasons = []
    if not source_lines:
        reasons.append("add source URLs")
    if not target_lines:
        reasons.append("add target URLs")

    if reasons:
        st.caption(f"To start: {', '.join(reasons)}")
    else:
        url_pairs = _pair_urls(source_urls_text, target_urls_text)
        if not url_pairs:
            st.warning("Could not pair source and target URLs. Check the entry format.")
        else:
            st.caption(f"{len(url_pairs)} post pair(s) detected")

    if st.button(
        "Start Audit",
        disabled=st.session_state.blog_audit_running or not can_run or not url_pairs,
        type="primary",
        key="blog_audit_start",
        width="stretch",
    ):
        safe_name = re.sub(r"[^\w\-]", "_", st.session_state.blog_audit_output.strip())
        output_dir = HERE / safe_name
        output_dir.mkdir(parents=True, exist_ok=True)
        runtime_cfg = build_runtime_config(
            CONFIG,
            viewport={"width": int(CONFIG["viewport"]["width"]), "height": int(CONFIG["viewport"]["height"])},
            stabilization_ms=int(delay * 1000),
        )

        runner = BlogAuditRunner(
            url_pairs,
            runtime_cfg,
            output_dir,
            ruleset_name=st.session_state.blog_audit_ruleset,
        )
        st.session_state.blog_audit_runner = runner
        st.session_state.blog_audit_running = True
        register_runner(runner)
        st.rerun()
