"""Custom extraction rule engine for SeleniumBase CDP."""

from __future__ import annotations

import json
import re
from pathlib import Path

EXTRACTION_TYPES = ["text", "attribute", "html", "count", "exists", "meta"]

HERE = Path(__file__).resolve().parent
RULESETS_DIR = HERE / "rulesets"

SEO_FIELD_CATEGORIES = ["meta", "headings", "open_graph", "twitter", "links", "images", "schema", "technical"]

STANDARD_SEO_FIELDS: list[dict] = [
    {"name": "title", "description": "Page <title> tag", "category": "meta", "type": "builtin", "js_key": "title"},
    {"name": "title_len", "description": "Character count of title", "category": "meta", "type": "derived", "derived_from": "title"},
    {"name": "meta_description", "description": "Meta description content", "category": "meta", "type": "meta", "selector": 'meta[name="description"]', "attribute": "name"},
    {"name": "meta_desc_len", "description": "Character count of meta description", "category": "meta", "type": "derived", "derived_from": "meta_description"},
    {"name": "canonical", "description": "Canonical link href", "category": "meta", "type": "builtin", "js_key": "canonical"},
    {"name": "robots_meta", "description": "Meta robots directive", "category": "meta", "type": "meta", "selector": 'meta[name="robots"]', "attribute": "name"},
    {"name": "h1", "description": "First H1 heading", "category": "headings", "type": "builtin", "js_key": "h1"},
    {"name": "h2s", "description": "All H2 headings (pipe-separated)", "category": "headings", "type": "builtin", "js_key": "h2s"},
    {"name": "h3s", "description": "All H3 headings (pipe-separated)", "category": "headings", "type": "builtin", "js_key": "h3s"},
    {"name": "og_title", "description": "Open Graph title", "category": "open_graph", "type": "meta", "selector": 'meta[property="og:title"]', "attribute": "property"},
    {"name": "og_description", "description": "Open Graph description", "category": "open_graph", "type": "meta", "selector": 'meta[property="og:description"]', "attribute": "property"},
    {"name": "og_image", "description": "Open Graph image URL", "category": "open_graph", "type": "meta", "selector": 'meta[property="og:image"]', "attribute": "property"},
    {"name": "schema_types", "description": "JSON-LD @type values (pipe-separated)", "category": "schema", "type": "builtin", "js_key": "schemaTypes"},
    {"name": "word_count", "description": "Total word count", "category": "technical", "type": "builtin", "js_key": "wordCount"},
    {"name": "internal_links", "description": "Internal link count", "category": "links", "type": "builtin", "js_key": "internal"},
    {"name": "external_links", "description": "External link count", "category": "links", "type": "builtin", "js_key": "external"},
    {"name": "images_missing_alt", "description": "Images missing alt attribute", "category": "images", "type": "builtin", "js_key": "imagesMissingAlt"},
]

