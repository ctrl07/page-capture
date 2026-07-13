"""Quick manual test for FastRunner with real URLs."""
from __future__ import annotations
import sys
from pathlib import Path
from runners import FastRunner

urls = [
    "https://www.competitionbmw.com/",
    "https://www.competitionbmw.com/how-to-solve-bmw-sensor-problems/",
    "https://www.competitionbmw.com/is-your-bmw-engine-sputtering/",
    "https://www.competitionbmw.com/why-is-your-bmw-car-not-starting-up/",
    "https://www.competitionbmw.com/how-to-check-mileage-for-a-used-bmw/",
]
runtime_cfg = {
    "viewport": {"width": 1920, "height": 1080},
    "timing": {
        "scroll_interval_ms": 100,
        "stabilization_ms": 800,
        "inter_page_delay_min": 0.3,
        "inter_page_delay_max": 0.5,
    },
    "hide": {},
    "hide_visibility": {},
}
output_dir = Path("S:/capture/page-capture/test_scrapy_output")
output_dir.mkdir(parents=True, exist_ok=True)
runner = FastRunner(urls, runtime_cfg, output_dir)
runner.run()

seo = runner.results.get("seo", [])
print(f"\n=== RESULT: {len(seo)} items ===")
for item in seo:
    status = item.get("status", "?")
    url = item.get("url", "?")
    title = item.get("title", "")[:60]
    code = item.get("status_code", "?")
    wc = item.get("word_count", 0)
    print(f"  {status} | {code} | {url}")
    print(f"    title={title}  words={wc}  h1={item.get('h1','')[:40]}")
