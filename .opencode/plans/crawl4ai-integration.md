# Crawl4AI Integration Plan

## Overview
Replace FastRunner (SeleniumBase + curl_cffi) with **Crawl4AI** for the "Fast SEO" mode. Crawl4AI provides:
- Single async library (no browser → HTTP handoff)
- Built-in JS rendering via Playwright
- Clean structured output (title, meta, headings, links, schema, word count, etc.)
- Async concurrency with rate limiting
- CAPTCHA handling

---

## Current FastRunner Flow
```
Browser (once) → Export cookies → curl_cffi (8 threads) → lxml/XPath → SEO dict
```

## New Crawl4AI Flow
```
AsyncWebCrawler.arun_many(urls) → Clean structured output (title, meta, headings, links, schema, word count, etc.)
```

---

## Integration Points

### 1. New Runner: `Crawl4AIRunner` in `runners.py`
```python
class Crawl4AIRunner:
    """Fast SEO crawl using Crawl4AI (async Playwright + structured output)."""
    
    def __init__(self, urls, runtime_cfg, output_dir, seo_fields=None):
        self.urls = urls
        self.runtime_cfg = runtime_cfg
        self.output_dir = output_dir
        self.seo_fields = seo_fields  # for future filtering
        self.results = {"seo": []}
        self.cancelled = False
        self._thread = None
        self.status = "queued"
        self.progress_total = len(urls)
        self.progress_done = 0
    
    def run(self):
        # async with AsyncWebCrawler(...) as crawler:
        #     results = await crawler.arun_many(
        #         self.urls,
        #         max_concurrent=8,
        #         rate_limit=(10, 1),  # 10 req/sec per domain
        #         headless=True,
        #     )
        #     transform CrawlResult → existing SEO dict format
        #     save CSV + history
```

### 2. Output Mapping (CrawlResult → Existing SEO Format)
| Existing Field | Crawl4AI Source |
|---|---|
| `title` | `result.metadata.title` |
| `meta_description` | `result.metadata.description` |
| `canonical` | `result.metadata.canonical` |
| `robots_meta` | `result.metadata.robots` |
| `h1` | `result.metadata.h1` |
| `h2s` | `result.metadata.h2` (pipe-separated) |
| `h3s` | `result.metadata.h3` |
| `og_title` | `result.metadata.og_title` |
| `og_description` | `result.metadata.og_description` |
| `og_image` | `result.metadata.og_image` |
| `schema_types` | `result.metadata.schema` (pipe-separated) |
| `word_count` | `result.metadata.word_count` |
| `internal_links` | `len(result.metadata.internal_links)` |
| `external_links` | `len(result.metadata.external_links)` |
| `images_missing_alt` | `result.metadata.images_missing_alt` |

### 3. Config (`config.yaml`)
```yaml
crawl4ai:
  concurrency: 8
  rate_limit: 10  # requests/second per domain
  timeout: 30
  headless: true
  respect_robots_txt: false
```

### 4. Files to Modify
| File | Change |
|---|---|
| `pyproject.toml` | Add `crawl4ai>=0.6.0` |
| `runners.py` | Add `Crawl4AIRunner` class, deprecate `FastRunner` |
| `pages/capture.py` | Import `Crawl4AIRunner`, use in fast_mode branch |
| `config.yaml` | Add `crawl4ai` section |
| `launch.bat` | Add `playwright install chromium` |

---

## Tradeoff Questions

| Decision | Options | Recommendation |
|---|---|---|
| **Keep FastRunner as fallback?** | Yes / No | Keep for 1 release, then remove |
| **SEO field selection** | Filter output / Pass to crawler | Filter output (crawl4ai returns all) |
| **Rate limiting** | Crawl4AI built-in / Manual | Use built-in `rate_limit` param |
| **Proxy support** | Later / Now | Later (add to config if needed) |

---

## Testing Checklist
- [ ] Fast mode crawl completes, shows SEO results in UI
- [ ] SEO CSV download works with all fields
- [ ] Dashboard history shows run (`kind: "crawl4ai_seo"`)
- [ ] SEO Analysis page loads results
- [ ] Re-run from dashboard works
- [ ] Cancel button works mid-crawl
- [ ] Progress updates during crawl
- [ ] Error handling (blocked, timeout, network error)

---

## Rollback Plan
Keep `FastRunner` renamed to `FastRunnerLegacy` in `runners.py` for 1 release. If issues, toggle back via config flag.

---

## Estimated Effort
- **Phase 1-2** (runner + mapping): ~2-3 hrs
- **Phase 3** (config): ~30 min
- **Phase 4** (capture page): ~30 min
- **Testing**: ~1 hr
- **Total**: ~4-5 hrs

---

**Ready to proceed?** Any preferences on the tradeoff questions above?