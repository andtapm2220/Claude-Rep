"""Trabajópolis (trabajopolis.bo): protegido por Cloudflare; se intenta y, si bloquea, se omite."""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ..http import Blocked, Http, find_emails, html_to_text
from ..models import Job
from . import json_ld, parse_iso, relative_date

log = logging.getLogger(__name__)
BASE = "https://www.trabajopolis.bo"


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    jobs: list[Job] = []
    try:
        for region in src.get("regions") or ["la-paz"]:
            html = http.text(f"{BASE}/empleos/{region}")
            links = sorted(set(re.findall(r'href="((?:https://www\.trabajopolis\.bo)?/trabajo/\d+/[^"#?]+)"', html)))
            for href in links[: src.get("max_details", 40)]:
                url = href if href.startswith("http") else BASE + href
                if is_seen(url):
                    continue
                page = http.text(url)
                posts = json_ld(page, "JobPosting")
                if posts:
                    p = posts[0]
                    desc = html_to_text(p.get("description"))
                    jobs.append(Job(
                        source="trabajopolis", url=url, title=p.get("title", ""),
                        company=(p.get("hiringOrganization") or {}).get("name", ""),
                        location=region.replace("-", " ").title(), country="BO",
                        posted_at=parse_iso(p.get("datePosted")), valid_through=parse_iso(p.get("validThrough")),
                        description=desc, apply_emails=find_emails(desc), apply_url=url,
                    ))
                else:
                    soup = BeautifulSoup(page, "html.parser")
                    h1 = soup.find("h1")
                    desc = soup.get_text("\n")[:8000]
                    jobs.append(Job(
                        source="trabajopolis", url=url, title=h1.get_text(" ", strip=True) if h1 else "",
                        location=region.replace("-", " ").title(), country="BO",
                        posted_at=relative_date(desc), description=desc,
                        apply_emails=find_emails(desc), apply_url=url,
                    ))
    except Blocked as e:
        log.warning("trabajopolis bloqueado por anti-bot, se omite hoy: %s", e)
    return jobs
