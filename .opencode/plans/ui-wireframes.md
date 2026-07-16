# Page Capture — UI Wireframes

## Overview

5 pages across 3 navigation sections. All pages use Streamlit's native components with `st.navigation` sidebar.

---

## 1. 🚀 Capture Page (`pages/capture.py`)

**Purpose**: Main workflow — import URLs, configure collectors, run crawl, view results

### States
| State | Trigger | UI |
|-------|---------|-----|
| **Setup** | Default / "Capture Again" | Full configuration form |
| **Running** | "Start Capture" clicked | Live progress (full-width) |
| **Complete** | Run finishes | Results + downloads + "Capture Again" |

---

### State 1: Setup Form

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ New Capture                                                          [←Sidebar]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─ URL Source ─────────────────────────────────────────────────────────┐  │
│  │  (●) Paste URLs    (○) Sitemap    (○) CSV upload    (○) WordPress XML │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │  [Paste mode shown]                                                 │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │ https://example.com                                            │  │  │
│  │  │ https://example.com/about                                      │  │  │
│  │  │ https://example.com/contact                                    │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  │  [Sitemap mode: URL input + [Fetch] button]                         │  │
│  │  [CSV/WP XML mode: File uploader]                                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  [Add N URLs to queue]  ← appears after import                            │
│                                                                             │
│  ✅ **N URL(s) in queue**                    [Clear queue]                │
│  ▼ View URLs (expander: first 100, "+ N more")                            │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ┌─ Collectors ──────────────────┐  ┌─ Settings ────────────────────────┐  │
│  │  ☑ Screenshots   ☑ SEO data   │  │  Width:  [1920] ▼  Height: [1080] ▼│  │
│  │  ☐ Custom rules               │  │  Delay:  [0.8] s     Folder: [run_...]│  │
│  │                               │  │                                    │  │
│  │  [Configure SEO fields ▼]     │  │  ☐ Fast mode (curl_cffi)           │  │
│  │  ⚠ No extraction rules loaded │  │     ℹ️ Disables screenshots        │  │
│  │                               │  │                                    │  │
│  │                               │  │  ☐ Generate PDFs                   │  │
│  │                               │  │     ⚠ Requires Screenshots         │  │
│  └───────────────────────────────┘  └────────────────────────────────────┘  │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  [Start Capture]  ← PRIMARY, full-width, disabled until valid              │
│       ↑                                                                      │
│       "To start: add URLs, select a collector, load extraction rules"      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Interactions**:
- Radio tabs for URL source (horizontal)
- "Add to queue" merges & dedupes → updates session state → rerun
- Collectors: 3 checkboxes in row; SEO expander; Extraction shows warning if no rules
- Settings: 2×2 grid (viewport W/H, delay, folder); Fast mode & PDF toggles below
- Start button: validates `urls + collectors + (extraction→rules)`; shows inline hint if invalid

---

### State 2: Running (Full-Width)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ New Capture                                                          [←Sidebar]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ℹ️ Running — **Opening https://example.com/about**                        │
│  ████████████████████░░░░░░░░░░  12/48  |  1m 23s elapsed | ETA ~4m 12s   │
│  [Cancel]                                                                   │
│                                                                             │
│  (Auto-reruns every 300ms via run_with_progress)                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Progress Bar Text**: `{done}/{total} | {elapsed} elapsed{ETA}`  
**Status**: From `runner.status` (e.g., "Opening...", "Scrolling...", "Extracting SEO...")

---

### State 3: Complete

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ New Capture                                                          [←Sidebar]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                           │
│  │  URLs   │ │ Passed  │ │ Failed  │ │Collect. │                           │
│  │   24    │ │   22    │ │    2    │ │    3    │                           │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘                           │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ### Download Results                                                     │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐             │
│  │ Screenshots ZIP │ │    SEO CSV      │ │ Extraction CSV  │             │
│  │   [DOWNLOAD]    │ │   [DOWNLOAD]    │ │   [DOWNLOAD]    │             │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘             │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│  **SEO Analysis**  →  [Open SEO Analysis] (secondary, full-width)        │
│                                                                             │
│  Output saved to: `run_20250716_143022`                                   │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ┌─ Tabs: Screenshots | Quick SEO | Custom Rules | Summary ────────────┐  │
│  │                                                                        │  │
│  │  [Each tab: render_unified_results → render_results]                  │  │
│  │                                                                        │  │
│  │  Sub-tabs: Summary | Details | Preview                                │  │
│  │                                                                        │  │
│  │  Details:  [Filter: All/OK/Failed] [Search URLs...]                  │  │
│  │  ████████████████████████████████████████████████████████████████    │  │
│  │  (st.dataframe with LinkColumn URL, single-row select → detail panel)│  │
│  │                                                                        │  │
│  │  Preview (screenshots): dropdown → full image + PNG/PDF download     │  │
│  │                                                                        │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│  [Capture Again]  ← resets to Setup state                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 📊 Dashboard Page (`pages/dashboard.py`)

