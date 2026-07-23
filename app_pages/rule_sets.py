"""Rule Sets page — extraction rule editor with templates, validation, import/export."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from extraction import build_extraction_js, render_rules_editor
from page_capture import load_config
from runners import HERE, PageCapture, build_runtime_config
from templates import TEMPLATES

CONFIG = load_config(HERE / "config.yaml")


def _validate_rules(rules: list[dict]) -> list[str]:
    """Validate extraction rules, return list of error messages."""
    errors = []
    seen_names = set()
    for i, rule in enumerate(rules):
        name = rule.get("name", "").strip()
        selector = rule.get("selector", "").strip()
        rtype = rule.get("type", "text")

        if not name:
            errors.append(f"Rule {i+1}: Field name is required")
        elif name in seen_names:
            errors.append(f"Rule {i+1}: Duplicate field name '{name}'")
        else:
            seen_names.add(name)

        if rtype in ("text", "attribute", "html", "count", "exists") and not selector:
            errors.append(f"Rule {i+1} ({name}): Selector is required for type '{rtype}'")

        if rtype == "attribute" and not rule.get("attribute", "").strip():
            errors.append(f"Rule {i+1} ({name}): Attribute name is required for 'attribute' type")

        if rtype == "meta" and not selector and not rule.get("attribute"):
            errors.append(f"Rule {i+1} ({name}): Selector or attribute required for 'meta' type")

    return errors


def _export_rules_json(rules: list[dict]) -> str:
    """Export rules as JSON string."""
    return json.dumps(rules, indent=2)


def _import_rules_json(json_str: str) -> list[dict] | None:
    """Import rules from JSON string, return None if invalid."""
    try:
        data = json.loads(json_str)
        if not isinstance(data, list):
            return None
        for rule in data:
            if not isinstance(rule, dict):
                return None
            required_keys = {"name", "selector", "type", "attribute", "regex", "multiple"}
            if not all(k in rule for k in required_keys):
                return None
        return data
    except json.JSONDecodeError:
        return None


def _test_rules_on_url(rules: list[dict], url: str, runtime_cfg: dict) -> dict | None:
    """Test extraction rules on a live URL, return extracted data or None on error."""
    if not rules:
        return None
    try:
        with st.spinner(f"Loading {url}..."):
            from seleniumbase import SB
            with SB(uc=True, test=True, headless=False,
                    window_size=f"{runtime_cfg['viewport']['width']},{runtime_cfg['viewport']['height']}") as sb:
                page = PageCapture(sb, runtime_cfg)
                page.open(url)
                page.scroll()
                sb.sleep(runtime_cfg["timing"]["stabilization_ms"] / 1000)
                page.hide_overlays()
                # Resolve lazy images before extraction
                page.sb.cdp.evaluate("""
                (() => {
                    document.querySelectorAll('img').forEach(img => {
                        const src = img.getAttribute('src') || '';
                        if (src && !src.startsWith('data:')) return;
                        for (const attr of ['data-lazy-src', 'data-src', 'data-original', 'data-pin-media']) {
                            const val = img.getAttribute(attr);
                            if (val) { img.setAttribute('src', val); break; }
                        }
                        if (!img.getAttribute('src') || img.getAttribute('src').startsWith('data:')) {
                            const srcset = img.getAttribute('data-lazy-srcset') || img.getAttribute('data-srcset') || img.getAttribute('srcset');
                            if (srcset) {
                                let bestUrl = '', bestWidth = -1;
                                srcset.split(',').forEach(c => {
                                    const parts = c.trim().split(' ');
                                    if (parts.length >= 2 && parts[1].endsWith('w')) {
                                        const w = parseInt(parts[1], 10);
                                        if (w > bestWidth) { bestWidth = w; bestUrl = parts[0]; }
                                    }
                                });
                                if (bestUrl) img.setAttribute('src', bestUrl);
                            }
                        }
                        for (const attr of ['data-lazy-src', 'data-src', 'data-original', 'data-pin-media',
                                             'data-lazy-srcset', 'data-srcset', 'data-load-done', 'data-ssr-src-done']) {
                            img.removeAttribute(attr);
                        }
                    });
                })()
                """)
                # Build and run extraction JS
                js = build_extraction_js(rules)
                result = page.sb.cdp.evaluate(js)
                return result
    except Exception as e:
        st.error(f"Test failed: {e}")
        return None


def page_rule_sets() -> None:
    st.subheader("Rule Sets")
    st.caption("Define custom CSS selector rules to extract data from pages. Use templates for common patterns.")

    runtime_cfg = build_runtime_config(CONFIG, CONFIG["viewport"], CONFIG["timing"]["stabilization_ms"])

    tabs = st.tabs(["Editor", "Templates", "Import/Export", "Test Rules"])

    with tabs[0]:
        st.markdown("### Rule Editor")

        rules: list[dict] = st.session_state.get("extraction_rules", [])

        if rules:
            errors = _validate_rules(rules)
            if errors:
                with st.container(border=True):
                    st.error("Validation Errors")
                    for err in errors:
                        st.markdown(f"- {err}")

        render_rules_editor(allow_run=False, runtime_cfg=runtime_cfg)

    with tabs[1]:
        st.markdown("### Rule Templates")
        st.caption("Click a template to load it into the editor. This will replace current rules.")

        template_cols = st.columns(3)
        for idx, (key, tmpl) in enumerate(TEMPLATES.items()):
            with template_cols[idx % 3]:
                with st.container(border=True):
                    st.markdown(f"**{tmpl['name']}**")
                    st.caption(tmpl['description'])
                    st.markdown(f"`{len(tmpl['rules'])}` rules")
                    if st.button("Load Template", key=f"load_tmpl_{key}", width="stretch"):
                        st.session_state.extraction_rules = [
                            {**r, "regex": r.get("regex", ""), "multiple": r.get("multiple", False)}
                            for r in tmpl["rules"]
                        ]
                        st.success(f"Loaded {tmpl['name']} template")
                        st.rerun()

        st.markdown("---")
        st.markdown("### Create Custom Template")
        with st.form("create_template"):
            tmpl_name = st.text_input("Template name", placeholder="my-custom-template")
            tmpl_desc = st.text_area("Description", placeholder="What this template extracts...")
            if st.form_submit_button("Save as Template", width="stretch"):
                if tmpl_name.strip() and rules:
                    safe_name = "".join(c for c in tmpl_name if c.isalnum() or c in "-_").lower()
                    template_file = Path("templates") / f"{safe_name}.json"
                    template_file.parent.mkdir(exist_ok=True)
                    template_file.write_text(json.dumps({
                        "name": tmpl_name.strip(),
                        "description": tmpl_desc.strip(),
                        "rules": rules,
                    }, indent=2))
                    st.success(f"Template saved as {template_file}")
                else:
                    st.error("Template name and at least one rule required")

    with tabs[2]:
        st.markdown("### Import / Export Rules")

        col_export, col_import = st.columns(2)

        with col_export:
            st.markdown("#### Export")
            if rules:
                json_str = _export_rules_json(rules)
                st.download_button(
                    "Download rules.json",
                    data=json_str,
                    file_name="extraction_rules.json",
                    mime="application/json",
                    width="stretch",
                    type="primary",
                )
                preview_exp = st.expander("Preview JSON")
                if preview_exp.open:
                    with preview_exp:
                        st.code(json_str, language="json")
            else:
                st.info("No rules to export")

        with col_import:
            st.markdown("#### Import")
            uploaded = st.file_uploader("Upload rules.json", type=["json"], label_visibility="collapsed")
            if uploaded:
                content = uploaded.read().decode("utf-8")
                imported = _import_rules_json(content)
                if imported is not None:
                    st.success(f"Valid rules file ({len(imported)} rules)")
                    if st.button("Apply Imported Rules", width="stretch", type="primary"):
                        st.session_state.extraction_rules = imported
                        st.rerun()
                else:
                    st.error("Invalid rules format. Must be a JSON array of rule objects.")

            st.markdown("---")
            st.markdown("#### Paste JSON")
            pasted = st.text_area("Paste rules JSON here", height=150, placeholder='[{"name": "...", "selector": "...", ...}]')
            if pasted.strip():
                imported = _import_rules_json(pasted)
                if imported is not None:
                    st.success(f"Valid JSON ({len(imported)} rules)")
                    if st.button("Apply Pasted Rules", key="apply_pasted", width="stretch"):
                        st.session_state.extraction_rules = imported
                        st.rerun()
                else:
                    st.error("Invalid JSON format")

    with tabs[3]:
        st.markdown("### Test Rules on Live URL")
        st.caption("Enter a URL to test your current extraction rules against a real page.")

        rules = st.session_state.get("extraction_rules", [])
        if not rules:
            st.warning("No rules defined. Add rules in the **Editor** tab first.")
        else:
            st.success(f"{len(rules)} rule(s) ready to test")

            test_url = st.text_input(
                "URL to test",
                placeholder="https://example.com/page-to-test",
                key="rule_test_url",
            )

            if test_url and st.button("Run Test", key="run_rule_test", type="primary", width="stretch"):
                result = _test_rules_on_url(rules, test_url, runtime_cfg)
                if result:
                    st.markdown("---")
                    st.markdown("#### Test Results")

                    # Summary metrics
                    total_fields = len(result)
                    filled_fields = sum(1 for v in result.values() if v)
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total Fields", total_fields)
                    c2.metric("Extracted", filled_fields)
                    c3.metric("Empty", total_fields - filled_fields)

                    # Results table
                    st.markdown("**Extracted Data**")
                    for name, value in result.items():
                        rule = next((r for r in rules if r.get("name") == name), {})
                        rtype = rule.get("type", "text")
                        with st.expander(f"{name} ({rtype})", expanded=bool(value)):
                            if isinstance(value, list):
                                st.json(value)
                            elif isinstance(value, str) and len(value) > 500:
                                st.text_area("Value", value=value, height=200, key=f"test_result_{name}")
                            else:
                                st.code(value if value else "(empty)")

                    # Raw JSON download
                    st.download_button(
                        "Download Results (JSON)",
                        data=json.dumps(result, indent=2),
                        file_name="test_results.json",
                        mime="application/json",
                        key="dl_test_results",
                    )
