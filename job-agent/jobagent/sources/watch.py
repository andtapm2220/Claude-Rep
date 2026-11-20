"""Vigía de páginas: revisa a diario páginas de "convocatorias" que no tienen API
(boletín Redesma/CEBEM, UNITAS, ONG, ministerios, BCB, ASFI, embajadas...) y
avisa los enlaces NUEVOS que parecen una convocatoria. Abre cada uno (HTML o PDF de
términos de referencia) para que Claude lo evalúe.

La primera vez que ve una página, sólo toma los primeros `max_new` enlaces (los
más recientes suelen estar arriba) para no inundarte con el histórico.
"""
from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import urljoin

from ..http import Http
from ..models import Job
from . import spanish_date
from .generic import page_to_job

log = logging.getLogger(__name__)

JOBISH = re.compile(
    r"convocatoria|consultor|vacan|t[eé]rminos de referencia|\btdr\b|requiere|busca|invita|contrataci[oó]n|"
    r"especialista|oficial|t[eé]cnic[oa]|coordinador|responsable|analista|asistente|cargo|puesto|job|vacancy|"
    r"position|hiring|recruit", re.I)
NOISE = re.compile(r"@|facebook\.com|twitter\.com|x\.com|instagram|youtube|whatsapp|mailto:|javascript:|#$|/tag/|/page/\d+/?$|/category/", re.I)


def extract_links(html: str, base: str, must_contain: str | None = None) -> list[tuple[str, str]]:
    out, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        text = " ".join(unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        url = urljoin(base, unescape(href).replace("https:/Portals", "/Portals"))
        if NOISE.search(url) or re.sub(r"#.*$", "", url).rstrip("/") == base.rstrip("/"):
            continue
        if must_contain and must_contain not in url:
            continue
        if not JOBISH.search(f"{text} {url}"):
            continue
        key = re.sub(r"[?#].*$", "", url)
        if key in seen:
            continue
        seen.add(key)
        out.append((url, text))
    return out


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    jobs: list[Job] = []
    for page in src.get("pages", []):
        url, name = page["url"], page.get("name", page["url"])
        try:
            html = http.text(url)
        except Exception as e:
            log.warning("vigía %s: no se pudo abrir (%s)", name, e)
            continue
        links = extract_links(html, url, page.get("link_must_contain"))
        new = [(u, t) for u, t in links if not is_seen(u)][: page.get("max_new", 15)]
        log.info("vigía %s: %d enlaces de convocatoria, %d nuevos", name, len(links), len(new))
        for u, text in new:
            j = page_to_job(u, http, source=f"vigia:{name}")
            if j is None:
                j = Job(source=f"vigia:{name}", url=u, title=text[:200], apply_url=u,
                        description=f"Convocatoria publicada en {name}: {text}")
            # El texto del enlace en el listado suele describir mejor la convocatoria que el <h1> del sitio
            generic_text = text.lower() in ("aquí", "aqui", "ver más", "descargar", "términos de referencia",
                                            "estos son los términos de referencia", "convocatoria completa") or text.startswith("http")
            if len(text) > 15 and not generic_text:
                j.title = text[:200]
            # quita emails del propio sitio (p. ej. el del boletín), no son de postulación
            host = re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", url)
            j.apply_emails = [e for e in j.apply_emails if host.split(".")[0] not in e.split("@")[-1]]
            # Organización: "HELVETAS Swiss Intercooperation: Requiere..." -> "HELVETAS Swiss Intercooperation"
            head = j.title.split(":")[0].strip()
            if not j.company and ":" in j.title and 3 < len(head) < 70 and not head.lower().startswith(("convocatoria", "tdr")):
                j.company = head
            if not j.posted_at:  # la fecha suele estar en la cabecera: leerla antes de recortar
                j.posted_at = spanish_date(j.description[:1500])
            # Quita la cabecera del sitio: el texto útil empieza donde aparece el título de la convocatoria
            probe = j.title[:40].lower()
            pos = j.description.lower().find(probe, 30) if probe else -1
            if pos > 0:
                j.description = j.description[pos:]
            j.company = j.company or page.get("org", "")
            j.country = j.country or "BO"
            j.location = j.location or page.get("location", "Bolivia")
            j.flags.append("fuente_oficial")
            jobs.append(j)
    return jobs
