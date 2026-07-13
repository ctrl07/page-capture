# Page Capture — Agent Context

## Project Overview
Desktop Streamlit app for website migration audits: screenshots, SEO extraction, custom CSS-selector extraction, unified crawl combining all collectors in one browser session. Uses SeleniumBase with CDP for bot-bypass browser automation. Deployed as a local GUI via `launch.bat`.

## Project Location
```
S:\capture\page-capture\
```

## Directory Structure
```
S:\capture\page-capture\
  ├── app.py              # Main Streamlit UI + page functions + router
  ├── runners.py          # CaptureRunner, ExtractionRunner, UnifiedRunner + helpers
  ├── run_capture.py      # CLI runner (standalone, not used by app)
  ├── page_capture.py     # PageCapture class (SeleniumBase CDP wrapper)
  ├── extraction.py       # CSS selector extraction rule engine
  ├── importers.py        # URL import (sitemap, CSV, WP XML)
  ├── config.yaml         # Viewport, timing, overlay-hide selectors
  ├── pyproject.toml      # uv dependency manifest
  ├── launch.bat          # One-click launcher: `uv sync && uv run streamlit run app.py`
  ├── uv.lock             # Lockfile
  └── rulesets/           # Saved extraction rule sets (JSON)
```

## Architecture

### Sidebar Navigation (`st.navigation`)
```
Capture
  🚀 Unified Crawl      (page_unified_crawl)  — default page
  📷 Screenshots         (page_screenshots)
  📊 Data Extraction     (page_extraction)
Tools
  📥 Import URLs         (page_import)
Library
  📜 History             (page_history)
  ⚙️ Settings            (page_settings)
```

- `main()` is called at module level (not inside `if __name__`)
- Pages grouped into sections via `st.navigation(pages, position="sidebar")`
- `_init_session_state()` initializes all session state keys at startup

### Browser Automation (SeleniumBase CDP)
- All browser interaction uses SeleniumBase with `sb.uc=True` (undetected mode)
- CDP via `sb.cdp.evaluate()` for JS execution (scrolling, overlay hiding, data extraction)
- `PageCapture` class in `page_capture.py`: `open()`, `scroll()`, `hide_overlays()`, `capture_png()`
- One browser session per run (reused across all URLs)
- Background thread with cancellation support

### Runner Classes (`runners.py`)
| Class | Purpose |
|-------|---------|
| `CaptureRunner` | Screenshots only (optional PDF via img2pdf) |
| `ExtractionRunner` | Custom CSS extraction (uses `extract_from_page`) |
| `UnifiedRunner` | Combines multiple collectors in one browser session |

### Key Patterns
- **Progress polling**: Generic `_run_with_progress()` helper — polls `runner._thread.is_alive()` in a `while` loop with `time.sleep(0.3)`, updates progress bar
- **Session State**: `runner`, `running`, `capture_urls`, `unified_runner`, `unified_running`, `extraction_rules`, `extraction_runner`
- **URLs passed between tabs**: `st.session_state.capture_urls` (Import → Unified Crawl / Screenshots)
- **History**: Flat JSON file `.run_history.json`, last 50 entries, keyed by timestamp with kind + results + output_dir
- **Results viewer**: `render_results()` with `st.segmented_control` status filter, URL search, `st.dataframe` with `on_select="rerun"` for row-click detail panel, `st.column_config.LinkColumn` for clickable URLs

### Dependencies
- **Streamlit** ≥1.42 — `st.navigation`, `st.Page`, `st.segmented_control`, `st.dataframe(on_select)`, `st.column_config.LinkColumn`
- **SeleniumBase** — `SB(uc=True, test=True, headless=False)`, CDP via `sb.cdp.evaluate()`
- **Pandas** — `DataFrame` display, CSV export
- **img2pdf** — PNG-to-PDF conversion with DPI detection (replaces CDP `printToPDF`)
- **Pillow** — Image dimension reading for img2pdf
- **PyYAML** — config.yaml load/save (in SeleniumBase dep chain)

### Development Workflow
- **Launch**: `launch.bat` — runs `uv sync && uv run streamlit run app.py`
- **Lint**: `uv run ruff check`
- **Typecheck**: `uv run pyright` (1 pre-existing error: `st.components` attribute)
- **No tests**: Local GUI tool, no test suite currently
- **Commit**: Uses git, pushes to `origin/main`

## Current State

### Completed
- Sidebar navigation (`st.navigation` with Capture / Tools / Library sections)
- Unified Crawl (`UnifiedRunner` — multiple collectors in one browser session)
- Improved results viewer (search, status filter, sortable columns, row-click detail)
- img2pdf PNG→PDF with DPI detection (replaces CDP `printToPDF`)
- Config-driven scroll/timing (100ms scroll, 800ms stabilise)
- Extraction rules editor (CSS selectors, regex, save/load/delete rule sets)
- Import URLs (manual, sitemap URL, sitemap XML, CSV, WP XML)
- History (browse, re-run, delete past runs)
- `launch.bat` one-click launcher

### Pending
- Dashboard landing page with last-run summary metrics
- Dark mode toggle
- Project system (scope TBD)

## Key Decisions
- **No cloud deployment** — local-only desktop app, no CI/CD
- **No Playwright** — SeleniumBase with CDP handles all browser automation
- **No httpx** — `requests` available via SeleniumBase dep chain
- **CSS selectors** for custom extraction (no XPath) — JS-based via CDP
- **No external database** — flat JSON for history, JSON files for extraction rulesets
- **img2pdf over CDP printToPDF** — CDP version lost page dimensions; img2pdf is reliable and DPI-aware
- **Single browser session per run** — `UnifiedRunner` reuses one SB instance for screenshots + extraction

## Agents

Three specialized subagents available in `.opencode/agents/`:

| Agent | Purpose |
|-------|---------|
| `seleniumbase-cdp` | SeleniumBase CDP browser automation expert. Use for all browser interaction, CDP evaluation, page capture, overlay hiding, bot bypass. |
| `streamlit-ui` | Streamlit UI expert. Use for tabs, forms, session state, progress indicators, data tables, download buttons, any `st.*` widget. |
| `api-writer` | REST/GraphQL API writer for external apps. Use for FastAPI/Flask routes, Pydantic models, auth, database schemas. |

All agents use Context7 MCP for up-to-date library documentation.
