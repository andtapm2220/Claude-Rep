"""Computrabajo Bolivia (bo.computrabajo.com): HTML de listados y de detalle."""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..http import Http, find_emails
from ..models import Job
from . import relative_date

log = logging.getLogger(__name__)
BASE = "https://bo.computrabajo.com"


def _clean(s: str) -> str:
    return " ".join((s or "").split())


def parse_list(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for art in soup.find_all("article"):
        a = art.select_one("h2 a.js-o-link") or art.select_one("h2 a")
        if not a or not a.get("href"):
            continue
        href = re.sub(r"#.*$", "", a["href"])
        url = href if href.startswith("http") else BASE + href
        comp = art.select_one("[offer-grid-article-company-url]") or art.select_one("p a")
        ps = [_clean(p.get_text(" ")) for p in art.find_all("p")]
        loc = next((p for p in ps[1:] if "," in p and len(p) < 60), "")
        sal = art.select_one(".i_salary")
        date_txt = next((p for p in ps if re.search(r"(?i)hace|ayer|hoy", p)), "")
        out.append(Job(
            source="computrabajo",
            url=url,
            title=_clean(a.get_text(" ")),
            company=_clean(comp.get_text(" ")) if comp else "",
            location=loc,
            country="BO",
            salary=_clean(sal.parent.get_text(" ")) if sal else "",
            posted_at=relative_date(date_txt),
            apply_url=url,
            flags=["empresa_verificada_portal"] if art.select_one(".i_verificada") else [],
        ))
    return out


def parse_detail(job: Job, html: str) -> Job:
    soup = BeautifulSoup(html, "html.parser")
    box = None
    for h in soup.find_all(["h3", "h2", "p"]):
        if "Descripción de la oferta" in h.get_text():
            box = h.parent
            break
    text = box.get_text("\n") if box else soup.get_text("\n")
    text = re.sub(r"\n\s*\n+", "\n", text)
    # El bloque termina antes de "Postularme"/secciones de empresa
    text = re.split(r"\n(?:Postularme|Ofertas similares|Valoración de la empresa)", text)[0]
    job.description = text.strip()[:8000]
    job.apply_emails = find_emails(job.description)
    if "remoto" in job.description.lower() or "teletrabajo" in job.description.lower():
        job.remote = True
    return job


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    paths = [f"empleos-en-{r}" for r in (src.get("regions") or ["la-paz"])]
    paths += [f"trabajo-de-{k}" for k in src.get("keyword_pages", [])]
    max_pages, max_details = src.get("max_pages", 4), src.get("max_details", 80)
    jobs: list[Job] = []
    queued: set[str] = set()
    for path in paths:
        for page in range(1, max_pages + 1):
            url = f"{BASE}/{path}" + (f"?p={page}" if page > 1 else "")
            listed = parse_list(http.text(url))
            if not listed:
                break
            new = [j for j in listed if not is_seen(j.url) and j.url not in queued]
            log.info("computrabajo %s p%d: %d ofertas, %d nuevas", path, page, len(listed), len(new))
            for j in new:
                if len(jobs) >= max_details:
                    return jobs
                queued.add(j.url)
                try:
                    jobs.append(parse_detail(j, http.text(j.url)))
                except Exception as e:
                    log.warning("computrabajo detalle %s: %s", j.url, e)
    return jobs
