"""Progress bar helper for runners with callback-based updates."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import streamlit as st


@dataclass
class ProgressState:
    """Thread-safe progress state updated via callbacks."""
    done: int = 0
    total: int = 0
    status: str = ""
    updated: float = field(default_factory=time.time)


_PROGRESS_REGISTRY: dict[str, ProgressState] = {}


def _make_callback(key: str) -> callable:
    """Create a progress callback that updates the registry."""
    def callback(done: int, total: int, status: str) -> None:
        state = _PROGRESS_REGISTRY.get(key)
        if state:
            state.done = done
            state.total = total
            state.status = status
            state.updated = time.time()
    return callback


def run_with_progress(runner, key_prefix: str, label: str = "") -> None:
    """Generic progress loop using callback-based updates when available.

    Falls back to direct attribute polling when the runner doesn't support
    callbacks (backward compatibility).
    """
    status_placeholder = st.empty()
    progress_bar = st.progress(0)

    if st.button("Cancel", key=f"cancel_{key_prefix}"):
        runner.cancelled = True

    if not runner._thread or not runner._thread.is_alive():
        progress_key = f"{key_prefix}_{id(runner)}"
        cb = _make_callback(progress_key)
        _PROGRESS_REGISTRY[progress_key] = ProgressState()

        # Register callback if runner supports it
        if hasattr(runner, "progress_callback") and runner.progress_callback is None:
            runner.progress_callback = cb
        # Also mark for cleanup
        runner._progress_key = progress_key

        runner._thread = threading.Thread(target=runner.run, daemon=True)
        runner._thread.start()

    start_time = time.time()
    progress_key = getattr(runner, "_progress_key", None)
    alive = True
    while alive:
        alive = runner._thread.is_alive()

        if progress_key and progress_key in _PROGRESS_REGISTRY:
            state = _PROGRESS_REGISTRY[progress_key]
            done = state.done
            total = state.total
            status_msg = state.status
        else:
            done = getattr(runner, "progress_done", len(getattr(runner, "results", [])))
            total = getattr(runner, "progress_total", len(getattr(runner, "urls", [])))
            status_msg = getattr(runner, "status", "")

        pct = min(done / total, 1.0) if total else 0
        elapsed = time.time() - start_time

        elapsed_m = int(elapsed) // 60
        elapsed_s = int(elapsed) % 60
        elapsed_text = f"{elapsed_m}m {elapsed_s}s" if elapsed_m else f"{elapsed_s}s"

        progress_bar.progress(pct, text=f"{done}/{total} | {elapsed_text} elapsed")
        if status_msg:
            status_placeholder.caption(status_msg)
        elif label:
            status_placeholder.caption(label)

        if not alive:
            break
        time.sleep(0.3)

    # Cleanup
    if progress_key and progress_key in _PROGRESS_REGISTRY:
        _PROGRESS_REGISTRY.pop(progress_key, None)
