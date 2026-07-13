"""PageCapture — Page Object Model for full-page PNG + PDF capture.
"""
import base64
import json
from pathlib import Path

import mycdp
import yaml

_CHALLENGE_TITLES = {"just a moment", "attention required", "checking your browser", "please wait"}


_BASE_CSS = (
    "@media print { html, body { width: auto !important; height: auto !important; } }\n"
    "@media print { a::after { content: '' !important; } }\n"
    "* { animation: none !important; transition: none !important; }\n"
    "* { print-color-adjust: exact !important; -webkit-print-color-adjust: exact !important; }\n"
    "html { background: #ffffff !important; }\n"
    "body::after { content: none !important; }\n"
)


def load_config(path: Path) -> dict:
    defaults = {
        "viewport": {"width": 1920, "height": 1080},
        "timing": {
            "scroll_interval_ms":   100,
            "stabilization_ms":    800,
            "inter_page_delay_min": 0.3,
            "inter_page_delay_max": 0.5,
        },
        "hide": {},
    }
    if path.exists():
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for key, val in raw.items():
            defaults[key] = val
    return defaults


def _build_css(hide: dict, hide_visibility: dict | None = None) -> str:
    parts = [_BASE_CSS]
    for selectors in hide.values():
        if not selectors:
            continue
        sel_str = ",\n".join(selectors)
        parts.append(
            f"{sel_str} {{\n"
            f"  display: none !important;\n"
            f"  visibility: hidden !important;\n"
            f"}}"
        )
    for selectors in (hide_visibility or {}).values():
        if not selectors:
            continue
        sel_str = ",\n".join(selectors)
        parts.append(
            f"{sel_str} {{\n"
            f"  visibility: hidden !important;\n"
            f"}}"
        )
    return "\n".join(parts)


def _run(sb, cmd):
    return sb.cdp.loop.run_until_complete(sb.cdp.page.send(cmd))


def _build_selectors(hide: dict) -> list[str]:
    """Flat list of every CSS selector from the hide config."""
    result = []
    for selectors in hide.values():
        if selectors:
            result.extend(selectors)
    return result


