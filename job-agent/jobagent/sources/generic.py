"""Lector genérico de una página de oferta cualquiera (JSON-LD JobPosting o texto visible)."""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..http import Http, find_emails, html_to_text
from ..models import Job
from . import json_ld, parse_iso

log = logging.getLogger(__name__)


def page_to_job(url: str, http: Http, source: str = "manual") -> Job | None:
    try:
        html = http.text(url)
    except Exception as e:
        log.info("no se pudo abrir %s: %s", url, e)
        return None
    posts = json_ld(html, "JobPosting")
    if posts:
        p = posts[0]
        org = p.get("hiringOrganization") or {}
        loc = p.get("jobLocation") or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        addr = (loc.get("address") if isinstance(loc, dict) else {}) or {}
        desc = html_to_text(p.get("description"))
        return Job(
            source=source, url=url, title=" ".join((p.get("title") or "").split()),
            company=org.get("name", "") if isinstance(org, dict) else str(org),
            company_url=org.get("sameAs", "") if isinstance(org, dict) else "",
            location=", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion")] if x),
            country=addr.get("addressCountry", "") if isinstance(addr.get("addressCountry", ""), str) else "",
            remote=p.get("jobLocationType") == "TELECOMMUTE",
            posted_at=parse_iso(p.get("datePosted")), valid_through=parse_iso(p.get("validThrough")),
            description=desc[:8000], apply_emails=find_emails(desc), apply_url=url,
        )
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        t.decompose()
    title = (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else
             (soup.title.get_text(strip=True) if soup.title else url))
    text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n")).strip()
    return Job(source=source, url=url, title=title[:200], description=text[:8000],
               apply_emails=find_emails(text), apply_url=url)