**Purpose**: Browse run history, filter, re-run selected URLs, download artifacts

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Dashboard                                                           [←Sidebar]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────┐ ┌────────────┐ ┌──────────┐ ┌────────┐                        │
│  │  Runs   │ │ URLs Done  │ │ Succeeded│ │ Failed │                        │
│  │   12    │ │   1,247    │ │  1,189   │ │   58   │                        │
│  └─────────┘ └────────────┘ └──────────┘ └────────┘                        │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  [Search URLs...]      [Kind ▼: All / unified / screenshot / seo / ...]   │
│                                                                             │
│  Select run: [2025-07-16 14:30:22 — unified — 22/24 OK ▼]                 │
│  2025-07-16 14:30:22 | 24 URLs | 22 OK | 2 failed | `run_20250716_143022`│
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ┌─ Action Bar ─────────────────────────────────────────────────────────┐  │
│  │ [Re-run selected (N)]  [Re-capture all (N)]  [Delete]  [CSV] [ZIP]  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ┌─ Tabs: Screenshots | Quick SEO | Custom Rules ──────────────────────┐  │
│  │                                                                        │  │
│  │  [Tab header: View ▼ Grid/List] [Filter ▼ All/OK/Failed] [Search...] │  │
│  │                                                                        │  │
│  │  ┌─ GRID VIEW (screenshots) ──────────────────────────────────────┐  │  │
│  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │  │  │
│  │  │  │ 🖼️      │  │ 🖼️      │  │ 🖼️      │  │ 🖼️      │           │  │  │
│  │  │  │ example │  │ about   │  │ contact │  │ blog    │           │  │  │
│  │  │  │   OK    │  │   OK    │  │  FAIL   │  │   OK    │           │  │  │
│  │  │  │ ☑ Select│  │ ☑ Select│  │ ☐ Select│  │ ☐ Select│           │  │  │
│  │  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘           │  │  │
│  │  │  (4 per row, checkbox per thumb)                                │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  │  ┌─ LIST VIEW (SEO/Extraction) ───────────────────────────────────┐  │  │
│  │  │ ████████████████████████████████████████████████████████████    │  │  │
│  │  │ (st.dataframe, multi-row select, LinkColumn URL, Status col)   │  │  │
│  │  │ Selected rows → populate action bar "Re-run selected"          │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  │                                                                        │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Flows**:
- **Re-run selected**: Collects URLs from checked rows across collectors → sets `capture_urls` + restores `collectors`, `extraction_rules`, `fast_mode` → switches to Capture page
- **Re-capture all**: Same but all URLs from run
- **Delete**: Confirmation modal → removes from history → rerun
- **CSV/ZIP**: Streams download from filtered results

---

## 3. 📋 Rule Sets Page (`pages/rule_sets.py`)