class PageCapture:
    def __init__(self, sb, config: dict):
        self.sb           = sb
        self.viewport     = config.get("viewport", {"width": 1920, "height": 1080})
        self.timing       = config.get("timing", {})
        hide              = config.get("hide", {})
        self.css          = _build_css(hide, config.get("hide_visibility", {}))
        self._selectors   = _build_selectors(hide)
        self._cdp_active  = False

    def open(self, url: str):
        """Navigate and solve Turnstile — retries up to 5 times."""
        if self._cdp_active:
            self.sb.cdp.open(url)
        else:
            self.sb.activate_cdp_mode(url)
            self._cdp_active = True
        self.sb.sleep(1)
        self.sb.solve_captcha()
        self.sb.sleep(2)
        for _ in range(5):
            title = (self.sb.cdp.evaluate("document.title") or "").lower()
            if not any(t in title for t in _CHALLENGE_TITLES):
                break
            self.sb.solve_captcha()
            self.sb.sleep(3)

    def scroll(self):
        total = self.sb.cdp.evaluate(
            "(document.documentElement || document.body || {scrollHeight:0}).scrollHeight"
        ) or 0
        step = self.sb.cdp.evaluate("Math.round(window.innerHeight * 0.8)") or 1
        steps = max(1, int(total / step) + 1)
        delay = self.timing.get("scroll_interval_ms", 100) / 1000
        for _ in range(steps):
            self.sb.cdp.scroll_down(amount=step)
            self.sb.sleep(delay)
        self.sb.cdp.scroll_to_top()
        self.sb.sleep(delay)

    def hide_overlays(self):
        escaped = self.css.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        self.sb.cdp.execute_script(
            f"(function(){{var s=document.createElement('style');"
            f"s.textContent=`{escaped}`;"
            f"(document.head||document.documentElement).appendChild(s);}})()"
        )
        self.sb.sleep(0.5)
        self._remove_configured_elements()
        self.sb.cdp.evaluate("""
        (() => {
            const vw = window.innerWidth, vh = window.innerHeight;
            document.querySelectorAll('*').forEach(el => {
                const s = window.getComputedStyle(el);
                if (s.display === 'none') return;
                if (s.position !== 'fixed' && s.position !== 'absolute') return;
                if ((parseInt(s.zIndex) || 0) < 100) return;
                const r = el.getBoundingClientRect();
                if (r.width >= vw * 0.6 && r.height >= vh * 0.6) el.remove();
            });
            if (document.body) {
                document.body.classList.remove(
                    'modal-open','overflow-hidden','noscroll','no-scroll','scroll-lock','body-locked'
                );
                document.body.style.removeProperty('overflow');
                document.body.style.removeProperty('overflow-y');
            }
        })()
        """)

    def _content_height(self) -> int:
        try:
            metrics = _run(self.sb, mycdp.page.get_layout_metrics())
            h = int(metrics.cssContentSize.height) if metrics.cssContentSize else 0
        except Exception:
            h = 0
        if not h:
            h = self.sb.cdp.evaluate(
                "(document.documentElement || document.body || {scrollHeight:0}).scrollHeight"
            )
        return h

    def _remove_configured_elements(self):
        """Remove all elements matching the hide-config selectors from the DOM."""
        if not self._selectors:
            return
        sel_json = json.dumps(self._selectors)
        self.sb.cdp.evaluate(f"""
        (() => {{
            const sels = {sel_json};
            sels.forEach(sel => {{
                try {{
                    document.querySelectorAll(sel).forEach(el => el.remove());
                }} catch(e) {{}}
            }});
        }})()
        """)

    def capture_png(self, path: Path):
        """Full-page PNG — expands viewport manually so we can re-sweep after
        the resize event fires (chat widgets re-inject on resize)."""
        height = self._content_height()
        w = self.viewport["width"]
        _run(self.sb, mycdp.emulation.set_device_metrics_override(
            width=w, height=height, device_scale_factor=1, mobile=False
        ))
        try:
            self._remove_configured_elements()
            data = _run(self.sb, mycdp.page.capture_screenshot(
                format_="png",
                clip=mycdp.page.Viewport(x=0, y=0, width=w, height=height, scale=1),
                capture_beyond_viewport=True,
            ))
            path.write_bytes(base64.b64decode(data))
        finally:
            _run(self.sb, mycdp.emulation.set_device_metrics_override(
                width=w, height=self.viewport["height"], device_scale_factor=1, mobile=False
            ))

    def extract_data(self) -> dict:
        title = self.sb.cdp.evaluate("document.title") or ""
        try:
            h1 = self.sb.cdp.evaluate(
                "(document.querySelector('h1') || {innerText:''}).innerText"
            ).strip()
        except Exception:
            h1 = ""
        return {"page_name": title, "h1": h1}

    def extract_session(self) -> dict:
        """Extract cookies + user agent from the browser after Turnstile solve.

        Returns a dict with ``cookies`` (list of Scrapy-compatible dicts) and
        ``user_agent`` (str) for hand-off to Scrapy.
        """
        try:
            raw_cookies = self.sb.get_cookies() or []
        except Exception:
            raw_cookies = []

        cookies = []
        for c in raw_cookies:
            domain = c.get("domain", "")
            cookies.append({
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": domain,
                "path": c.get("path", "/"),
                "secure": c.get("secure", False),
                "httpOnly": c.get("httpOnly", False),
                "sameSite": c.get("sameSite", "Lax"),
            })

        try:
            user_agent = self.sb.cdp.get_user_agent() or ""
        except Exception:
            user_agent = ""
        if not user_agent:
            user_agent = self.sb.evaluate("navigator.userAgent") or ""

        return {"cookies": cookies, "user_agent": user_agent}

    def run(self, url: str, png_path: Path) -> dict:
        """Full capture pipeline for one URL. Returns page data dict."""
        self.open(url)
        self.scroll()
        self.sb.sleep(self.timing.get("stabilization_ms", 800) / 1000)
        self.hide_overlays()
        self.capture_png(png_path)
        return self.extract_data()
