"""SEO Analysis page — post-crawl analysis with health score and visualisations."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from analysis import (
    analyze_results,
    compute_health_score,
    generate_pdf_report,
    group_issues_by_category,
    summarize_issues,
)
from runners import load_history


def page_seo_analysis() -> None:
    st.subheader("SEO Analysis")
    st.caption("Post-crawl analysis with health score, issue detection, and visualisations.")

    # Find SEO results — from last unified run or history
    results = None
    source_label = ""
    output_dir = ""

    # Check current session for unified runner results
    if st.session_state.get("unified_runner"):
        runner = st.session_state.unified_runner
        if runner.results.get("seo"):
            results = runner.results["seo"]
            source_label = "Current run"
            output_dir = str(runner.output_dir)

    # Fallback: check history
    if results is None:
        history = load_history()
        seo_runs = [
            (i, h) for i, h in enumerate(history)
            if h.get("kind") in ("seo", "unified", "fast_seo") and (
                h.get("collectors", ["seo"] if h.get("kind") == "seo" else ["seo"]) or h.get("kind") == "seo"
            )
        ]
        if seo_runs:
            labels = [
                f"{h['timestamp'][:19]} — {h.get('total', '?')} URLs ({h.get('ok', 0)} OK)"
                for _, h in seo_runs
            ]
            selected = st.selectbox("Select a past SEO run", labels, key="seo_analysis_select")
            if selected:
                idx = labels.index(selected)
                _, entry = seo_runs[idx]
                results = entry.get("results", [])
                source_label = f"History: {entry['timestamp'][:19]}"
                output_dir = entry.get("output_dir", "")

    if results is None:
        st.info("No SEO results available. Run a capture with the SEO collector enabled first.")
        return

    st.caption(f"Source: {source_label} — {len(results)} URL(s)")

    # Run analysis
    issues = analyze_results(results)
    ok_rows = [r for r in results if r.get("status") == "ok"]
    total_pages = len(ok_rows)
    health_score = compute_health_score(issues, total_pages)
    summary = summarize_issues(issues)
    categories = group_issues_by_category(issues)

    # ── Health Score ──
    st.metric("Health Score", f"{health_score}/100", delta=None)
    st.progress(health_score / 100)

    # ── Summary Metrics ──
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total URLs", len(results))
    m2.metric("OK", total_pages)
    m3.metric("Errors", summary["errors"])
    m4.metric("Warnings", summary["warnings"])

    st.markdown("---")

    # ── Issue Categories ──
    st.markdown("### Issues by Category")
    if not categories:
        st.success("No issues found. Great job!")
    else:
        for cat, cat_issues in categories.items():
            cat_name = cat.replace("_", " ").title()
            errors = sum(i.count for i in cat_issues if i.severity == "error")
            warnings = sum(i.count for i in cat_issues if i.severity == "warning")
            opps = sum(i.count for i in cat_issues if i.severity == "opportunity")

            with st.expander(
                f"{cat_name} -- {errors} errors, {warnings} warnings, {opps} opportunities"
                if errors + warnings + opps > 0
                else f"{cat_name} -- no issues",
                expanded=errors > 0,
            ):
                for issue in cat_issues:
                    if issue.count == 0:
                        continue
                    badge = {"error": "🔴", "warning": "🟡", "opportunity": "🔵"}[issue.severity]
                    label = issue.name.replace("_", " ").title()
                    st.markdown(f"{badge} **{label}** -- {issue.count} URL(s)")
                    st.caption(issue.how_to_fix)
                    with st.expander(f"Show {issue.count} URL(s)", expanded=False):
                        for u in issue.urls[:20]:
                            st.text(u)
                        if issue.count > 20:
                            st.caption(f"... and {issue.count - 20} more")

    st.markdown("---")

    # ── Visualisations ──
    st.markdown("### Visualisations")
    if not ok_rows:
        st.info("No OK pages to visualise.")
        return

    viz1, viz2 = st.columns(2)

    with viz1:
        st.markdown("**Title Length Distribution**")
        title_lens = [r.get("title_len", 0) for r in ok_rows if isinstance(r.get("title_len"), int)]
        if title_lens:
            buckets = {"0": 0, "1-29": 0, "30-60": 0, "61-70": 0, "70+": 0}
            for tl in title_lens:
                if tl == 0:
                    buckets["0"] += 1
                elif tl < 30:
                    buckets["1-29"] += 1
                elif tl <= 60:
                    buckets["30-60"] += 1
                elif tl <= 70:
                    buckets["61-70"] += 1
                else:
                    buckets["70+"] += 1
            st.bar_chart(pd.Series(buckets))
        else:
            st.info("No title length data.")

    with viz2:
        st.markdown("**Meta Description Length**")
        meta_lens = [r.get("meta_desc_len", 0) for r in ok_rows if isinstance(r.get("meta_desc_len"), int)]
        if meta_lens:
            buckets = {"0": 0, "1-69": 0, "70-155": 0, "156-160": 0, "160+": 0}
            for ml in meta_lens:
                if ml == 0:
                    buckets["0"] += 1
                elif ml < 70:
                    buckets["1-69"] += 1
                elif ml <= 155:
                    buckets["70-155"] += 1
                elif ml <= 160:
                    buckets["156-160"] += 1
                else:
                    buckets["160+"] += 1
            st.bar_chart(pd.Series(buckets))
        else:
            st.info("No meta description length data.")

    viz3, viz4 = st.columns(2)

    with viz3:
        st.markdown("**Word Count Distribution**")
        word_counts = [r.get("word_count", 0) for r in ok_rows if isinstance(r.get("word_count"), int)]
        if word_counts:
            buckets = {"0": 0, "1-199": 0, "200-499": 0, "500-999": 0, "1000+": 0}
            for wc in word_counts:
                if wc == 0:
                    buckets["0"] += 1
                elif wc < 200:
                    buckets["1-199"] += 1
                elif wc < 500:
                    buckets["200-499"] += 1
                elif wc < 1000:
                    buckets["500-999"] += 1
                else:
                    buckets["1000+"] += 1
            st.bar_chart(pd.Series(buckets))
        else:
            st.info("No word count data.")

    with viz4:
        st.markdown("**URL Depth**")
        url_depths = [r.get("url", "").count("/") - 2 for r in ok_rows]
        url_depths = [max(d, 0) for d in url_depths]
        if url_depths:
            depth_counts = pd.Series(url_depths).value_counts().sort_index()
            st.bar_chart(depth_counts)
        else:
            st.info("No URL data.")

    # Social completeness
    st.markdown("---")
    st.markdown("### Social Tags Completeness")
    soc1, soc2 = st.columns(2)

    with soc1:
        og_fields = ["og_title", "og_description", "og_image"]
        og_complete = sum(1 for r in ok_rows if all(r.get(f) for f in og_fields))
        og_partial = sum(1 for r in ok_rows if any(r.get(f) for f in og_fields) and not all(r.get(f) for f in og_fields))
        og_none = total_pages - og_complete - og_partial
        st.markdown("**Open Graph**")
        st.bar_chart(pd.Series({"Complete": og_complete, "Partial": og_partial, "None": og_none}))

    with soc2:
        tw_fields = ["twitter_card", "twitter_title", "twitter_image"]
        tw_complete = sum(1 for r in ok_rows if all(r.get(f) for f in tw_fields))
        tw_partial = sum(1 for r in ok_rows if any(r.get(f) for f in tw_fields) and not all(r.get(f) for f in tw_fields))
        tw_none = total_pages - tw_complete - tw_partial
        st.markdown("**Twitter Cards**")
        st.bar_chart(pd.Series({"Complete": tw_complete, "Partial": tw_partial, "None": tw_none}))

    # ── Duplicate detection ──
    st.markdown("---")
    st.markdown("### Duplicate Detection")

    dup_title_groups = {}
    for r in ok_rows:
        t = r.get("title", "")
        if t:
            dup_title_groups.setdefault(t, []).append(r.get("url", ""))
    dup_title_groups = {k: v for k, v in dup_title_groups.items() if len(v) > 1}

    if dup_title_groups:
        st.warning(f"{len(dup_title_groups)} duplicate title(s) found")
        for title, urls in list(dup_title_groups.items())[:5]:
            with st.expander(f'"{title[:60]}..." — {len(urls)} pages'):
                for u in urls:
                    st.text(u)
    else:
        st.success("No duplicate titles found.")

    dup_meta_groups = {}
    for r in ok_rows:
        m = r.get("meta_description", "")
        if m:
            dup_meta_groups.setdefault(m, []).append(r.get("url", ""))
    dup_meta_groups = {k: v for k, v in dup_meta_groups.items() if len(v) > 1}

    if dup_meta_groups:
        st.warning(f"{len(dup_meta_groups)} duplicate meta description(s) found")
        for desc, urls in list(dup_meta_groups.items())[:5]:
            with st.expander(f'"{desc[:60]}..." — {len(urls)} pages'):
                for u in urls:
                    st.text(u)
    else:
        st.success("No duplicate meta descriptions found.")

    # ── PDF Report ──
    st.markdown("---")
    st.markdown("### Export Report")
    pdf_bytes = generate_pdf_report(results, issues, health_score, output_dir)
    st.download_button(
        "Download PDF Report",
        data=pdf_bytes,
        file_name=f"seo_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )
