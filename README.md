# Page Capture

Desktop app for website migration audits — screenshots, SEO extraction, and custom data extraction using SeleniumBase with CDP-based bot bypass.

## Features

- **Unified Crawl** — screenshots, SEO, and custom extraction in a single browser session
- **Screenshots** — full-page PNG with optional PDF export
- **SEO Extraction** — title, meta description, headings, Open Graph tags, schema markup, word count, link counts, missing alt text
- **Custom Rules** — CSS selector-based data extraction with save/load rule sets
- **Import URLs** — from sitemap, CSV, WordPress XML export
- **Run History** — browse, re-run, delete past crawls
- **Persistent URL Queue** — sidebar shows loaded URLs across pages

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager

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
make test       # pytest
make format     # auto-format
```

## Project Structure

```
page-capture/
├── app.py              # Streamlit UI, pages, router
├── runners.py          # CaptureRunner, ExtractionRunner, UnifiedRunner
├── page_capture.py     # PageCapture class (SeleniumBase CDP wrapper)
├── extraction.py       # CSS selector extraction engine + rules editor
├── importers.py        # URL import (sitemap, CSV, WP XML)
├── config.yaml         # Viewport, timing, overlay-hide selectors
├── launch.bat          # One-click launcher
├── pyproject.toml      # Dependencies + dev tools
├── Makefile            # Dev commands
└── tests/              # pytest tests
```

## Tech Stack

- **Streamlit** — UI framework
- **SeleniumBase** — browser automation with CDP + bot bypass
- **Pandas** — data display and CSV handling
- **img2pdf** — PNG-to-PDF conversion
- **Pillow** — image processing

## License

Internal tool — not for distribution.
