"""Google Maps business lookup via SeleniumBase CDP."""

from __future__ import annotations

import re
import threading
import time

from seleniumbase import SB


class GMapScraper:
    """Scrape Google Maps for a business location using SeleniumBase CDP."""

    def __init__(self, sb):
        self.sb = sb
        self._opened = False

    def search_business(self, query: str) -> dict | None:
        url = f"https://www.google.com/maps?q={query}"

        if not self._opened:
            self.sb.activate_cdp_mode(url)
            self._opened = True
        else:
            self.sb.cdp.open(url)

        current_url = ""
        coords = None
        for _ in range(30):
            time.sleep(1)
            try:
                current_url = self.sb.cdp.evaluate("window.location.href") or ""
            except Exception:
                current_url = ""
            coords = self._parse_coords(current_url)
            if coords:
                break

        if not coords:
            return None

        lat, lng, zoom = coords
        name = ""
        try:
            name = self.sb.cdp.evaluate("document.title") or ""
        except Exception:
            name = ""

        clean_name = name.replace(" - Google Maps", "").strip() if name else query

        return {
            "query": query,
            "name": clean_name,
            "lat": lat,
            "lng": lng,
            "zoom": zoom,
            "url": current_url,
            "iframe_src": f"https://maps.google.com/maps?q={lat},{lng}&z={int(zoom)}&output=embed",
            "iframe_html": (
                f'<iframe src="https://maps.google.com/maps?q={lat},{lng}'
                f'&z={int(zoom)}&output=embed" width="600" height="450"'
                f' style="border:0;" allowfullscreen="" loading="lazy"'
                f' referrerpolicy="no-referrer-when-downgrade"></iframe>'
            ),
        }

    @staticmethod
    def _parse_coords(url: str) -> tuple | None:
        m = re.search(r"@(-?\d+\.?\d*),(-?\d+\.?\d*),(\d+(?:\.\d+)?)z", url or "")
        if m:
            return (float(m.group(1)), float(m.group(2)), float(m.group(3)))
        return None


class GeoRunner:
    """Run a single Google Maps business lookup in a background thread."""

    def __init__(self, query: str):
        self.query = query
        self.result: dict | None = None
        self.status = "idle"
        self.cancelled = False
        self._thread: threading.Thread | None = None

    def run(self) -> None:
        try:
            self.status = "Starting browser..."
            with SB(uc=True, test=True, headless=False) as sb:
                scraper = GMapScraper(sb)
                self.status = "Searching Google Maps..."
                self.result = scraper.search_business(self.query)
                if self.result:
                    self.status = "done"
                else:
                    self.status = "No coordinates found — try a more specific query"
        except Exception as e:
            self.status = f"error: {e}"
