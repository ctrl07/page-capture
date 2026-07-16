"""Progress bar helper for runners."""

from __future__ import annotations

import threading
import time

import streamlit as st

from runners import CaptureRunner, ExtractionRunner, UnifiedRunner


def run_with_progress(runner: CaptureRunner | ExtractionRunner | UnifiedRunner, key_prefix: str, label: str = "") -> None:
    """Generic progress loop for any runner with _thread, results, cancelled."""
    status_placeholder = st.empty()
    progress_bar = st.progress(0)

    if st.button("Cancel", key=f"cancel_{key_prefix}"):
        runner.cancelled = True

    if not runner._thread or not runner._thread.is_alive():
        runner._thread = threading.Thread(target=runner.run, daemon=True)
        runner._thread.start()

    start_time = time.time()
    alive = True
    while alive:
        alive = runner._thread.is_alive()
        done = getattr(runner, "progress_done", len(getattr(runner, "results", [])))
        total = getattr(runner, "progress_total", len(getattr(runner, "urls", [])))
        pct = min(done / total, 1.0) if total else 0
        elapsed = time.time() - start_time

        # Elapsed time
        elapsed_m = int(elapsed) // 60
        elapsed_s = int(elapsed) % 60
        elapsed_text = f"{elapsed_m}m {elapsed_s}s" if elapsed_m else f"{elapsed_s}s"

        progress_bar.progress(pct, text=f"{done}/{total} | {elapsed_text} elapsed")
        status_msg = runner.status if hasattr(runner, "status") and runner.status else label
        if status_msg:
            status_placeholder.caption(status_msg)

        if not alive:
            break
        time.sleep(0.3)
