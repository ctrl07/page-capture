"""Custom extraction rule engine for SeleniumBase CDP."""

from __future__ import annotations

import json
import re
from pathlib import Path

EXTRACTION_TYPES = ["text", "attribute", "html", "count", "exists"]

HERE = Path(__file__).resolve().parent
RULESETS_DIR = HERE / "rulesets"


def _js(s: str) -> str:
    return json.dumps(s)


def build_extraction_js(rules: list[dict]) -> str:
    parts: list[str] = []
    for rule in rules:
        name = _js(rule["name"])
        sel = _js(rule.get("selector", ""))
        xtype = rule.get("type", "text")
        attr = rule.get("attribute", "")
        multi = rule.get("multiple", False)

        if xtype == "count":
            parts.append(f"r[{name}]=document.querySelectorAll({sel}).length")
        elif xtype == "exists":
            parts.append(f"r[{name}]=document.querySelector({sel})!==null")
        elif xtype == "attribute":
            if multi:
                parts.append(
                    f"r[{name}]=Array.from(document.querySelectorAll({sel}))"
                    f".map(e=>e.getAttribute({_js(attr)})||'')"
                )
            else:
                parts.append(
                    f"{{let e=document.querySelector({sel});"
                    f"r[{name}]=e?e.getAttribute({_js(attr)})||'':''}}"
                )
        elif xtype == "html":
            if multi:
                parts.append(
                    f"r[{name}]=Array.from(document.querySelectorAll({sel}))"
                    f".map(e=>e.innerHTML.trim())"
                )
            else:
                parts.append(
                    f"{{let e=document.querySelector({sel});"
                    f"r[{name}]=e?e.innerHTML.trim():''}}"
                )
        else:  # text
            if multi:
                parts.append(
                    f"r[{name}]=Array.from(document.querySelectorAll({sel}))"
                    f".map(e=>e.textContent.trim())"
                )
            else:
                parts.append(
                    f"{{let e=document.querySelector({sel});"
                    f"r[{name}]=e?e.textContent.trim():''}}"
                )

    js = "(()=>{var r={};" + ";".join(parts) + ";return JSON.stringify(r);})()"
    return js


def apply_regex(value, pattern: str):
    if not pattern:
        return value
    try:
        if isinstance(value, list):
            return [apply_regex(v, pattern) for v in value]
        m = re.search(pattern, str(value))
        return m.group(0) if m else value
    except re.error:
        return value


def extract_from_page(sb, rules: list[dict]) -> dict:
    if not rules:
        return {}
    js = build_extraction_js(rules)
    raw = sb.cdp.evaluate(js)
    data = json.loads(raw or "{}")
    for rule in rules:
        name = rule["name"]
        regex = rule.get("regex", "")
        if regex and name in data:
            data[name] = apply_regex(data[name], regex)
    return data


def save_ruleset(rules: list[dict], name: str) -> Path:
    RULESETS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\- ]", "", name).strip()
    if not safe:
        raise ValueError("Invalid rule set name")
    path = RULESETS_DIR / f"{safe}.json"
    path.write_text(json.dumps(rules, indent=2), encoding="utf-8")
    return path


def load_ruleset(name: str) -> list[dict]:
    safe = re.sub(r"[^\w\- ]", "", name).strip()
    path = RULESETS_DIR / f"{safe}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def delete_ruleset(name: str) -> bool:
    safe = re.sub(r"[^\w\- ]", "", name).strip()
    path = RULESETS_DIR / f"{safe}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def list_rulesets() -> list[str]:
    if not RULESETS_DIR.exists():
        return []
    return sorted(p.stem for p in RULESETS_DIR.iterdir() if p.suffix == ".json")


