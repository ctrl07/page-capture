# Page Capture

Desktop app for website migration audits — screenshots, SEO extraction, blog comparison, and custom data extraction. Runs SeleniumBase + CDP for bot‑bypass browser automation.

## Features

- **Unified Crawl** — screenshots, SEO, and custom extraction in one browser session
- **Fast Crawl** — SEO‑only via curl_cffi (8 concurrent, Turnstile bypass)
- **Crawl4AI Deep Crawl** — follow links N hops deep, respect robots.txt, rate limits, filter by URL pattern. Exports Excel / JSON / CSV
- **Blog Audit** — compare source vs target blog posts field‑by‑field (title, date, author, categories, content, images). Pick a platform‑specific ruleset or use the generic one.
- **Screenshots** — full‑page PNG with optional PDF via img2pdf
- **Custom Rules** — CSS selector extraction with save / load / delete rule sets
- **Import URLs** — paste, sitemap, CSV, WordPress XML
- **Dashboard** — browse runs, grid/list views, re‑run selected URLs, re‑capture all
- **SEO Analysis** — post‑crawl health score with PDF report
- **Projects** — group runs into named projects, filter the dashboard by project
- **Network Idle Scroll** — waits for images + fetch/XHR instead of a fixed delay

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (auto‑installed by `launch.bat`)

### Run

```bash
# Windows one‑click
launch.bat

# Or manually
uv sync
uv run streamlit run app.py
```

Open **http://localhost:8501**.

## Which Mode Should I Use?

| Mode | Best For | Screenshots | JS Rendering | Speed |
|------|----------|-------------|--------------|-------|
| **Normal (Unified)** | Full audits + screenshots | ✅ | ✅ SeleniumBase | Medium |
| **Fast (curl_cffi)** | Large SEO‑only scans | ❌ | ❌ | ~8× faster |
| **Crawl4AI** | Deep site crawls, structured data | ❌ | ✅ Playwright | Configurable (slider + presets) |
| **Blog Audit** | Migration content comparison | ❌ | ✅ SeleniumBase | Per‑pair |

## Quick Workflows

### Run a Unified Crawl
1. Go to **Capture** > paste / import URLs
2. Turn on **SEO data** (on by default), toggle **Screenshots** and **Custom Rules** as needed
3. Pick **Normal** mode, hit **Start Capture**
4. When done — download Screenshots ZIP, SEO CSV, or Extraction CSV

### Run a Fast SEO Scan
1. **Capture** > import URLs
2. Switch crawl mode to **Fast**
3. Click **Start Capture** — curl_cffi handles the rest at ~8× speed

### Run a Crawl4AI Deep Crawl
1. **Capture** > import URLs
2. Switch to **Crawl4AI** mode
3. Pick a preset:
   - **Just my URLs** — scan only what you entered
   - **Crawl entire site** — follow links 3 levels deep
   - **Blogs & articles** — only URLs containing `/blog/`, `/news/`
   - **Products & shop** — only URLs containing `/product/`, `/item/`
4. Tweak depth, page limit, or domain filters if needed
5. Results export as **CSV + Excel + JSON** automatically

### Run a Blog Audit
1. Go to the **Blog Audit** page (under Tools)
2. Paste source URLs (old site) and target URLs (new site), one per line
3. Pick a **Ruleset** matching your platform (WordPress, Wix, DealerOn, or Generic)
4. Click **Start Audit**
5. Review the per‑post comparison — scores, field diffs, issues (missing images, unicode problems, unlocalized assets)
6. Download the full report as **CSV** or **JSON**

### Create Custom Extraction Rules
1. **Rule Sets** page > add rows with a field name + CSS selector + type
2. Choose from: **text**, **attribute**, **html**, **count**, **exists**, **meta**
3. Save the rule set for re‑use
4. On the Capture page, turn on **Custom Rules** and select your saved rule set

### Manage Projects & Dashboard
1. **Projects** page — create a project, give it a name
2. From the **Dashboard**, open a run detail drawer and **Add to project**
3. Filter the dashboard by project to see only relevant runs
4. Re‑run selected URLs or re‑capture everything with one click

## Project Structure

```
page-capture/
├── app.py              # Router — wires pages into st.navigation
├── state.py            # Session state + active‑run disk manifest
├── project.py          # Create / edit / delete projects
├── runners.py          # All runners: Unified, Fast, Crawl4AI, BlogAudit, etc.
├── page_capture.py     # PageCapture class (SeleniumBase CDP wrapper)
├── extraction.py       # CSS selector rule engine
├── importers.py        # URL import (sitemap, CSV, WP XML)
├── analysis.py         # SEO analysis engine + PDF report
├── config.yaml         # Viewport, timing, overlay‑hide selectors
├── app_pages/          # Streamlit page modules
│   ├── capture.py      # New Capture — import, configure, run, results
│   ├── dashboard.py    # Run management, re‑run, project filter
│   ├── rule_sets.py    # Extraction rule editor
│   ├── seo_analysis.py # Post‑crawl SEO health check
│   ├── blog_audit.py   # Source‑vs‑target blog comparison
│   ├── projects.py     # Project management
│   └── settings.py     # Config editor
├── components/         # Reusable Streamlit components
│   ├── progress.py     # Callback‑based progress bar
│   └── results_viewer.py # Grid / list / unified results display
├── rulesets/           # Built‑in extraction rule sets
│   ├── standard_seo.json
│   ├── generic_blog.json
│   ├── dealeron_blog.json
│   ├── wix_blog.json
│   └── wordpress_blog.json
├── launch.bat          # One‑click launcher (Windows)
├── pyproject.toml      # uv dependency manifest
├── Makefile            # Dev commands
└── tests/              # 124+ pytest tests
```

## Tech Stack

- **Streamlit** — UI framework
- **SeleniumBase** — browser automation with CDP + bot bypass
- **Crawl4AI / Playwright** — async deep crawling with structured extraction
- **curl_cffi** — concurrent SEO crawling with Chrome TLS impersonation
- **Pandas** — data display, CSV / Excel export
- **img2pdf** — PNG‑to‑PDF conversion with DPI detection
- **Pillow** — image processing
- **PyYAML** — config.yaml load / save

## Development

```bash
make dev        # install deps + run app
make lint       # ruff check
make typecheck  # pyright
make test       # pytest (124+ tests)
make format     # auto‑format
```

## License

Internal tool — not for distribution.
