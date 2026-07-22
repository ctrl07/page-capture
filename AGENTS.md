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
  ├── app.py              # Slim router (53 lines) — wires pages into st.navigation
  ├── state.py            # Session state init + active-run persistence (module-level registry + disk manifest)
  ├── project.py          # Project management — create/delete/edit projects, associate runs
  ├── runners.py          # FastRunner, UnifiedRunner, CaptureRunner, ExtractionRunner + helpers
  ├── page_capture.py     # PageCapture class (SeleniumBase CDP wrapper) — smooth scroll with network idle detection
  ├── extraction.py       # CSS selector extraction rule engine
  ├── importers.py        # URL import (sitemap, CSV, WP XML)
  ├── analysis.py         # SEO analysis engine — issue detection, health score, PDF report
  ├── config.yaml         # Viewport, timing, overlay-hide selectors
  ├── pyproject.toml      # uv dependency manifest
  ├── launch.bat          # One-click launcher: auto-installs uv, syncs deps, runs app
  ├── uv.lock             # Lockfile
  ├── pages/              # Streamlit page modules
  │   ├── capture.py      # New Capture — import, configure, run, monitor, results
  │   ├── dashboard.py    # Run management — browse runs, grid/list views, re-run/re-capture, project filter
  │   ├── projects.py     # Project management — create/edit/delete, view associated runs
  │   ├── rule_sets.py    # Extraction rule editor (CSS selectors, regex, save/load/delete)
  │   ├── seo_analysis.py # Post-crawl SEO health check with PDF report
  │   └── settings.py     # Config editor
  ├── components/         # Reusable Streamlit components
  │   ├── progress.py     # run_with_progress() — callback-based progress with polling fallback
  │   └── results_viewer.py # render_results(), render_results_grid(), render_results_list(), render_unified_results()
  └── rulesets/           # Saved extraction rule sets (JSON)
```

## Architecture

### Sidebar Navigation (`st.navigation`)
```
Capture
  🚀 Capture            (page_new_run)  — default page
  📊 Dashboard          (page_dashboard) — run management, re-run, re-capture, project filter
Tools
  📋 Rule Sets          (page_rule_sets)
  📈 SEO Analysis       (page_seo_analysis)
Library
  📁 Projects           (page_projects)
  ⚙️ Settings           (page_settings)
