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
