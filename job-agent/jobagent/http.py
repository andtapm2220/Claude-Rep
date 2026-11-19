from __future__ import annotations

import logging
import random
import re
import time
from html import unescape

import requests

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class Blocked(Exception):
    """El sitio respondió con un desafío anti-bot (Cloudflare) o 403."""


class Http:
    """Sesión con pausas entre pedidos a un mismo host, para no saturar portales chicos."""

    def __init__(self, delay: float = 1.5, timeout: float = 25):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "es-BO,es;q=0.9,en;q=0.5"})
        self.delay = delay
        self.timeout = timeout
        self._last: dict[str, float] = {}

    def _wait(self, url: str) -> None:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        elapsed = time.monotonic() - self._last.get(host, 0)
        pause = self.delay + random.uniform(0, self.delay / 2)
        if elapsed < pause:
            time.sleep(pause - elapsed)
        self._last[host] = time.monotonic()

    def get(self, url: str, **kw) -> requests.Response:
        self._wait(url)
        for attempt in range(3):
            try:
                r = self.s.get(url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                if attempt == 2:
                    raise
                log.warning("GET %s falló (%s), reintento", url, e)
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 403 or "challenges.cloudflare.com" in r.text[:5000]:
                raise Blocked(f"{url} -> {r.status_code} (anti-bot)")
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("unreachable")

    def text(self, url: str) -> str:
        r = self.get(url)
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
        return r.text

    def json(self, url: str, **kw):
        return self.get(url, **kw).json()


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    html = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", html)
    html = re.sub(r"(?i)<li[^>]*>", "• ", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def find_emails(text: str) -> list[str]:
    out = []
    for e in EMAIL_RE.findall(text or ""):
        e = e.strip(".").lower()
        if e not in out and not e.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            out.append(e)
    return out