EXTENDED_SEO_FIELDS: list[dict] = [
    {"name": "og_type", "description": "Open Graph type", "category": "open_graph", "type": "meta", "selector": 'meta[property="og:type"]', "attribute": "property"},
    {"name": "og_url", "description": "Open Graph URL", "category": "open_graph", "type": "meta", "selector": 'meta[property="og:url"]', "attribute": "property"},
    {"name": "og_site_name", "description": "Open Graph site name", "category": "open_graph", "type": "meta", "selector": 'meta[property="og:site_name"]', "attribute": "property"},
    {"name": "og_locale", "description": "Open Graph locale", "category": "open_graph", "type": "meta", "selector": 'meta[property="og:locale"]', "attribute": "property"},
    {"name": "twitter_card", "description": "Twitter card type", "category": "twitter", "type": "meta", "selector": 'meta[name="twitter:card"]', "attribute": "name"},
    {"name": "twitter_title", "description": "Twitter title", "category": "twitter", "type": "meta", "selector": 'meta[name="twitter:title"]', "attribute": "name"},
    {"name": "twitter_description", "description": "Twitter description", "category": "twitter", "type": "meta", "selector": 'meta[name="twitter:description"]', "attribute": "name"},
    {"name": "twitter_image", "description": "Twitter image URL", "category": "twitter", "type": "meta", "selector": 'meta[name="twitter:image"]', "attribute": "name"},
    {"name": "twitter_site", "description": "Twitter site handle", "category": "twitter", "type": "meta", "selector": 'meta[name="twitter:site"]', "attribute": "name"},
    {"name": "html_lang", "description": "HTML lang attribute", "category": "meta", "type": "builtin", "js_key": "htmlLang"},
    {"name": "meta_viewport", "description": "Viewport meta tag", "category": "meta", "type": "meta", "selector": 'meta[name="viewport"]', "attribute": "name"},
    {"name": "meta_charset", "description": "Character encoding", "category": "meta", "type": "builtin", "js_key": "metaCharset"},
    {"name": "hreflang", "description": "Hreflang alternate links (pipe-separated)", "category": "meta", "type": "builtin", "js_key": "hreflang"},
    {"name": "jsonld_full", "description": "Full JSON-LD raw text", "category": "schema", "type": "builtin", "js_key": "jsonldFull"},
    {"name": "images_total", "description": "Total image count", "category": "images", "type": "count", "selector": "img"},
    {"name": "images_no_lazy", "description": "Images without loading='lazy'", "category": "images", "type": "builtin", "js_key": "imagesNoLazy"},
    {"name": "iframe_count", "description": "Embedded iframe count", "category": "images", "type": "count", "selector": "iframe"},
    {"name": "form_count", "description": "Form element count", "category": "images", "type": "count", "selector": "form"},
    {"name": "external_nofollow", "description": "External nofollow links", "category": "links", "type": "builtin", "js_key": "externalNofollow"},
]

ALL_SEO_FIELDS: list[dict] = STANDARD_SEO_FIELDS + EXTENDED_SEO_FIELDS


def get_standard_seo_fields() -> list[dict]:
    """Return a copy of the standard 15 SEO fields."""
    return json.loads(json.dumps(STANDARD_SEO_FIELDS))


def get_seo_fields_by_category() -> dict[str, list[dict]]:
    """Return all SEO fields grouped by category."""
    cats: dict[str, list[dict]] = {}
    for f in ALL_SEO_FIELDS:
        cat = f.get("category", "other")
        cats.setdefault(cat, []).append(f)
    return cats


def get_seo_field_names(fields: list[dict] | None = None) -> list[str]:
    """Return the ordered list of field names from the given (or standard) fields."""
    if fields is None:
        fields = get_standard_seo_fields()
    return [f["name"] for f in fields]


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
        elif xtype == "meta":
            attr_key = rule.get("attribute", "name")
            if multi:
                parts.append(
                    f"r[{name}]=Array.from(document.querySelectorAll('meta[{attr_key}]'))"
                    f".map(e=>e.getAttribute('content')||'')"
                )
            else:
                sel_meta = rule.get("selector", "")
                if sel_meta:
                    # selector-based: e.g. meta[name="description"]
                    parts.append(
                        f"{{let e=document.querySelector({sel});"
                        f"r[{name}]=e?e.getAttribute('content')||'':''}}"
                    )
                else:
                    # fallback empty
                    parts.append(f"r[{name}]=''")
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


# JS helpers included once at the top of the SEO IIFE
_SEO_JS_HELPERS = r"""
    const q = (s) => document.querySelector(s);
    const qa = (s) => Array.from(document.querySelectorAll(s));
    const metaContent = (attr, val) => {
        const el = document.querySelector(`meta[${attr}="${val}"]`);
        return el ? (el.getAttribute('content') || '') : '';
    };
    const _contentArea = (() => {
        for (const sel of [
            'main', 'article', '[role="main"]', '[role="article"]',
            '.content', '.main-content', '.post-content', '.entry-content',
            '.article-content', '.page-content', '.site-content',
            '#content', '#main-content', '#main', '#mainContent',
        ]) {
            const el = document.querySelector(sel);
            if (el && el.querySelectorAll('h2, h3').length > 0) return el;
        }
        return null;
    })();
    const _headings = (tag, max) => {
        const scope = _contentArea || document;
        const seen = new Set();
        const out = [];
        for (const el of scope.querySelectorAll(tag)) {
            const t = el.innerText.trim().replace(/\s+/g, ' ');
            if (t && !seen.has(t)) { seen.add(t); out.push(t); }
            if (out.length >= max) break;
        }
        return out.join(' | ');
    };
"""

