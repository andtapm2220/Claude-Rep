"""PNUD: feed RSS oficial de vacantes por país (jobs.undp.org/rss_feeds/<ISO3>.xml).

Trae título, lugar, nivel (NPSA/NOA/IPSA...) y fecha de cierre. Sólo incluye
vacantes del PNUD/agencias que publican en su sistema (Quantum/Oracle).
"""
from __future__ import annotations

import logging
import re
from html import unescape

from ..http import Http
from ..models import Job
from . import parse_iso

log = logging.getLogger(__name__)
FEED = "https://jobs.undp.org/rss_feeds/{cty}.xml"


def _tag(item: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", item, re.S)
    if not m:
        return ""
    v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", v)).split())


def parse_feed(xml: str) -> list[Job]:
    jobs = []
    for item in re.findall(r"<item\b.*?</item>", xml, re.S):
        url = _tag(item, "link")
        if not url:
            continue
        level = _tag(item, "undpjobs:post_level")
        jobs.append(Job(
            source="pnud",
            url=url,
            title=_tag(item, "undpjobs:job_title") or _tag(item, "title"),
            company="PNUD / UNDP",
            location=_tag(item, "undpjobs:duty_station") or "Bolivia",
            country="BO",
            posted_at=parse_iso(_tag(item, "dc:date")),
            valid_through=parse_iso(_tag(item, "undpjobs:job_deadline_d")),
            description=(f"Vacante del PNUD. Nivel: {level or 'no indicado'} "
                         "(NPSA/NOA = contratación nacional; IPSA/P = internacional). "
                         f"{_tag(item, 'description')} Duty station: {_tag(item, 'undpjobs:duty_station')}. "
                         f"Tipo: {_tag(item, 'undpjobs:job_type')}. Se postula en el portal Quantum del PNUD."),
            apply_url=url,
            flags=["fuente_oficial"],
        ))
    return jobs


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    jobs = []
    for cty in src.get("countries", ["BOL"]):
        try:
            r = http.get(FEED.format(cty=cty))
            xml = r.content.decode("iso-8859-1", errors="ignore")
        except Exception as e:
            log.warning("pnud %s: %s", cty, e)
            continue
        found = parse_feed(xml)
        jobs += [j for j in found if not is_seen(j.url)]
        log.info("pnud %s: %d vacantes en el feed", cty, len(found))
    return jobs
