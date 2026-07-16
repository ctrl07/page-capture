# Page Capture — Project Learnings

## Project Overview

**Page Capture** is a desktop Streamlit application for website migration audits. It captures full-page screenshots, extracts SEO data, runs custom CSS selector extraction rules, and provides post-crawl SEO health analysis with PDF reports. All browser automation uses **SeleniumBase with CDP** (Chrome DevTools Protocol) in undetected mode for bot bypass.

**Location:** `S:\capture\page-capture\`

---

## Architecture

### Entry Point & Navigation
- **`app.py`** (53 lines): Slim router using `st.navigation` with sidebar position
- Pages organized into 3 sections:
  - **Capture**: 🚀 Capture (default), 📊 Dashboard
  - **Tools**: 📋 Rule Sets, 📈 SEO Analysis
  - **Library**: ⚙️ Settings
- `main()` called at module level (not in `if __name__ == "__main__"`)

### Session State & Persistence
- **`state.py`**: Module-level `_ACTIVE_RUNNERS` registry + disk manifest (`.active_run.json`) survives Streamlit reruns AND process restarts
- Session state keys initialized in `init_session_state()`:
  - `capture_urls` — URL queue shared between Dashboard → Capture
  - `extraction_rules` — Custom CSS rules from Rule Sets page
  - `unified_runner`, `unified_running` — Active run tracking

### Configuration
- **`config.yaml`**: Viewport (1920×1080), timing (scroll, delays, network idle), overlay-hide selectors (100+ selectors for chat widgets, cookies, modals, etc.)
- Loaded via `page_capture.load_config()` with defaults fallback

---

## Core Components

### 1. Browser Automation — `page_capture.py` (PageCapture class)

**SeleniumBase CDP Wrapper** with these key methods:
- `open(url)` — Navigate + solve Turnstile (retries 5×)
- `scroll()` — Smooth scroll down + up with **network idle detection**
- `hide_overlays()` — Inject CSS to hide overlays + remove large fixed/absolute elements
- `capture_png(path)` — Full-page PNG via CDP viewport resize + `capture_screenshot`
- `extract_data()` — Basic page title + H1
- `extract_session()` — Export cookies + UA for FastRunner handoff

**Network Idle Scroll** (config-driven):
- Monkey-patches `fetch` + `XMLHttpRequest` to track pending requests
- Waits for all images loaded + zero pending network requests
- Config: `scroll_wait_for_idle` (bool), `scroll_idle_timeout_ms` (5000), `scroll_idle_poll_ms` (100)

**PDF Generation**: Uses `img2pdf` (not CDP `printToPDF`) — preserves exact dimensions, DPI-aware (150 DPI default)

---

### 2. Runner Classes — `runners.py`

| Class | Purpose | Key Features |
|-------|---------|--------------|
| **CaptureRunner** | Screenshots only (+ optional PDF) | Single browser session, PNG + optional PDF |
| **ExtractionRunner** | Custom CSS selector extraction | Uses `extraction.extract_from_page()` |
| **UnifiedRunner** | Multiple collectors in ONE browser session | Screenshot + SEO + Extraction concurrently; progress tracking per URL×collector |
| **FastRunner** | SEO-only via `curl_cffi` (8 concurrent) | Opens browser once to solve Turnstile, exports cookies, then crawls via TLS-impersonated requests; retries blocked URLs with fresh session |

**Progress Tracking** (UnifiedRunner/FastRunner):
- `progress_total` = URLs × collectors
- `progress_done` increments per collector result
- `status` string updated during run

**History** (`.run_history.json`, max 50 entries):
- UnifiedRunner saves to `results_by_collector` (dict: collector → list[results])
- Other runners save to flat `results` list
- `get_results()` helper normalizes both formats

---

### 3. Custom Extraction — `extraction.py`

**Rule Engine** (CSS selectors via CDP):
- Types: `text`, `attribute`, `html`, `count`, `exists`, `meta`
- Supports `multiple` (array), `regex` post-processing
- JS built via `build_extraction_js()` → injected via `sb.cdp.evaluate()`

**SEO Fields** (configurable):
- `STANDARD_SEO_FIELDS` (15 fields): title, meta, headings, OG, schema, word count, links, images
- `EXTENDED_SEO_FIELDS` (20+ fields): Twitter, hreflang, viewport, charset, JSON-LD full, etc.
- `build_seo_js(fields)` generates single IIFE with helpers
- `parse_seo_fields()` handles derived fields (lengths)

**Rule Sets**: Saved as JSON in `rulesets/` — save/load/delete via UI

---

### 4. URL Importers — `importers.py`

- `parse_urls_text()` — Manual paste (one per line, comma-separated)
- `import_from_sitemap_url()` / `import_from_sitemap_xml()` — XML sitemaps (handles namespaces)
- `import_from_csv_file()` — First column = URL, second = optional extra
- `import_from_wp_xml()` — WordPress export XML (extracts title, URL, date, H1, categories, tags)

---

### 5. SEO Analysis — `analysis.py`

**Issue Detection** (14 categories, 50+ checks):
- Titles, Meta, Headings, Indexability, Canonical, Open Graph, Twitter Cards, Images, Schema, Technical, URLs, Content, Hreflang, Links

**Health Score** (Ahrefs-style 0–100):
- Error = 1.0 pt/page, Warning = 0.5, Opportunity = 0.2
- Normalized against `total_pages × 10` upper bound

**PDF Report** (fpdf2):
- Cover page with health score badge (green/yellow/red)
- Issues by category with severity badges
- Distribution charts (title length, meta desc, word count) as text bars

---

### 6. Streamlit Pages & Components

**`pages/capture.py`** — Main workflow:
1. URL import (paste/sitemap/CSV/WP XML) → queue
2. Collector checkboxes (Screenshot, SEO, Extraction)
3. Settings (viewport, delay, output folder, fast mode, PDF)
4. Run button → spawns background thread → live progress → results with downloads

**`pages/dashboard.py`** — Run management:
- Filter/search runs by kind/URL
- Grid view (thumbnails + checkboxes) + List view (multi-row dataframe)
- Actions: Re-run selected URLs, Re-capture all, CSV/ZIP download, Delete run
- Restores collectors, extraction rules, fast mode on re-run

**`pages/rule_sets.py`** — Extraction rule editor (standalone)

**`pages/seo_analysis.py`** — Post-crawl analysis:
- Health score + gauge
- Issues by category (expandable with fix guidance + URL list)
- Visualizations (bar charts via `st.bar_chart`)
- Duplicate title/meta detection
- PDF report download

**`pages/settings.py`** — Config editor (viewport, timing) + output folder cleanup

**Components**:
- `components/progress.py` — `run_with_progress()` polls thread every 300ms, rolling ETA
- `components/results_viewer.py` — `render_results()`, `render_unified_results()`, `render_results_grid()`, `render_results_list()`

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| **SeleniumBase + CDP** (not Playwright) | Undetected mode (`uc=True`) handles bot detection; CDP gives fine-grained control |
| **img2pdf > CDP printToPDF** | CDP lost page dimensions; img2pdf is reliable + DPI-aware |
| **Network idle scroll** | Fixed delays waste time on static pages; network idle adapts to lazy-load |
| **Single browser session (UnifiedRunner)** | Faster than re-opening browser per collector; reuses solved Turnstile session |
| **FastRunner (curl_cffi)** | 8× concurrency for SEO-only crawls; TLS fingerprint = Chrome |
| **Flat JSON history** | No external DB needed; portable, inspectable |
| **CSS selectors only** | Simpler than XPath; works natively in CDP JS context |
| **Streamlit ≥1.42** | `st.navigation`, `st.segmented_control`, `st.dataframe(on_select)`, `LinkColumn` |

---

## Development Workflow

| Task | Command |
|------|---------|
| **Launch** | `launch.bat` (auto-installs uv, syncs deps, runs Streamlit) |
| **Lint** | `uv run ruff check` |
| **Typecheck** | `uv run pyright` (1 known error: `st.components` attr) |
| **Tests** | `uv run pytest tests/` (124 tests: analysis, extraction, importers, runners, scrapy) |
| **CLI** | `uv run run_capture.py --kind screenshot/seo [urls...]` |

---

## Project Structure

```
S:\capture\page-capture\
├── app.py                    # Router (st.navigation)
├── state.py                  # Session state + active run persistence
├── config.yaml               # Viewport, timing, hide selectors
├── page_capture.py           # PageCapture (SeleniumBase CDP wrapper)
├── runners.py                # 4 Runner classes + history helpers
├── extraction.py             # CSS rule engine + SEO fields + rule editor UI
├── importers.py              # URL import (sitemap, CSV, WP XML)
├── analysis.py               # SEO analysis + health score + PDF report
├── run_capture.py            # CLI entry point
├── launch.bat                # One-click launcher
├── pyproject.toml            # uv dependencies
├── uv.lock                   # Lockfile
├── pages/
│   ├── capture.py            # New run: import → config → run → results
│   ├── dashboard.py          # Run history + re-run/re-capture
│   ├── rule_sets.py          # Extraction rule editor
│   ├── seo_analysis.py       # Post-crawl SEO health + PDF
│   └── settings.py           # Config editor + folder cleanup
├── components/
│   ├── progress.py           # run_with_progress() polling
│   └── results_viewer.py     # Grid/List views, downloads
├── rulesets/                 # Saved extraction rules (JSON)
└── tests/                    # 124 pytest tests
```

---

## Pending / Future Work (from AGENTS.md)

1. **Dark mode toggle** — Not implemented
2. **Project system** — Scope TBD (multi-site management?)
3. **Callback-based progress** — Replace polling with event-driven updates (planned)

---

## Notable Code Patterns

**Background thread + Streamlit rerun loop**:
```python
# In runner.run() — runs in background thread
# In progress.py — polls thread.is_alive() every 300ms
# On completion: st.session_state.unified_running = False; st.rerun()
```

**Module-level runner registry** (`state.py`):
```python
_ACTIVE_RUNNERS: dict[str, dict] = {}  # Survives reruns
_MANIFEST = HERE / ".active_run.json"  # Survives process restart
```

**Network idle detection via CDP** (`page_capture.py`):
```javascript
// Monkey-patch fetch + XHR
window.__pendingFetch++; 
window.__pendingXHR++;
// Poll until both zero + all images complete
```

**Unified results format** (`runners.py::get_results()`):
```python
# UnifiedRunner: {"screenshot": [...], "seo": [...], "extraction": [...]}
# Others: {"_flat": [...]}  (wrapped for consistent API)
```

**Results viewer dual mode** (`components/results_viewer.py`):
- Grid: `st.image` + `st.checkbox` (screenshots)
- List: `st.dataframe(selection_mode="multi-row")` (all types)

---

## Dependencies (from pyproject.toml)

| Package | Purpose |
|---------|---------|
| `streamlit>=1.42` | UI framework |
| `seleniumbase>=4.36.0` | Browser automation (uc mode + CDP) |
| `pyyaml>=6.0` | Config YAML |
| `pandas>=2.2` | DataFrames for results tables |
| `img2pdf>=0.5` | PNG → PDF conversion |
| `Pillow>=10.0` | Image DPI reading for img2pdf |
| `fpdf2>=2.8.0` | PDF report generation |
| `curl_cffi>=0.15` | FastRunner TLS impersonation |
| `lxml>=5.0` | HTML parsing for FastRunner |

Dev: `pytest`, `ruff`, `pyright`