# Map of js_key → JS expression for builtin fields
_SEO_JS_EXPRS: dict[str, str] = {
    "title": "document.title || ''",
    "canonical": """(q('link[rel="canonical"]') || {}).href || ''""",
    "h1": "((_contentArea || document).querySelector('h1') || {innerText: ''}).innerText.trim()",
    "h2s": "_headings('h2', 15)",
    "h3s": "_headings('h3', 15)",
    "schemaTypes": (
        """qa('script[type="application/ld+json"]')"""
        ".map(s => { try { const d = JSON.parse(s.textContent); return d['@type'] || ''; } catch(e) { return ''; } })"
        ".flat().filter(Boolean).join(' | ')"
    ),
    "wordCount": (
        "(document.body || {innerText: ''}).innerText || ''"
        ".trim().split(/\\s+/).filter(Boolean).length"
    ),
    "internal": r"""
        (() => {
            let c = 0;
            const host = window.location.hostname;
            qa('a[href]').forEach(a => {
                try {
                    const u = new URL(a.href, window.location.href);
                    if (u.hostname === host) c++;
                } catch(e) {}
            });
            return c;
        })()
    """,
    "external": r"""
        (() => {
            let c = 0;
            const host = window.location.hostname;
            qa('a[href]').forEach(a => {
                try {
                    const u = new URL(a.href, window.location.href);
                    if (u.hostname !== host && u.protocol.startsWith('http')) c++;
                } catch(e) {}
            });
            return c;
        })()
    """,
    "imagesMissingAlt": "qa('img').filter(_i => !_i.getAttribute('alt')).length",
    "htmlLang": "(document.documentElement.getAttribute('lang') || '')",
    "metaCharset": "(document.characterSet || document.charset || '')",
    "hreflang": (
        """qa('link[rel="alternate"][hreflang]')"""
        ".map(l => l.getAttribute('hreflang') + ':' + (l.href || ''))"
        ".filter(Boolean).join(' | ')"
    ),
    "jsonldFull": (
        """qa('script[type="application/ld+json"]')"""
        ".map(s => s.textContent.trim())"
        ".filter(Boolean).join('\\n---\\n')"
    ),
    "imagesNoLazy": (
        "qa('img').filter(_i => _i.getAttribute('loading') !== 'lazy').length"
    ),
    "externalNofollow": r"""
        (() => {
            let c = 0;
            const host = window.location.hostname;
            qa('a[href]').forEach(a => {
                try {
                    const u = new URL(a.href, window.location.href);
                    if (u.hostname !== host && u.protocol.startsWith('http')
                        && (a.getAttribute('rel') || '').includes('nofollow')) c++;
                } catch(e) {}
            });
            return c;
        })()
    """,
}


