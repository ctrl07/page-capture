"""Session state management and active-run persistence.

Module-level runner registry survives Streamlit reruns within the same process.
Disk manifest persists across process restarts.
"""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

from runners import HERE

_MANIFEST = HERE / ".active_run.json"


# ── Module-level runner registry ──

_ACTIVE_RUNNERS: dict[str, dict[str, Any]] = {}


def register_runner(runner: Any) -> None:
    """Store runner in module-level registry + write disk manifest."""
    key = str(runner.output_dir)
    kind = "unified"
    if hasattr(runner, "_refresh_session"):
        kind = "fast_seo"
    elif hasattr(runner, "_compare_entry"):
        kind = "blog_audit"

    _ACTIVE_RUNNERS[key] = {
        "runner": runner,
        "output_dir": str(runner.output_dir),
        "urls": getattr(runner, "urls", getattr(runner, "source_urls", [])),
        "total": getattr(runner, "progress_total", 0),
        "kind": kind,
    }
    _write_manifest(runner)


def unregister_runner(runner: Any) -> None:
    """Remove runner from registry."""
    key = str(runner.output_dir)
    _ACTIVE_RUNNERS.pop(key, None)
    _clear_manifest()


def _write_manifest(runner: Any) -> None:
    """Write active run manifest to disk."""
    kind = "unified"
    if hasattr(runner, "_refresh_session"):
        kind = "fast_seo"
    elif hasattr(runner, "_compare_entry"):
        kind = "blog_audit"

    manifest = {
        "output_dir": str(runner.output_dir),
        "total": getattr(runner, "progress_total", 0),
        "urls_count": len(getattr(runner, "url_pairs", getattr(runner, "urls", []))),
        "kind": kind,
    }
    try:
        _MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        pass


def _clear_manifest() -> None:
    """Remove active run manifest from disk."""
    try:
        if _MANIFEST.exists():
            _MANIFEST.unlink()
    except OSError:
        pass


def has_active_run() -> bool:
    """Check if there's an active run (module-level or disk manifest)."""
    return bool(_ACTIVE_RUNNERS) or _MANIFEST.exists()


def get_manifest() -> dict | None:
    """Read the disk manifest, if it exists."""
    if not _MANIFEST.exists():
        return None
    try:
        return json.loads(_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ── Streamlit session state init ──

def init_session_state() -> None:
    """Initialize all session state keys at startup."""
    defaults = {
        "capture_urls": None,
        "extraction_rules": [],
        "unified_runner": None,
        "unified_running": False,
        "blog_audit_runner": None,
        "blog_audit_running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Recover active run from module-level registry (survives Streamlit reruns)
    if _ACTIVE_RUNNERS and not (st.session_state.get("unified_running") or st.session_state.get("blog_audit_running")):
        for key, entry in _ACTIVE_RUNNERS.items():
            runner = entry["runner"]
            thread = getattr(runner, "_thread", None)
            if thread and thread.is_alive():
                kind = entry.get("kind", "unified")
                if kind == "blog_audit":
                    st.session_state.blog_audit_runner = runner
                    st.session_state.blog_audit_running = True
                else:
                    st.session_state.unified_runner = runner
                    st.session_state.unified_running = True
                break
