"""Get on Board (getonbrd.com): API pública v0, ofertas de Latinoamérica (mucho remoto)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote

from ..http import Http, find_emails, html_to_text
from ..models import Job, norm

log = logging.getLogger(__name__)
API = "https://www.getonbrd.com/api/v0/search/jobs"


def to_job(item: dict) -> Job:
    a = item["attributes"]
    comp = ((a.get("company") or {}).get("data") or {}).get("attributes") or {}
    desc = "\n".join(html_to_text(a.get(k)) for k in ("description", "functions", "desirable", "benefits") if a.get(k))
    sal = ""
    if a.get("min_salary") or a.get("max_salary"):
        sal = f"USD {a.get('min_salary') or '?'}-{a.get('max_salary') or '?'} /mes"
    ts = a.get("published_at")
    return Job(
        source="getonbrd",
        url=(item.get("links") or {}).get("public_url") or f"https://www.getonbrd.com/jobs/{item['id']}",
        title=a.get("title", ""),
        company=comp.get("name", ""),
        company_url=comp.get("web", "") or "",
        location=", ".join(a.get("countries") or []),
        country=",".join(a.get("countries") or []),
        remote=bool(a.get("remote")) or a.get("remote_modality") == "fully_remote",
        posted_at=datetime.fromtimestamp(ts, timezone.utc) if ts else None,
        salary=sal,
        description=desc[:8000],
        apply_emails=find_emails(desc),
        apply_url=(item.get("links") or {}).get("public_url", ""),
    )


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    want = [norm(c) for c in src.get("countries", ["Bolivia"])]
    jobs, keys = [], set()
    for q in src.get("queries") or profile.get("keywords", [])[:8]:
        url = f"{API}?query={quote(q)}&per_page=50&page=1&expand=%5B%22company%22%5D"
        try:
            data = http.json(url).get("data", [])
        except Exception as e:
            log.warning("getonbrd %s: %s", q, e)
            continue
        for item in data:
            job = to_job(item)
            countries = [norm(c) for c in job.country.split(",") if c]
            # Remoto abierto a la región, o presencial en un país que te interesa
            ok = (job.remote and src.get("accept_remote", True)) or any(c in want for c in countries)
            if ok and job.key not in keys and not is_seen(job.url):
                keys.add(job.key)
                jobs.append(job)
        log.info("getonbrd '%s': %d resultados", q, len(data))
    return jobs