def build_seo_js(fields: list[dict]) -> str:
    """Build a single JS IIFE that extracts the given SEO field definitions.

    Each field is a dict with keys: name, type, selector (optional),
    attribute (optional), js_key (for builtins), multiple (bool).
    Derived fields (type="derived") are skipped — they are computed in Python.
    """
    parts: list[str] = []
    for f in fields:
        name = _js(f["name"])
        ftype = f.get("type", "text")

        if ftype == "derived":
            continue
        elif ftype == "builtin":
            js_key = f.get("js_key", "")
            expr = _SEO_JS_EXPRS.get(js_key, "''")
            parts.append(f"r[{name}]={expr}")
        elif ftype == "meta":
            sel = f.get("selector", "")
            if sel:
                parts.append(
                    f"{{let e=document.querySelector({_js(sel)});"
                    f"r[{name}]=e?e.getAttribute('content')||'':''}}"
                )
            else:
                parts.append(f"r[{name}]=''")
        elif ftype == "count":
            sel = f.get("selector", "")
            if sel:
                parts.append(f"r[{name}]=document.querySelectorAll({sel}).length")
            else:
                parts.append(f"r[{name}]=0")
        elif ftype == "exists":
            sel = f.get("selector", "")
            if sel:
                parts.append(f"r[{name}]=document.querySelector({sel})!==null")
            else:
                parts.append(f"r[{name}]=false")
        elif ftype == "attribute":
            sel = f.get("selector", "")
            attr = f.get("attribute", "")
            multi = f.get("multiple", False)
            if multi:
                parts.append(
                    f"r[{name}]=Array.from(document.querySelectorAll({sel}))"
                    f".map(e=>e.getAttribute({_js(attr)})||'')"
                )
            elif sel:
                parts.append(
                    f"{{let e=document.querySelector({sel});"
                    f"r[{name}]=e?e.getAttribute({_js(attr)})||'':''}}"
                )
            else:
                parts.append(f"r[{name}]=''")
        elif ftype == "html":
            sel = f.get("selector", "")
            multi = f.get("multiple", False)
            if multi:
                parts.append(
                    f"r[{name}]=Array.from(document.querySelectorAll({sel}))"
                    f".map(e=>e.innerHTML.trim())"
                )
            elif sel:
                parts.append(
                    f"{{let e=document.querySelector({sel});"
                    f"r[{name}]=e?e.innerHTML.trim():''}}"
                )
            else:
                parts.append(f"r[{name}]=''")
        else:  # text
            sel = f.get("selector", "")
            multi = f.get("multiple", False)
            if multi:
                parts.append(
                    f"r[{name}]=Array.from(document.querySelectorAll({sel}))"
                    f".map(e=>e.textContent.trim())"
                )
            elif sel:
                parts.append(
                    f"{{let e=document.querySelector({sel});"
                    f"r[{name}]=e?e.textContent.trim():''}}"
                )
            else:
                parts.append(f"r[{name}]=''")

    return "(()=>{" + _SEO_JS_HELPERS + "var r={};" + ";".join(parts) + ";return JSON.stringify(r);})()"


def parse_seo_fields(raw: str, fields: list[dict]) -> dict:
    """Parse raw JSON from build_seo_js into a flat dict, applying derived fields."""
    payload = json.loads(raw or "{}")
    result: dict = {}
    for f in fields:
        name = f["name"]
        ftype = f.get("type", "text")
        if ftype == "derived":
            src = f.get("derived_from", "")
            result[name] = len(str(payload.get(src, "")))
        else:
            result[name] = payload.get(name, "" if ftype != "count" else 0)
    return result


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
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "rules" in data:
        return data["rules"]
    if isinstance(data, list):
        return data
    return []


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