```

- `main()` is called at module level (not inside `if __name__`)
- Pages grouped into sections via `st.navigation(pages, position="sidebar")`
- `init_session_state()` initializes all session state keys at startup
- Sidebar shows active run status (progress bar + status text)

### Browser Automation (SeleniumBase CDP)
- All browser interaction uses SeleniumBase with `sb.uc=True` (undetected mode)
- CDP via `sb.cdp.evaluate()` for JS execution (scrolling, overlay hiding, data extraction)
- `PageCapture` class in `page_capture.py`: `open()`, `scroll()`, `hide_overlays()`, `capture_png()`
- **Network idle scroll**: Monkey-patches `fetch` + `XMLHttpRequest` to count pending requests; waits for all images loaded + no pending network before advancing
- One browser session per run (reused across all URLs)
- Background thread with cancellation support

### Runner Classes (`runners.py`)
| Class | Purpose |
|-------|---------|
| `CaptureRunner` | Screenshots only (optional PDF via img2pdf) |
| `ExtractionRunner` | Custom CSS extraction (uses `extract_from_page`) |
| `UnifiedRunner` | Combines multiple collectors in one browser session |
| `FastRunner` | Crawl SEO via curl_cffi (8 concurrent) after solving Turnstile once — no screenshots |

### Key Patterns
- **Network idle scroll**: After each scroll step, JS checks `img.complete` + `pendingFetch/pendingXHR === 0`; polls every 100ms up to 5s timeout. Configurable via `scroll_wait_for_idle`, `scroll_idle_timeout_ms`, `scroll_idle_poll_ms` in config.yaml.
- **Callback-based progress**: `run_with_progress()` registers a `progress_callback` on the runner. All runner classes invoke the callback on progress changes (done/total/status). Falls back to direct attribute polling when no callback is provided.
- **Session State**: `capture_urls`, `unified_runner`, `unified_running`, `extraction_rules`
- **URLs passed between pages**: `st.session_state.capture_urls` (Dashboard → Capture)
- **Projects**: Named collections of runs stored in `.projects.json`. Create/edit/delete projects, add/remove runs via dashboard drawer. Filter dashboard by project.
- **History**: Flat JSON file `.run_history.json`, last 50 entries. UnifiedRunner saves to `results_by_collector` key; all other runners save to `results` key. `get_results()` helper normalizes both formats.
- **Results viewer**: Grid view (thumbnails + checkboxes), List view (multi-row dataframe selection), status filter, URL search, row-click detail panel
- **Dashboard re-run**: Select rows → "Re-run selected" queues only those URLs; "Re-capture all" queues all URLs. Restores collectors, extraction rules, and fast mode from history entry.
- **Active run persistence**: Module-level `_ACTIVE_RUNNERS` registry + disk manifest `.active_run.json` survives Streamlit reruns

### Dependencies
- **Streamlit** ≥1.42 — `st.navigation`, `st.Page`, `st.segmented_control`, `st.dataframe(on_select)`, `st.column_config.LinkColumn`
- **SeleniumBase** — `SB(uc=True, test=True, headless=False)`, CDP via `sb.cdp.evaluate()`
- **Pandas** — `DataFrame` display, CSV export
- **img2pdf** — PNG-to-PDF conversion with DPI detection (replaces CDP `printToPDF`)
- **Pillow** — Image dimension reading for img2pdf
- **curl_cffi** — FastRunner: Chrome TLS impersonation for concurrent SEO crawling
- **PyYAML** — config.yaml load/save (in SeleniumBase dep chain)

### Development Workflow
- **Launch**: `launch.bat` — auto-installs uv if missing, runs `uv sync && uv run streamlit run app.py`
- **Lint**: `uv run ruff check`
- **Typecheck**: `uv run pyright` (1 pre-existing error: `st.components` attribute)
- **Tests**: `uv run pytest tests/` — 124 tests (analysis, extraction, importers, runners, scrapy)
- **Commit**: Uses git, pushes to `origin/main`

## Current State

### Completed
- Sidebar navigation (`st.navigation` with Capture / Tools / Library sections)
- Unified Crawl (`UnifiedRunner` — multiple collectors in one browser session)
- Fast crawl (`FastRunner` — curl_cffi TLS impersonation, 8 concurrent, Turnstile retry)
- Network idle scroll (waits for images + fetch/XHR instead of fixed delay)
- Smooth scroll (down + smooth up, not instant jump to top)
- Dashboard with run management (browse, search, filter by kind, project filter)
- Grid view (thumbnail gallery with checkboxes) and list view (multi-row dataframe selection)
- Re-run selected URLs and re-capture all from dashboard
- Restore collectors, extraction rules, fast mode on re-run from history
- img2pdf PNG→PDF with DPI detection (optional, checkbox in capture form)
- Config-driven scroll/timing (network idle with 5s timeout, 100ms poll)
- Extraction rules editor (CSS selectors, regex, save/load/delete rule sets)
- Import URLs (manual, sitemap URL, sitemap XML, CSV, WP XML)
- SEO Analysis (post-crawl health check with PDF report)
- `launch.bat` one-click launcher (auto-installs uv)
- Project system — create/edit/delete projects, add/remove runs, filter dashboard by project
- Callback-based progress — all runners support progress_callback, progress.py uses callback registry
- 124 tests passing

### Phase 2 — Crawl4AI Screaming Frog-like Crawl
Planned enhancements to the Crawl4AIRunner to match Screaming Frog SEO Spider capabilities.

#### Step 1: Core Crawl Configuration
- **Crawl depth control**: Add `max_depth` parameter (0 = initial URLs only, 1 = one hop, etc.)
- **URL filtering**: Add include/exclude regex patterns (`include_patterns`, `exclude_patterns`)
- **Parameter handling**: Option to strip/ignore/sort URL query parameters for dedup
- **Redirect control**: Configurable redirect following with chain tracking
- **Robots.txt respect**: Optional robots.txt parsing and adherence
- **Rate limiting**: Per-domain rate limits with burst control

Files: `runners.py` (Crawl4AIRunner.__init__, _crawl4ai_config, _crawl), `config.yaml` (crawl4ai section)

#### Step 2: Enhanced Data Extraction
- **Custom CSS/XPath field extraction**: Allow user-defined selectors in crawl config
- **Element counting**: Count elements matching a selector per page
- **Element existence**: Boolean check if a selector matches any element
- **Attribute extraction**: Extract specific attributes from matched elements
- **Text extraction**: Extract innerText from matched elements
- **Regex extraction**: Apply regex to page text for pattern matching
- **Custom field storage**: Store custom fields alongside standard SEO data in results

Files: `runners.py` (Crawl4AIRunner._transform_result), `extraction.py`, `config.yaml`

#### Step 3: Link and Redirect Analysis
- **Link detail tracking**: Per-link data (anchor text, href, rel attributes, position)
- **Redirect chain recording**: Full redirect URL chain + final status code
- **Broken link detection**: 4xx/5xx error identification with URL context
- **Canonical chain analysis**: Follow and report canonical redirect paths
- **Hreflang validation**: Verify valid language codes, x-default presence, consistency
- **Inlink count per page**: Total internal links pointing to each URL

Files: `runners.py`, `analysis.py`

#### Step 4: On-Page SEO Auditing
- **Page size tracking**: Download size for each URL
- **Image detail extraction**: Dimensions, file size, format, alt text
- **Content type detection**: text/html, application/pdf, etc.
- **Response time capture**: Server response time per URL
- **Structured data validation**: Parse and validate JSON-LD schemas
- **Boilerplate/content ratio**: Detect thin content vs. boilerplate

Files: `runners.py`, `analysis.py`

#### Step 5: Export and Reporting
- **Excel export**: Export results as .xlsx with multiple sheets (SEO data, custom fields, issues)
- **JSON export**: Raw result export in JSON format
- **Issue summary report**: Generate crawl-wide issue summary with counts
- **Crawl statistics**: URL count by status code, content type, depth, etc.
- **Export UI**: Download buttons for each format in results view

Files: `components/results_viewer.py`, `pages/capture.py`, `pages/seo_analysis.py`

#### Step 6: UI Configuration
- **Crawl config panel**: Expandable config section in capture page for Crawl4AI mode
  - Depth slider
  - Include/exclude pattern inputs
  - Custom field selector (from Rule Sets)
  - Redirect follow/depth settings
- **Real-time crawl stats**: Live statistics bar during crawl (URLs crawled, errors, rate)
  - Already have callback-based progress — extend to show detailed stats
- **Crawl visualization**: Generate site tree / depth visualization post-crawl
  - Use Streamlit's tree or graph elements
  - Show URL distribution by depth, status, content type

Files: `pages/capture.py`, `pages/seo_analysis.py`, `components/progress.py`

## Key Decisions
- **No cloud deployment** — local-only desktop app, no CI/CD
- **No Playwright** — SeleniumBase with CDP handles all browser automation
- **No httpx** — `requests` available via SeleniumBase dep chain; `curl_cffi` for FastRunner
- **CSS selectors** for custom extraction (no XPath) — JS-based via CDP
- **No external database** — flat JSON for history, JSON files for extraction rulesets
- **img2pdf over CDP printToPDF** — CDP version lost page dimensions; img2pdf is reliable and DPI-aware
- **Single browser session per run** — `UnifiedRunner` reuses one SB instance for screenshots + extraction
- **Network idle over fixed delay** — JS monkey-patch tracks pending fetch/XHR + image load state; faster on static pages, safer on lazy-load sites

## Agents

Three specialized subagents available in `.opencode/agents/`:

| Agent | Purpose |
|-------|---------|
| `seleniumbase-cdp` | SeleniumBase CDP browser automation expert. Use for all browser interaction, CDP evaluation, page capture, overlay hiding, bot bypass. |
| `streamlit-ui` | Streamlit UI expert. Use for tabs, forms, session state, progress indicators, data tables, download buttons, any `st.*` widget. |
| `api-writer` | REST/GraphQL API writer for external apps. Use for FastAPI/Flask routes, Pydantic models, auth, database schemas. |

All agents use Context7 MCP for up-to-date library documentation.
