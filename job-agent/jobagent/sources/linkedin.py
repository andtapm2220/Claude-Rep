"""LinkedIn en modo invitado (sin iniciar sesión).

No usa tu cuenta, así que no hay cuenta que puedan banear. Lo único que LinkedIn
puede hacer es frenar temporalmente la IP (HTTP 429), y para evitarlo:
  - sólo ofertas publicadas en las últimas 24 h (f_TPR=r86400): pocas por día,
  - 1 página (25 resultados) por búsqueda y pocas búsquedas,
  - pausas largas y aleatorias entre pedidos,
  - si responde 429 o con un muro de login, se detiene hasta mañana.
"""
from __future__ import annotations

import logging
import re
import time
import random
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..http import Blocked, Http, find_emails
from ..models import Job
from . import relative_date

log = logging.getLogger(__name__)
SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={q}&location={loc}&f_TPR={tpr}&start=0"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


def job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}"


def parse_search(html: str) -> list[tuple[str, str, str, str, str]]:
    """-> [(id, title, company, location, date)]"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for card in soup.select("div.base-card"):
        m = re.search(r"jobPosting:(\d+)", card.get("data-entity-urn", ""))
        if not m:
            continue
        g = lambda sel: (card.select_one(sel).get_text(" ", strip=True) if card.select_one(sel) else "")
        t = card.select_one("time")
        out.append((m.group(1), g(".base-search-card__title"), g(".base-search-card__subtitle"),
                    g(".job-search-card__location"), t.get("datetime", "") if t else ""))
    return out


def parse_detail(job_id: str, html: str) -> Job:
    soup = BeautifulSoup(html, "html.parser")
    g = lambda sel: (soup.select_one(sel).get_text(" ", strip=True) if soup.select_one(sel) else "")
    desc_el = soup.select_one(".description__text")
    desc = desc_el.get_text("\n", strip=True) if desc_el else ""
    criteria = g(".description__job-criteria-list")
    comp_a = soup.select_one(".topcard__org-name-link")
    loc = g(".topcard__flavor--bullet")
    return Job(
        source="linkedin",
        url=job_url(job_id),
        title=g("h2.top-card-layout__title") or g("h1"),
        company=g(".topcard__org-name-link") or g(".topcard__flavor"),
        company_url=re.sub(r"\?.*$", "", comp_a.get("href", "")) if comp_a else "",
        location=loc,
        country="BO" if "bolivia" in loc.lower() else "",
        remote="remote" in (loc + criteria).lower() or "remoto" in desc.lower()[:2000],
        posted_at=relative_date(g(".posted-time-ago__text")),
        description=(desc + ("\n\n" + criteria if criteria else ""))[:8000],
        apply_emails=find_emails(desc),
        apply_url=job_url(job_id),
    )


def fetch_ids(ids: list[str], http: Http, limit: int) -> list[Job]:
    jobs = []
    for jid in ids[:limit]:
        time.sleep(random.uniform(3, 7))
        try:
            jobs.append(parse_detail(jid, http.text(DETAIL.format(id=jid))))
        except Blocked as e:
            log.warning("LinkedIn frenó los pedidos (%s); se sigue mañana", e)
            break
        except Exception as e:
            if "429" in str(e):
                log.warning("LinkedIn 429: se detiene por hoy")
                break
            log.warning("linkedin detalle %s: %s", jid, e)
    return jobs


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    queries = src.get("queries") or profile.get("keywords", [])[:3]
    locations = src.get("locations", ["Bolivia"])
    tpr = src.get("time_range", "r86400")
    ids: list[str] = []
    for loc in locations:
        for q in queries:
            time.sleep(random.uniform(4, 9))
            try:
                rows = parse_search(http.text(SEARCH.format(q=quote(q), loc=quote(loc), tpr=tpr)))
            except Exception as e:
                log.warning("linkedin búsqueda '%s' en %s detenida: %s", q, loc, e)
                return fetch_ids(ids, http, src.get("max_details", 30))
            new = [r[0] for r in rows if not is_seen(job_url(r[0])) and r[0] not in ids]
            log.info("linkedin '%s' @ %s: %d resultados, %d nuevos", q, loc, len(rows), len(new))
            ids += new
    return fetch_ids(ids, http, src.get("max_details", 30))