def render_seo_fields_selector(key_prefix: str = "seo_fields") -> list[dict]:
    """Render the SEO fields selector UI.

    Shows checkboxes grouped by category for standard/extended fields.
    Users can toggle fields on/off, add custom fields, and save/load presets.

    Returns the list of enabled SEO field dicts.
    """
    import streamlit as st

    state_key = f"{key_prefix}_enabled"
    if state_key not in st.session_state:
        st.session_state[state_key] = get_standard_seo_fields()

    enabled: list[dict] = st.session_state[state_key]
    enabled_names = {f["name"] for f in enabled}

    # Field list by category
    categories = get_seo_fields_by_category()
    category_labels = {
        "meta": "Meta & Document",
        "headings": "Headings",
        "open_graph": "Open Graph",
        "twitter": "Twitter Cards",
        "links": "Links",
        "images": "Images",
        "schema": "Schema / Structured Data",
        "technical": "Technical",
    }

    # Preset load/save/delete
    preset_cols = st.columns([2, 1, 1, 1])
    with preset_cols[0]:
        presets = list_rulesets()
        seo_presets = [p for p in presets if "seo" in p.lower() or p == "standard_seo"]
        if seo_presets:
            selected_preset = st.selectbox(
                "Load preset", [""] + seo_presets,
                key=f"{key_prefix}_preset_load", label_visibility="collapsed",
                placeholder="Load a preset...",
            )
            if selected_preset and st.button("Load", key=f"{key_prefix}_load_btn"):
                st.session_state[state_key] = load_ruleset(selected_preset)
                st.rerun()
    with preset_cols[1]:
        preset_name = st.text_input(
            "Preset name", key=f"{key_prefix}_preset_name",
            placeholder="my-seo-rules", label_visibility="collapsed",
        )
        if st.button("Save", key=f"{key_prefix}_save_btn") and preset_name.strip():
            save_ruleset(enabled, preset_name.strip())
            st.success(f"Saved as {preset_name.strip()}.json")
    with preset_cols[2]:
        seo_presets_del = [p for p in list_rulesets() if "seo" in p.lower() or p == "standard_seo"]
        if seo_presets_del:
            del_preset = st.selectbox(
                "Delete", [""] + seo_presets_del,
                key=f"{key_prefix}_preset_del", label_visibility="collapsed",
            )
            if del_preset and st.button("Delete", key=f"{key_prefix}_del_btn"):
                delete_ruleset(del_preset)
                st.rerun()
    with preset_cols[3]:
        if st.button("Reset defaults", key=f"{key_prefix}_reset"):
            st.session_state[state_key] = get_standard_seo_fields()
            st.rerun()

    st.markdown("---")

    # Render each category
    for cat_key, cat_fields in categories.items():
        label = category_labels.get(cat_key, cat_key.title())
        with st.expander(f"{label} ({sum(1 for f in cat_fields if f['name'] in enabled_names)}/{len(cat_fields)})", expanded=cat_key in ("meta", "open_graph")):
            for field_def in cat_fields:
                fname = field_def["name"]
                desc = field_def.get("description", "")
                is_enabled = fname in enabled_names
                new_val = st.checkbox(
                    f"`{fname}` — {desc}",
                    value=is_enabled,
                    key=f"{key_prefix}_cb_{fname}",
                )
                if new_val and not is_enabled:
                    enabled.append(field_def)
                    st.rerun()
                elif not new_val and is_enabled:
                    st.session_state[state_key] = [f for f in enabled if f["name"] != fname]
                    st.rerun()

    # Custom field form
    with st.expander("Add custom field", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            custom_name = st.text_input("Field name", key=f"{key_prefix}_custom_name", placeholder="my_custom_field")
            custom_selector = st.text_input("CSS selector", key=f"{key_prefix}_custom_sel", placeholder='meta[name="author"], .my-class')
            custom_type = st.selectbox("Type", ["text", "attribute", "html", "count", "exists", "meta", "builtin"], key=f"{key_prefix}_custom_type")
        with c2:
            custom_attr = st.text_input("Attribute (for type=attribute)", key=f"{key_prefix}_custom_attr", placeholder="href, src, alt, content")
            custom_multi = st.checkbox("Multiple values", key=f"{key_prefix}_custom_multi")
            custom_js_key = st.text_input("JS key (for builtin only)", key=f"{key_prefix}_custom_jskey", placeholder="e.g. myCustomBuiltin")
            custom_desc = st.text_input("Description", key=f"{key_prefix}_custom_desc", placeholder="What this field extracts")

        if st.button("Add field", key=f"{key_prefix}_add_custom"):
            if not custom_name.strip():
                st.error("Field name is required.")
            elif any(f["name"] == custom_name.strip() for f in ALL_SEO_FIELDS):
                st.error("Field name already exists in the built-in list.")
            elif any(f["name"] == custom_name.strip() for f in enabled):
                st.error("Field name already enabled.")
            else:
                new_field: dict = {
                    "name": custom_name.strip(),
                    "description": custom_desc.strip(),
                    "category": "technical",
                    "type": custom_type,
                    "selector": custom_selector.strip(),
                    "attribute": custom_attr.strip(),
                    "multiple": custom_multi,
                }
                if custom_type == "builtin" and custom_js_key.strip():
                    new_field["js_key"] = custom_js_key.strip()
                enabled.append(new_field)
                st.rerun()

    # Show count
    total = len(ALL_SEO_FIELDS)
    st.caption(f"{len(enabled)} of {total} built-in fields enabled")

    return enabled