**Purpose**: Create/edit/save/load/delete CSS extraction rules

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Rule Sets                                                           [←Sidebar]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Define custom CSS selector rules to extract data from pages.              │
│                                                                             │
│  ┌─ Rules Table ────────────────────────────────────────────────────────┐  │
│  │ Field          │ Selector              │ Type       │ Attr  │ Multi  │  │
│  ├────────────────┼───────────────────────┼────────────┼───────┼────────┤  │
│  │ product_title  │ h1.product-title      │ text       │       │ ☐      │ ✕│
│  │ price          │ .price::attr(data-usd)│ attribute  │data-usd│ ☐     │ ✕│
│  │ description    │ .product-desc         │ html       │       │ ☐      │ ✕│
│  │ image_count    │ .gallery img          │ count      │       │        │ ✕│
│  │ has_schema     │ script[type="ld+json"]│ exists     │       │        │ ✕│
│  │                [+ Add Rule]                                          │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ▼ Regex (optional) — expandable per rule                                 │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ Regex — product_title    [________________________]                │   │
│  │ Regex — price            [________________________]                │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ▼ Test Rules (live preview)                                              │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ Test URL: [https://example.com/product]    [Test]  (spinner)       │   │
│  │                                                                    │   │
│  │ product_title: "Awesome Widget"                                    │   │
│  │ price: "29.99"                                                     │   │
│  │ description: "<p>Best widget ever...</p>"                          │   │
│  │ image_count: 12                                                    │   │
│  │ has_schema: true                                                   │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ┌─ Rule Set Management ───────────────────────────────────────────────┐  │
│  │ [Save]  Rule set name: [my-rules________]  [Save]                    │  │
│  │ [Load]  Select: [my-rules ▼]  [Load]                                 │  │
│  │ [Del]   Select: [my-rules ▼]  [Delete]                               │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  (Saved as JSON in `rulesets/`)                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Row Details**:
- Field: text input (required)
- Selector: text input (CSS)
- Type: `st.selectbox` — text/attribute/html/count/exists/meta
- Attr: text input (shows for attribute type)
- Multi: checkbox
- Delete: icon button per row → pops from session_state → rerun

---

## 4. 📈 SEO Analysis Page (`pages/seo_analysis.py`)

**Purpose**: Post-crawl health audit with score, issues, charts, PDF export

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ SEO Analysis                                                          [←Sidebar]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Source: Current run / History: 2025-07-16 14:30:22 — 24 URLs (22 OK)     │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    HEALTH SCORE: 73 / 100                            │  │
│  │  ████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                           │
│  │ Total   │ │ OK      │ │ Errors  │ │Warnings │                           │
│  │   24    │ │   22    │ │    8    │ │   15    │                           │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘                           │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│  ### Issues by Category                                                    │
│                                                                             │
│  ▼ titles — 2 errors, 3 warnings, 0 opportunities                         │
│    🔴 **Missing Title** — 1 URL(s)                                        │
│       Add a unique, descriptive <title> tag (30-60 characters) to every   │
│       page.                                                                │
│       ▼ Show 1 URL(s)  →  https://example.com/broken-page                 │
│    🟡 **Title Too Long** — 2 URL(s)                                       │
│       Keep titles under 60 characters to avoid truncation in search...    │
│       ▼ Show 2 URL(s)  →  https://example.com/very-long-title-page...     │
│    🟡 **Title Too Short** — 1 URL(s)                                      │
│    🔴 **Duplicate Title** — 1 URL(s)                                      │
│                                                                             │
│  ▼ meta — 1 error, 4 warnings, 0 opportunities                            │
│    🟡 **Missing Meta Description** — 3 URL(s)                             │
│    🟡 **Duplicate Meta Description** — 2 URL(s)                           │
│    🔴 **Meta Description Too Long** — 1 URL(s)                            │
│                                                                             │
│  ▼ headings — 0 errors, 2 warnings, 1 opportunity                         │
│    🟡 **Missing H1** — 1 URL(s)                                           │
│    🟡 **Missing H2** — 4 URL(s)                                           │
│    🔵 **Multiple H1** — 1 URL(s)                                          │
│                                                                             │
│  ▼ open_graph — 0 errors, 0 warnings, 3 opportunities                     │
│    🔵 **OG Title Missing** — 5 URL(s)                                     │
│    🔵 **OG Description Missing** — 5 URL(s)                               │
│    🔵 **OG Image Missing** — 5 URL(s)                                     │
│    🔵 **OG Incomplete** — 8 URL(s)                                        │
│    🔵 **OG Mismatch Title** — 2 URL(s)                                    │
│                                                                             │
│  ▼ images — 0 errors, 3 warnings, 1 opportunity                           │
│  ▼ schema — 0 errors, 0 warnings, 4 opportunities                         │
│  ▼ technical — 0 errors, 1 warning, 2 opportunities                       │
│  ▼ urls — 0 errors, 2 warnings, 3 opportunities                           │
│  ▼ links — 0 errors, 0 warnings, 2 opportunities                          │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│  ### Visualisations                                                        │
│                                                                             │
│  ┌─ Title Length ──────────────────┐ ┌─ Meta Desc Length ──────────────┐  │
│  │ ████████████████████ 30-60 (8)   │ │ ██████████████████ 70-155 (9)   │  │
│  │ ████████████ 1-29 (4)            │ │ ██████████ 1-69 (5)             │  │
│  │ ████████ 61-70 (3)               │ │ ████████████████████ 156-160 (4)│  │
│  │ ██████ 70+ (2)                   │ │ ████████ 160+ (3)               │  │
│  │ ████ 0 (1)                       │ │ ██████████ 0 (2)                │  │
│  └──────────────────────────────────┘ └─────────────────────────────────┘  │
│                                                                             │
│  ┌─ Word Count ────────────────────┐ ┌─ URL Depth ─────────────────────┐  │
│  │ ████████████████████████ 200-499│ │ ██████████████████ depth 2 (10) │  │
│  │ ████████████████ 500-999 (6)    │ │ ████████████ depth 3 (7)        │  │
│  │ ██████████ 1000+ (4)            │ │ ██████████ depth 1 (5)          │  │
│  │ ████████ 1-199 (3)              │ │ ████ depth 4 (2)                │  │
│  │ ████ 0 (1)                      │ │ ██ depth 0 (1)                  │  │
│  └──────────────────────────────────┘ └─────────────────────────────────┘  │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│  ### Social Tags Completeness                                              │
│                                                                             │
│  ┌─ Open Graph ─────────────────┐ ┌─ Twitter Cards ──────────────────┐   │
│  │ ██████████████████ Complete(8)│ │ ████████████████████ Complete(6) │   │
│  │ ██████████ Partial (6)        │ │ ████████████ Partial (7)         │   │
│  │ ████████████████████ None (8) │ │ ████████████████████████ None (9)│   │
│  └───────────────────────────────┘ └─────────────────────────────────┘   │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│  ### Duplicate Detection                                                   │
│                                                                             │
│  ⚠️ 3 duplicate title(s) found                                            │
│  ▼ "Home Page" — 3 pages  →  /, /home, /index                             │
│  ▼ "Product Catalog" — 2 pages  →  /products, /shop                       │
│                                                                             │
│  ⚠️ 2 duplicate meta description(s) found                                 │
│  ▼ "Welcome to our site..." — 4 pages                                     │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│  ### Export Report                                                         │
│  [Download PDF Report]  ← PRIMARY, full-width                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Key Features**:
- Health score with color-coded progress bar (green ≥80, yellow ≥50, red <50)
- Expandable category sections, sorted by severity (errors first)
- Each issue: badge + title + fix guidance + expandable URL list (max 20 shown)
- Charts: `st.bar_chart` with pre-bucketed pandas Series
- PDF: fpdf2-generated multi-page report (cover, score, issues, charts)

---

## 5. ⚙️ Settings Page (`pages/settings.py`)

**Purpose**: Edit `config.yaml` + manage output folders

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Settings                                                            [←Sidebar]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ### Configuration                                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Viewport width:       [1920] ▼    Viewport height: [1080] ▼          │  │
│  │ Stabilization (ms):   [800] ▼                                            │  │
│  │ Inter-page delay min: [0.3] s   Inter-page delay max: [0.5] s        │  │
│  │                                                                        │  │
│  │                                    [Save]                              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ### Manage Output Folders                                                 │
│                                                                             │
│  Select folder to clean: [run_20250716_143022 ▼]                          │
│                                                                             │
│  [Delete selected folder]  →  confirmation modal                          │
│                                                                             │
│  ⚠️ Delete `run_20250716_143022`? This cannot be undone.                  │
│  [Yes, delete] [Cancel]                                                   │
│                                                                             │
│  (Folders listed by mtime desc; only those with /data or /photos)         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Reference

### Reusable Components (from `components/`)

| Component | File | Used In |
|-----------|------|---------|
| `run_with_progress(runner, key)` | `progress.py` | Capture (running state) |
| `render_results(results, kind, dir, prefix)` | `results_viewer.py` | Capture (complete), Dashboard |
| `render_unified_results(runner, prefix)` | `results_viewer.py` | Capture (complete) |
| `render_results_grid(results, kind, dir, prefix)` | `results_viewer.py` | Dashboard (screenshots tab) |
| `render_results_list(results, kind, dir, prefix)` | `results_viewer.py` | Dashboard (SEO/extraction tabs) |
| `render_rules_editor(...)` | `extraction.py` | Rule Sets, Capture (SEO expander) |
| `render_seo_fields_selector(prefix)` | `extraction.py` | Capture (SEO config) |

---

## Navigation & State Flow

```
┌─────────────┐     Re-run selected      ┌─────────────┐
│  Dashboard  │ ───────────────────────► │   Capture   │
│  (history)  │  (sets capture_urls,     │  (setup)    │
└─────────────┘   restore_*)             └──────┬──────┘
       ▲                                       │
       │                                       ▼
       │                              ┌─────────────┐
       │   Restore from history       │   Capture   │
       └───────────────────────────── │  (running)  │
                                      └──────┬──────┘
                                             │
                                             ▼
                                      ┌─────────────┐
                                      │  Capture    │
                                      │ (complete)  │
                                      └──────┬──────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
             ┌───────────┐            ┌─────────────┐          ┌────────────┐
             │Rule Sets  │            │SEO Analysis │          │ Settings   │
             │(edit rules)           │(analyze SEO)│          │(config YAML)│
             └───────────┘            └─────────────┘          └────────────┘
```

**Session State Keys**:
- `capture_urls` — URL queue (Dashboard → Capture)
- `extraction_rules` — Rule list (Rule Sets ↔ Capture)
- `unified_runner`, `unified_running` — Active run (Capture)
- `newrun_collectors`, `newrun_output`, `newrun_fast_mode`, `newrun_generate_pdf` — Capture form
- `restore_collectors`, `restore_extraction_rules`, `restore_fast_mode` — Dashboard → Capture handoff

---

## Responsive Notes

- All pages use `layout="wide"` (set in `app.py`)
- Grids: `st.columns([1,1])` for split panels, `st.columns(4)` for metric rows
- Grid view: 4 columns fixed (`cols_per_row = 4`)
- Dataframes: `width="stretch"` for full-width tables
- Download buttons: `width="stretch"` for consistent sizing
- Mobile: Streamlit handles stacking; no custom breakpoints needed