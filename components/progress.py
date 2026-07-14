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
    last_done = 0
    last_tick = start_time
    avg_secs_per_item = 0.0
    alive = True
    while alive:
        alive = runner._thread.is_alive()
        done = getattr(runner, "progress_done", len(getattr(runner, "results", [])))
        total = getattr(runner, "progress_total", len(getattr(runner, "urls", [])))
        pct = min(done / total, 1.0) if total else 0
        now = time.time()
        elapsed = now - start_time

        # Update rolling average of time-per-item
        if done > last_done:
            delta = now - last_tick
            items_done = done - last_done
            item_rate = delta / items_done
            if avg_secs_per_item == 0:
                avg_secs_per_item = item_rate
            else:
                # Exponential moving average: weight recent items 60%
                avg_secs_per_item = 0.4 * avg_secs_per_item + 0.6 * item_rate
            last_tick = now
            last_done = done

        # ETA
        eta_text = ""
        if done > 0 and total > done and avg_secs_per_item > 0:
            eta_secs = int(avg_secs_per_item * (total - done))
            if eta_secs >= 60:
                eta_text = f" | ETA ~{eta_secs // 60}m {eta_secs % 60}s"
            else:
                eta_text = f" | ETA ~{eta_secs}s"

        # Elapsed time
        elapsed_m = int(elapsed) // 60
        elapsed_s = int(elapsed) % 60
        elapsed_text = f"{elapsed_m}m {elapsed_s}s" if elapsed_m else f"{elapsed_s}s"

        progress_bar.progress(pct, text=f"{done}/{total} | {elapsed_text} elapsed{eta_text}")
        status_msg = runner.status if hasattr(runner, "status") and runner.status else label
        if status_msg:
            status_placeholder.caption(status_msg)
        if not alive:
            break
        time.sleep(0.3)
