# Page Capture

Desktop app for website migration audits — screenshots, SEO extraction, and custom data extraction using SeleniumBase with CDP-based bot bypass.

## Features

- **Unified Crawl** — screenshots, SEO, and custom extraction in a single browser session
- **Fast Crawl** — SEO extraction via curl_cffi (8 concurrent) after solving Turnstile once
- **Screenshots** — full-page PNG with optional PDF export via img2pdf
- **SEO Extraction** — title, meta description, headings, Open Graph tags, schema markup, word count, link counts, missing alt text
- **Custom Rules** — CSS selector-based data extraction with save/load rule sets
- **Import URLs** — from sitemap, CSV, WordPress XML export
- **Dashboard** — browse runs, grid/list views, re-run selected URLs, re-capture all
- **SEO Analysis** — post-crawl health check with PDF report
- **Network Idle Scroll** — waits for images + fetch/XHR instead of fixed delay

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager (auto-installed by `launch.bat`)

### Run

```bash
# One-click launcher (Windows)
launch.bat

# Or manually
uv sync
uv run streamlit run app.py
```

App opens at **http://localhost:8501**.

## Development

```bash
make dev        # install deps + run app
make lint       # ruff check
make typecheck  # pyright
make test       # pytest (124 tests)
make format     # auto-format
```

## Project Structure

```
page-capture/
├── app.py              # Slim router (53 lines)
├── state.py            # Session state + active-run persistence
├── runners.py          # FastRunner, UnifiedRunner, CaptureRunner, ExtractionRunner
├── page_capture.py     # PageCapture class (SeleniumBase CDP wrapper)
├── extraction.py       # CSS selector extraction engine
├── importers.py        # URL import (sitemap, CSV, WP XML)
├── analysis.py         # SEO analysis engine + PDF report
├── config.yaml         # Viewport, timing, overlay-hide selectors
├── pages/              # Streamlit page modules
│   ├── capture.py      # Import, configure, run, monitor, results
│   ├── dashboard.py    # Run management, grid/list views, re-run/re-capture
│   ├── rule_sets.py    # Extraction rule editor
│   ├── seo_analysis.py # Post-crawl SEO health check
│   └── settings.py     # Config editor
├── components/         # Reusable Streamlit components
│   ├── progress.py     # Progress bar with rolling ETA
│   └── results_viewer.py # Grid/list views, unified results
├── launch.bat          # One-click launcher
├── pyproject.toml      # Dependencies + dev tools
├── Makefile            # Dev commands
└── tests/              # 124 pytest tests
```

## Tech Stack

- **Streamlit** — UI framework
- **SeleniumBase** — browser automation with CDP + bot bypass
- **Pandas** — data display and CSV handling
- **img2pdf** — PNG-to-PDF conversion
- **Pillow** — image processing
- **curl_cffi** — concurrent SEO crawling with Chrome TLS impersonation

## License

Internal tool — not for distribution.
