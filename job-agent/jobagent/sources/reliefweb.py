"""ReliefWeb (OCHA/ONU): ofertas de ONG, ONU y cooperación por país, vía API oficial.

Requiere un 'appname' aprobado (gratis): https://apidoc.reliefweb.int/parameters#appname
Configúralo en el secreto RELIEFWEB_APPNAME. Sin él, la fuente se omite.
"""
from __future__ import annotations

import logging
import os

from ..http import Http, find_emails, html_to_text
from ..models import Job
from . import parse_iso

log = logging.getLogger(__name__)
API = "https://api.reliefweb.int/v2/jobs?appname={app}"


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    app = os.environ.get("RELIEFWEB_APPNAME")
    if not app:
        log.info("reliefweb: sin RELIEFWEB_APPNAME, se omite")
        return []
    body = {
        "filter": {"field": "country.name", "value": src.get("countries", ["Bolivia (Plurinational State of)"]), "operator": "OR"},
        "fields": {"include": ["title", "url", "body", "source.name", "date.created", "date.closing", "city.name", "how_to_apply"]},
        "sort": ["date.created:desc"],
        "limit": src.get("limit", 50),
    }
    try:
        r = http.s.post(API.format(app=app), json=body, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        log.warning("reliefweb: %s", e)
        return []
    jobs = []
    for d in data:
        f = d.get("fields", {})
        url = f.get("url", "")
        if not url or is_seen(url):
            continue
        desc = html_to_text(f.get("body", "")) + "\n\nCómo postular:\n" + html_to_text(f.get("how_to_apply", ""))
        cities = ", ".join(c.get("name", "") for c in f.get("city", []) or [])
        jobs.append(Job(
            source="reliefweb", url=url, title=f.get("title", ""),
            company=", ".join(s.get("name", "") for s in f.get("source", []) or []),
            location=(cities + ", Bolivia").strip(", "), country="BO",
            posted_at=parse_iso((f.get("date") or {}).get("created")),
            valid_through=parse_iso((f.get("date") or {}).get("closing")),
            description=desc[:8000], apply_emails=find_emails(desc), apply_url=url,
        ))
    log.info("reliefweb: %d ofertas nuevas", len(jobs))
    return jobs
