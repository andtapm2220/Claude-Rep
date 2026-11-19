"""Lector genérico de una página de oferta cualquiera (JSON-LD JobPosting o texto visible)."""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..http import Http, find_emails, html_to_text
from ..models import Job
from . import json_ld, parse_iso

log = logging.getLogger(__name__)


def pdf_to_job(url: str, data: bytes, source: str) -> Job | None:
    """Términos de referencia / convocatorias en PDF (muy común en Bolivia)."""
    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:8])
    except Exception as e:
        log.info("PDF ilegible %s: %s", url, e)
        return None
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()
    if len(text) < 100:
        return None  # PDF escaneado (imagen): sin texto
    first = next((ln.strip() for ln in text.splitlines() if len(ln.strip()) > 15), url)
    return Job(source=source, url=url, title=first[:200], description=text[:8000],
               apply_emails=find_emails(text), apply_url=url)


def page_to_job(url: str, http: Http, source: str = "manual") -> Job | None:
    try:
        r = http.get(url)
    except Exception as e:
        log.info("no se pudo abrir %s: %s", url, e)
        return None
    if "pdf" in r.headers.get("content-type", "").lower() or r.content[:5] == b"%PDF-":
        return pdf_to_job(url, r.content, source)
    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
    html = r.text
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
