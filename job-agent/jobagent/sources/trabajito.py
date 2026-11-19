"""Trabajito (trabajito.com.bo): listados con ItemList y detalle con JobPosting en JSON-LD."""
from __future__ import annotations

import logging

from ..http import Http, find_emails, html_to_text
from ..models import Job
from . import json_ld, parse_iso

log = logging.getLogger(__name__)
BASE = "https://www.trabajito.com.bo"


def parse_detail(url: str, html: str) -> Job | None:
    posts = json_ld(html, "JobPosting")
    if not posts:
        return None
    p = posts[0]
    org = p.get("hiringOrganization") or {}
    addr = ((p.get("jobLocation") or {}).get("address")) or {}
    if isinstance(p.get("jobLocation"), list) and p["jobLocation"]:
        addr = p["jobLocation"][0].get("address", {})
    desc = html_to_text(p.get("description"))
    sal = p.get("baseSalary") or {}
    salary = ""
    if isinstance(sal, dict) and sal.get("value"):
        v = sal["value"]
        salary = f"{v.get('minValue', v.get('value', ''))}-{v.get('maxValue', '')} {sal.get('currency', '')}".strip("- ")
    return Job(
        source="trabajito",
        url=url,
        title=" ".join((p.get("title") or "").split()),
        company=org.get("name", ""),
        company_url=org.get("sameAs", "") or "",
        location=", ".join(x for x in [addr.get("addressLocality"), addr.get("addressRegion")] if x),
        country=addr.get("addressCountry", "BO"),
        remote=p.get("jobLocationType") == "TELECOMMUTE",
        posted_at=parse_iso(p.get("datePosted")),
        valid_through=parse_iso(p.get("validThrough")),
        salary=salary,
        description=desc,
        apply_emails=find_emails(desc),
        apply_url=url,
    )


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    jobs: list[Job] = []
    regions = src.get("regions") or ["bolivia"]
    max_pages = src.get("max_pages", 5)
    max_details = src.get("max_details", 80)
    for region in regions:
        for page in range(1, max_pages + 1):
            url = f"{BASE}/empleos/{region}" + (f"?page={page}" if page > 1 else "")
            html = http.text(url)
            lists = json_ld(html, "ItemList")
            urls = [i.get("url") for lst in lists for i in lst.get("itemListElement", []) if i.get("url")]
            if not urls:
                break
            new = [u for u in urls if not is_seen(u)]
            log.info("trabajito %s p%d: %d ofertas, %d nuevas", region, page, len(urls), len(new))
            for u in new:
                if len(jobs) >= max_details:
                    return jobs
                try:
                    job = parse_detail(u, http.text(u))
                except Exception as e:  # una oferta rota no debe tumbar la corrida
                    log.warning("trabajito detalle %s: %s", u, e)
                    continue
                if job:
                    jobs.append(job)
            if not new:  # listado ordenado por fecha: una página entera ya vista => no hay más nuevas
                break
    return jobs
