"""Remotive (remotive.com): API pública de trabajo 100% remoto."""
from __future__ import annotations

import logging
from urllib.parse import quote

from ..http import Http, html_to_text
from ..models import Job, norm
from . import parse_iso

log = logging.getLogger(__name__)
API = "https://remotive.com/api/remote-jobs"
OPEN = ("worldwide", "anywhere", "latam", "latin america", "south america", "americas", "bolivia")


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    jobs, keys = [], set()
    for q in src.get("queries") or profile.get("keywords", [])[:6]:
        try:
            data = http.json(f"{API}?search={quote(q)}&limit=50").get("jobs", [])
        except Exception as e:
            log.warning("remotive %s: %s", q, e)
            continue
        for j in data:
            loc = norm(j.get("candidate_required_location"))
            if not any(o in loc for o in OPEN):  # descarta "USA only", "UK only", etc.
                continue
            job = Job(
                source="remotive", url=j["url"], title=j.get("title", ""),
                company=j.get("company_name", ""), location=j.get("candidate_required_location", ""),
                remote=True, posted_at=parse_iso(j.get("publication_date") + "Z" if j.get("publication_date") else None),
                salary=j.get("salary", ""), description=html_to_text(j.get("description"))[:8000],
                apply_url=j["url"],
            )
            if job.key not in keys and not is_seen(job.url):
                keys.add(job.key)
                jobs.append(job)
        log.info("remotive '%s': %d resultados", q, len(data))
    return jobs
