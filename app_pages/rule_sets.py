"""Rule Sets page — extraction rule editor with templates, validation, import/export."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from extraction import render_rules_editor
from page_capture import load_config
from runners import HERE, build_runtime_config
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


def page_rule_sets() -> None:
    st.subheader("Rule Sets")
    st.caption("Define custom CSS selector rules to extract data from pages. Use templates for common patterns.")

    runtime_cfg = build_runtime_config(CONFIG, CONFIG["viewport"], CONFIG["timing"]["stabilization_ms"])

    tabs = st.tabs(["Editor", "Templates", "Import/Export"])

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
