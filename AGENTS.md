# Page Capture — Agent Context

## Project Overview
Desktop Streamlit app for website migration work: screenshots, SEO data extraction, custom CSS-selector extraction, Google Maps geocoding. Uses SeleniumBase with CDP for browser automation and is deployed as a local GUI via `launch.bat`.

## Project Location
```
S:\capture\page-capture\
```

## Directory Structure
```
S:\capture\page-capture\
  ├── app.py              # Main Streamlit UI (6 tabs)
  ├── run_capture.py      # CLI runner
  ├── page_capture.py     # PageCapture class (CDP browser wrapper)
  ├── extraction.py       # Custom extraction rule engine
  ├── geocode.py          # Google Maps business lookup via CDP
  ├── importers.py        # URL import (sitemap, CSV, WP XML)
  ├── config.yaml         # Viewport/delays/overlay config
  ├── pyproject.toml      # uv dependency manifest
  ├── launch.bat          # One-click launcher: `uv sync && uv run streamlit run app.py`
  ├── uv.lock             # Lockfile
  └── rulesets/           # Saved extraction rule sets (JSON)
```

## Architecture

### App Tabs (flat, no sidebar currently)
1. **Import URLs** — Manual, sitemap URL, sitemap XML, CSV, WP XML
2. **Screenshots** — Capture PNG screenshots (with optional PDF)
3. **Data Extraction** — Quick SEO (built-in JS) or Custom Rules (CSS selectors)
4. **Geocoding** — Google Maps business lookup via CDP (not API key)
5. **Settings** — Config editor + output folder management
6. **History** — Browse/rerun/delete past runs

### Browser Automation (SeleniumBase CDP)
- All browser interaction uses SeleniumBase with `uc=True` (undetected mode)
- CDP (Chrome DevTools Protocol) via `sb.cdp.evaluate()` for JS execution
- `PageCapture` class in `page_capture.py` wraps: open, scroll, hide overlays, capture PNG
- One browser session per run (reused across all URLs)
- Runs in a background thread with cancellation support

### Runner Classes
| Class | File | Purpose |
|-------|------|---------|
| `CaptureRunner` | `app.py` | Screenshots + Quick SEO (uses `PageCapture`) |
| `ExtractionRunner` | `app.py` | Custom CSS extraction (uses `extract_from_page`) |
| `GeoRunner` | `geocode.py` | Google Maps business lookup |

### Key Patterns
- **Threading**: Each runner spawns a `threading.Thread` with `daemon=True`. The UI polls `runner._thread.is_alive()` in a `while` loop with `time.sleep(0.3)` to show progress.
- **Session State**: `st.session_state` stores `runner`, `running`, `capture_urls`, `geo_runner`, `geo_running`, `geo_history`, `extraction_rules`, `extraction_runner`.
- **URLs passed between tabs**: `st.session_state.ss_urls_text` / `st.session_state.seo_urls_text` / `st.session_state.capture_urls`.
- **Progress polling** pattern (repeated in 3 places):
  ```python
  if not runner._thread or not runner._thread.is_alive():
      runner._thread = threading.Thread(target=runner.run, daemon=True)
      runner._thread.start()
  alive = True
  while alive:
      alive = runner._thread.is_alive()
      done = len(runner.results)
      total = len(runner.urls)
      pct = min(done / total, 1.0) if total else 0
      progress_bar.progress(pct, text=f"{done}/{total}")
      ...
      if not alive: break
      time.sleep(0.3)
  ```
- **History**: Flat JSON file `S:\capture\page-capture\.run_history.json`, last 50 entries, keyed by timestamp with kind (screenshot/seo/extraction), results, output_dir.

### Dependencies
- **Streamlit** ≥1.28 — `st.tabs`, `st.form`, `st.columns`, `st.session_state`, `st.rerun`, `st.file_uploader`, `st.dataframe`, `st.download_button`
- **SeleniumBase** — `SB(uc=True, test=True, headless=False)`, CDP via `sb.cdp.evaluate()`
- **Pandas** — `DataFrame` display, CSV export
- **Requests** — sitemap import (already in SeleniumBase dep chain)
- **PyYAML** — config.yaml load/save (already in SeleniumBase dep chain)

### Development Workflow
- **Launch**: `launch.bat` — runs `uv sync && uv run streamlit run app.py`
- **Lint/typecheck**: `uv run ruff check`, `uv run pyright`
- **No tests**: The app is a local GUI tool, no test suite currently
- **Commit**: Uses git, pushes to `origin/main`

## Current State

### Completed
- Full app with 6 tabs, all runners, importers, geocoding, extraction rules
- `launch.bat` one-click launcher
- All `use_container_width` → `width="stretch"` deprecation fixes

### Pending
- Sidebar navigation + project system (Ahrefs-inspired UI overhaul)
- Dashboard landing page with metrics
- Unified Crawl (merge Screenshots + Extraction into one batch)
- Improved results viewer (sortable, filterable, side panel)
- Dark mode toggle

## Key Decisions
- **No cloud deployment** — local-only desktop app, no CI/CD
- **No Google API key** — geocoding scrapes Google Maps via CDP instead
- **No Nominatim/OSM** — exact coordinates come from `@lat,lng,zoom` in Google Maps URL
- **No Playwright** — SeleniumBase with CDP handles all browser automation
- **No httpx** — `requests` is available via SeleniumBase dep chain
- **CSS selectors** for custom extraction (no XPath) — JS-based via CDP
- **No external database** — flat JSON for history, JSON files for extraction rulesets
