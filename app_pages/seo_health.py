"""SEO Health page — post-crawl analysis with health score and visualisations."""

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


def _get_seo_runs():
    """Get all SEO-capable runs from history."""
    history = load_history()
    seo_runs = []
    for i, h in enumerate(history):
        kind = h.get("kind", "")
        if kind in ("seo", "unified", "fast_seo"):
            # For unified runs, check if SEO collector was used
            if kind == "unified":
                collectors = h.get("collectors", [])
                # collectors can be list of strings or list of dicts
                has_seo = any(
                    (c == "seo" if isinstance(c, str) else c.get("name") == "seo")
                    for c in collectors
                )
                if not has_seo:
                    continue
            seo_runs.append((i, h))
    return seo_runs


def _filter_issues_by_severity(issues, severities: list[str]):
    """Filter issues by selected severities."""
    if not severities or "All" in severities:
        return issues
    return [i for i in issues if i.severity in severities]


def _get_page_level_issues(issues, ok_rows):
    """Build page-level issue view for drill-down."""
    page_issues = {}
    for issue in issues:
        for url in issue.urls:
            if url not in page_issues:
                page_issues[url] = []
            page_issues[url].append(issue)
    return page_issues


def page_seo_health() -> None:
    st.subheader("SEO Health")
    st.caption("Post-crawl analysis with health score, issue detection, and visualisations.")

    # ── Source Selection ──────────────────────────────────────────────
    source_tabs = st.tabs(["Current Run", "History", "Compare Runs"])

    results = None
    source_label = ""
    output_dir = ""
    selected_run_idx = None

    with source_tabs[0]:
        # Current run
        if st.session_state.get("unified_runner"):
            runner = st.session_state.unified_runner
            if runner.results.get("seo"):
                results = runner.results["seo"]
                source_label = "Current run"
                output_dir = str(runner.output_dir)
                st.success("Using current run results")
            else:
                st.info("Current run has no SEO data")
        else:
            st.info("No active run")

    with source_tabs[1]:
        # History selection
        seo_runs = _get_seo_runs()
        if seo_runs:
            labels = [
                f"{h['timestamp'][:19]} — {h.get('kind', '?').upper()} — {h.get('total', '?')} URLs ({h.get('ok', 0)} OK)"
                for _, h in seo_runs
            ]
            selected = st.selectbox("Select a past SEO run", labels, key="seo_analysis_select")
            if selected:
                idx = labels.index(selected)
                selected_run_idx, entry = seo_runs[idx]
                results = entry.get("results", [])
                source_label = f"History: {entry['timestamp'][:19]}"
                output_dir = entry.get("output_dir", "")
        else:
            st.info("No SEO runs in history")

    with source_tabs[2]:
        # Compare runs
        seo_runs = _get_seo_runs()
        if len(seo_runs) >= 2:
            st.caption("Select two runs to compare")
            col_a, col_b = st.columns(2)
            labels = [f"{h['timestamp'][:19]} — {h.get('kind','?')} — {h.get('ok',0)}/{h.get('total',0)}" for _, h in seo_runs]

            with col_a:
                sel_a = st.selectbox("Run A", labels, key="seo_compare_a")
            with col_b:
                sel_b = st.selectbox("Run B", labels, key="seo_compare_b")

            if sel_a and sel_b and sel_a != sel_b:
                idx_a = labels.index(sel_a)
                idx_b = labels.index(sel_b)
                _, entry_a = seo_runs[idx_a]
                _, entry_b = seo_runs[idx_b]

                results_a = entry_a.get("results", [])
                results_b = entry_b.get("results", [])

                issues_a = analyze_results(results_a)
                issues_b = analyze_results(results_b)

                ok_a = [r for r in results_a if r.get("status") == "ok"]
                ok_b = [r for r in results_b if r.get("status") == "ok"]

                score_a = compute_health_score(issues_a, len(ok_a))
                score_b = compute_health_score(issues_b, len(ok_b))

                summary_a = summarize_issues(issues_a)
                summary_b = summarize_issues(issues_b)

                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    st.metric(f"Run A — {score_a}/100", f"Errors: {summary_a['errors']} | Warnings: {summary_a['warnings']}")
                with c2:
                    st.metric(f"Run B — {score_b}/100", f"Errors: {summary_b['errors']} | Warnings: {summary_b['warnings']}")

                # Category comparison
                cats_a = group_issues_by_category(issues_a)
                cats_b = group_issues_by_category(issues_b)
                all_cats = set(cats_a.keys()) | set(cats_b.keys())

                comp_data = []
                for cat in sorted(all_cats):
                    issues_ca = cats_a.get(cat, [])
                    issues_cb = cats_b.get(cat, [])
                    err_a = sum(i.count for i in issues_ca if i.severity == "error")
                    err_b = sum(i.count for i in issues_cb if i.severity == "error")
                    warn_a = sum(i.count for i in issues_ca if i.severity == "warning")
                    warn_b = sum(i.count for i in issues_cb if i.severity == "warning")
                    opp_a = sum(i.count for i in issues_ca if i.severity == "opportunity")
                    opp_b = sum(i.count for i in issues_cb if i.severity == "opportunity")
                    comp_data.append({
                        "Category": cat.replace("_", " ").title(),
                        "Run A Errors": err_a,
                        "Run B Errors": err_b,
                        "Δ Errors": err_b - err_a,
                        "Run A Warnings": warn_a,
                        "Run B Warnings": warn_b,
                        "Δ Warnings": warn_b - warn_a,
                        "Run A Opps": opp_a,
                        "Run B Opps": opp_b,
                        "Δ Opps": opp_b - opp_a,
                    })
                st.dataframe(pd.DataFrame(comp_data), width="stretch", hide_index=True)
                return  # Early return for compare view
        else:
            st.info("Need at least 2 SEO runs to compare")

    # ── No results ────────────────────────────────────────────────────
    if results is None:
        st.info("No SEO results available. Run a capture with the SEO collector enabled first.")
        return

    st.caption(f"Source: {source_label} — {len(results)} URL(s)")

    # ── Run analysis ──────────────────────────────────────────────────
    issues = analyze_results(results)
    ok_rows = [r for r in results if r.get("status") == "ok"]
    total_pages = len(ok_rows)
    health_score = compute_health_score(issues, total_pages)
    summary = summarize_issues(issues)
    categories = group_issues_by_category(issues)

    # ── Health Score ──────────────────────────────────────────────────
    st.metric("Health Score", f"{health_score}/100", delta=None, border=True)
    st.progress(health_score / 100)

    # ── Summary Metrics ───────────────────────────────────────────────
    with st.container(horizontal=True):
        st.metric("Total URLs", len(results), border=True)
        st.metric("OK", total_pages, border=True)
        st.metric("Errors", summary["errors"], border=True)
        st.metric("Warnings", summary["warnings"], border=True)
        st.metric("Opportunities", summary["opportunities"], border=True)

    st.markdown("---")

    # ── Severity Filter ───────────────────────────────────────────────
    severity_options = ["All", "error", "warning", "opportunity"]
    selected_severities = st.pills(
        "Filter by severity",
        options=severity_options,
        selection_mode="multi",
        default=["All"],
        key="seo_severity_filter",
    )

    filtered_issues = _filter_issues_by_severity(issues, selected_severities)

    # ── Issues by Category ────────────────────────────────────────────
    st.markdown("### Issues by Category")
    if not filtered_issues:
        st.success("No issues match the current filter.")
    else:
        # Category summary row
        cat_cols = st.columns(min(len(categories), 5))
        for idx, (cat, cat_issues) in enumerate(categories.items()):
            if idx < 5:
                with cat_cols[idx]:
                    cat_name = cat.replace("_", " ").title()
                    errors = sum(i.count for i in cat_issues if i.severity == "error")
                    warns = sum(i.count for i in cat_issues if i.severity == "warning")
                    opps = sum(i.count for i in cat_issues if i.severity == "opportunity")
                    total = errors + warns + opps
                    if total > 0:
                        st.metric(cat_name, total, delta=f":red[{errors}] :orange[{warns}] :blue[{opps}]", delta_color="off")

        st.markdown("")

        for cat, cat_issues in categories.items():
            cat_name = cat.replace("_", " ").title()
            cat_issues_filtered = [i for i in cat_issues if i.severity in selected_severities or "All" in selected_severities]
            if not cat_issues_filtered:
                continue

            errors = sum(i.count for i in cat_issues_filtered if i.severity == "error")
            warnings = sum(i.count for i in cat_issues_filtered if i.severity == "warning")
            opps = sum(i.count for i in cat_issues_filtered if i.severity == "opportunity")

            cat_exp = st.expander(
                f"{cat_name} — {errors} errors, {warnings} warnings, {opps} opportunities"
                if errors + warnings + opps > 0
                else f"{cat_name} — no issues",
                expanded=errors > 0,
                on_change="rerun",
            )
            if cat_exp.open:
                with cat_exp:
                    for issue in cat_issues_filtered:
                        if issue.count == 0:
                            continue
                        badge_color = {"error": "red", "warning": "orange", "opportunity": "blue"}[issue.severity]
                        badge_icon = {"error": ":material/error:", "warning": ":material/warning:", "opportunity": ":material/info:"}[issue.severity]
                        label = issue.name.replace("_", " ").title()

                        st.badge(label, icon=badge_icon, color=badge_color)
                        st.markdown(f"**{label}** — {issue.count} URL(s)")
                        st.caption(issue.how_to_fix)

                        # URL list with copy button
                        url_exp = st.expander(f"Show {issue.count} URL(s)", expanded=False, on_change="rerun")
                        if url_exp.open:
                            with url_exp:
                                for idx, u in enumerate(issue.urls[:50]):
                                    url_cols = st.columns([10, 1])
                                    with url_cols[0]:
                                        st.text(u)
                                    with url_cols[1]:
                                        if st.button(":material/content_copy:", key=f"copy_{issue.name}_{idx}", help="Copy URL"):
                                            st.toast(f"Copied: {u}")
                                if issue.count > 50:
                                    st.caption(f"... and {issue.count - 50} more")

    st.markdown("---")

    # ── Page-Level View ───────────────────────────────────────────────
    st.markdown("### Page-Level View")
    st.caption("Drill down into issues per URL")

    if ok_rows:
        page_issues = _get_page_level_issues(filtered_issues, ok_rows)
        urls_with_issues = list(page_issues.keys())

        if urls_with_issues:
            selected_url = st.selectbox(
                "Select URL to inspect",
                urls_with_issues,
                format_func=lambda x: x[:80] + "..." if len(x) > 80 else x,
                key="seo_page_select",
            )

            if selected_url:
                page_data = next((r for r in ok_rows if r.get("url") == selected_url), {})
                page_issues_list = page_issues[selected_url]

                st.markdown(f"**{selected_url}**")
                c1, c2, c3 = st.columns(3)
                c1.metric("Title", page_data.get("title", "—")[:50])
                c2.metric("H1", page_data.get("h1", "—")[:50])
                c3.metric("Word Count", page_data.get("word_count", 0))

                if page_issues_list:
                    for issue in page_issues_list:
                        badge_icon = {"error": ":material/error:", "warning": ":material/warning:", "opportunity": ":material/info:"}[issue.severity]
                        badge_color = {"error": "red", "warning": "orange", "opportunity": "blue"}[issue.severity]
                        st.markdown(f":{badge_color}-badge[{badge_icon}] **{issue.name.replace('_', ' ').title()}**")
                        st.caption(issue.how_to_fix)
                else:
                    st.success("No issues for this page with current filter")
        else:
            st.info("No pages have issues with the current severity filter")
    else:
        st.info("No OK pages to inspect")

    st.markdown("---")

    # ── Visualisations ────────────────────────────────────────────────
    st.markdown("### Visualisations")
    if not ok_rows:
        st.info("No OK pages to visualise.")
    else:
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

        # Duplicate detection
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
            for title, urls in list(dup_title_groups.items())[:10]:
                title_exp = st.expander(f'"{title[:60]}..." — {len(urls)} pages')
                if title_exp.open:
                    with title_exp:
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
            for desc, urls in list(dup_meta_groups.items())[:10]:
                desc_exp = st.expander(f'"{desc[:60]}..." — {len(urls)} pages')
                if desc_exp.open:
                    with desc_exp:
                        for u in urls:
                            st.text(u)
        else:
            st.success("No duplicate meta descriptions found.")

    # ── PDF Report ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Export Report")
    pdf_bytes = generate_pdf_report(results, issues, health_score, output_dir)
    st.download_button(
        "Download PDF Report",
        data=pdf_bytes,
        file_name=f"seo_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mime="application/pdf",
        type="primary",
        width="stretch",
    )