def render_rules_editor(
    *,
    allow_run: bool = True,
    run_disabled: bool = False,
    runtime_cfg: dict | None = None,
) -> list[dict]:
    """Render the extraction rules editor UI.

    Returns the current rules list from session state.
    If allow_run=True, includes the run form at the bottom (caller should
    use st.form_submit_button separately).
    """
    import streamlit as st

    st.caption("Define custom CSS selector rules to extract data from pages.")
    rules: list[dict] = st.session_state.get("extraction_rules", [])

    if rules:
        header_cols = st.columns([2, 3, 1.5, 1.5, 0.8])
        header_cols[0].markdown("**Field**")
        header_cols[1].markdown("**Selector**")
        header_cols[2].markdown("**Type**")
        header_cols[3].markdown("**Attr**")
        header_cols[4].markdown("**Multi**")

        for i in range(len(rules) - 1, -1, -1):
            if i >= len(st.session_state.extraction_rules):
                continue
            _render_rule_row(i, st.session_state.extraction_rules[i])

        with st.expander("Regex (optional)", expanded=False):
            for i, rule in enumerate(st.session_state.extraction_rules):
                rule["regex"] = st.text_input(
                    f"Regex — {rule.get('name', f'Rule {i+1}')}",
                    value=rule.get("regex", ""), key=f"er_regex_{i}",
                    placeholder="Optional regex to extract from result",
                )

    if st.button("+ Add Rule", key="er_add_rule"):
        st.session_state.extraction_rules.append({
            "name": "", "selector": "", "type": "text",
            "attribute": "", "regex": "", "multiple": False,
        })
        st.rerun()

    if rules:
        with st.expander("Test Rules (live preview)", expanded=False):
            preview_url = st.text_input(
                "Test URL", placeholder="https://example.com", key="er_preview_url",
            )
            if preview_url and st.button("Test", key="er_preview_btn"):
                from importers import is_valid_url
                if not is_valid_url(preview_url):
                    st.error("Invalid URL.")
                else:
                    with st.spinner("Running preview (UI will freeze temporarily)..."):
                        try:
                            from seleniumbase import SB

                            from page_capture import PageCapture
                            from runners import build_runtime_config
                            _cfg = runtime_cfg or build_runtime_config(
                                {"viewport": {"width": 1920, "height": 1080}, "timing": {"stabilization_ms": 800, "inter_page_delay_min": 0.3, "inter_page_delay_max": 0.5}},
                                {"width": 1920, "height": 1080},
                                800,
                            )
                            with SB(
                                uc=True, test=True, headless=False,
                                window_size=f"{_cfg['viewport']['width']},{_cfg['viewport']['height']}",
                            ) as sb:
                                page = PageCapture(sb, _cfg)
                                page.open(preview_url)
                                page.scroll()
                                sb.sleep(_cfg["timing"]["stabilization_ms"] / 1000)
                                page.hide_overlays()
                                data = extract_from_page(sb, rules)
                                if data:
                                    for k, v in data.items():
                                        st.text(f"{k}: {v}")
                                else:
                                    st.info("No data extracted. Check your selectors.")
                        except Exception as e:
                            st.error(f"Preview failed: {e}")

    st.markdown("---")
    col_save, col_load, col_del, _ = st.columns([1, 1, 1, 4])
    with col_save:
        rs_name = st.text_input(
            "Rule set name", key="er_rs_name",
            placeholder="my-rules", label_visibility="collapsed",
        )
        if st.button("Save", key="er_save") and rs_name.strip():
            save_ruleset(st.session_state.extraction_rules, rs_name.strip())
            st.success(f"Saved as {rs_name.strip()}.json")
    with col_load:
        rs_list = list_rulesets()
        if rs_list:
            selected_rs = st.selectbox(
                "Load", [""] + rs_list,
                key="er_rs_load", label_visibility="collapsed",
            )
            if selected_rs and st.button("Load", key="er_load"):
                st.session_state.extraction_rules = load_ruleset(selected_rs)
                st.rerun()
    with col_del:
        if rs_list:
            del_rs = st.selectbox(
                "Delete", [""] + rs_list,
                key="er_rs_del", label_visibility="collapsed",
            )
            if del_rs and st.button("Delete", key="er_del_rs"):
                delete_ruleset(del_rs)
                st.rerun()

    return st.session_state.get("extraction_rules", [])


def _render_rule_row(i: int, rule: dict) -> None:
    """Render a single rule editor row."""
    import streamlit as st

    cols = st.columns([2, 3, 1.5, 1.5, 0.8, 0.5])
    with cols[0]:
        rule["name"] = st.text_input(
            "Field", value=rule.get("name", ""),
            key=f"er_name_{i}", label_visibility="collapsed", placeholder="Field name",
        )
    with cols[1]:
        rule["selector"] = st.text_input(
            "Selector", value=rule.get("selector", ""),
            key=f"er_sel_{i}", label_visibility="collapsed", placeholder="CSS selector",
        )
    with cols[2]:
        rule["type"] = st.selectbox(
            "Type", EXTRACTION_TYPES,
            index=EXTRACTION_TYPES.index(rule.get("type", "text")),
            key=f"er_type_{i}", label_visibility="collapsed",
        )
    with cols[3]:
        rule["attribute"] = st.text_input(
            "Attr", value=rule.get("attribute", ""),
            key=f"er_attr_{i}", label_visibility="collapsed", placeholder="href/src/alt",
        )
    with cols[4]:
        rule["multiple"] = st.checkbox(
            "M", value=rule.get("multiple", False),
            key=f"er_multi_{i}", label_visibility="collapsed",
            help="Multiple values",
        )
    with cols[5]:
        st.button(
            "✕", key=f"er_del_{i}",
            on_click=lambda idx=i: st.session_state.extraction_rules.pop(idx),
        )
