"""Vigía de páginas: revisa a diario páginas de "convocatorias" que no tienen API
(boletín Redesma/CEBEM, UNITAS, ONG, ministerios, BCB, ASFI, embajadas...) y
avisa los enlaces NUEVOS que parecen una convocatoria. Abre cada uno (HTML o PDF de
términos de referencia) para que Claude lo evalúe.

La primera vez que ve una página, sólo toma los primeros `max_new` enlaces (los
más recientes suelen estar arriba) para no inundarte con el histórico.
"""
from __future__ import annotations

import hashlib
import logging
import re
from html import unescape
from urllib.parse import urljoin

from ..http import Http
from ..models import Job
from . import deadline_in_text, spanish_date
from .generic import page_to_job

log = logging.getLogger(__name__)

JOBISH = re.compile(
    r"convocatoria|consultor|vacan|t[eé]rminos de referencia|\btdr\b|requiere|busca|invita|contrataci[oó]n|"
    r"especialista|oficial|t[eé]cnic[oa]|coordinador|responsable|analista|asistente|cargo|puesto|job|vacancy|"
    r"position|hiring|recruit", re.I)
NOISE = re.compile(r"contrataciondelestado|/login|/accountcreation|forgotpassword|@|facebook\.com|twitter\.com|x\.com|instagram|youtube|whatsapp|mailto:|javascript:|#$|/tag/|/page/\d+/?$|/category/", re.I)


def parse_rss(xml: str) -> list[tuple[str, str, str]]:
    """Feed RSS genérico -> [(link, título, descripción)]."""
    out = []
    for item in re.findall(r"<item\b.*?</item>", xml, re.S):
        def tag(n):
            m = re.search(rf"<{n}[^>]*>(.*?)</{n}>", item, re.S)
            v = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S) if m else ""
            return unescape(v).strip()
        if tag("link"):
            out.append((tag("link"), " ".join(unescape(re.sub(r"<[^>]+>", " ", tag("title"))).split()), tag("description")))
    return out


def extract_links(html: str, base: str, must_contain: str | None = None,
                  link_pattern: str | None = None) -> list[tuple[str, str]]:
    out, seen = [], set()
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        text = " ".join(unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        url = urljoin(base, unescape(href).replace("https:/Portals", "/Portals"))
        if NOISE.search(url) or re.sub(r"#.*$", "", url).rstrip("/") == base.rstrip("/"):
            continue
        if must_contain and must_contain not in url:
            continue
        if link_pattern:
            if not re.search(link_pattern, url):
                continue
        elif not JOBISH.search(f"{text} {url}"):
            continue
        key = re.sub(r"[?#].*$", "", url)
        if key in seen:
            continue
        seen.add(key)
        out.append((url, text))
    return out


def _lines(html: str) -> dict[str, str]:
    """Renglones visibles de la página -> {huella: renglón}. Sin menús ni pie (líneas cortas o repetidas)."""
    from ..http import html_to_text

    html = re.sub(r"(?is)<(script|style|nav|footer|header|noscript)\b.*?</\1>", " ", html)
    out = {}
    for ln in html_to_text(html).splitlines():
        ln = " ".join(ln.split())
        if len(ln) >= 12 and not re.fullmatch(r"[\d\s/:.,-]+", ln):
            out[hashlib.sha1(ln.lower().encode()).hexdigest()[:10]] = ln
    return out


def changed_job(page: dict, html: str, est: dict) -> Job | None:
    """Modo `tipo: cambio`: páginas de empleo sin enlaces por oferta (texto, tablas, avisos).
    Guarda la huella de cada renglón; si aparecen renglones nuevos que parecen una vacante, arma una oferta
    con SOLO esos renglones (Claude ve el cambio, no la página entera). La primera visita sólo toma la foto."""
    lines = _lines(html)
    prev = est.get("lineas")
    est["lineas"] = sorted(lines)
    if prev is None:
        return None
    seen = set(prev)
    new = [ln for h, ln in lines.items() if h not in seen]
    if not any(JOBISH.search(ln) for ln in new):
        return None
    from datetime import date

    url, name = page["url"], page.get("name", page["url"])
    text = "\n".join(new)[:4000]
    title = next((ln for ln in new if JOBISH.search(ln)), new[0])[:200]
    return Job(source=f"vigia:{name}", url=f"{url}#cambio-{date.today().isoformat()}", title=title,
               company=page.get("org", ""), country="BO", location=page.get("location", "Bolivia"),
               description=f"Cambio nuevo en la página de empleo de {name} ({url}):\n{text}", apply_url=url,
               posted_at=spanish_date(text), valid_through=deadline_in_text(text), flags=["fuente_oficial", "cambio_pagina"])


def health_report(estado: dict, today: str) -> str:
    """Páginas vigiladas que fallan 3 veces seguidas o que no muestran convocatorias hace 60 días."""
    from datetime import date

    bad = []
    for url, e in sorted(estado.items()):
        if e.get("fallos", 0) >= 3:
            bad.append(f"- {e.get('nombre', url)}: no abre hace {e['fallos']} corridas ({e.get('error', '')}). {url}")
        elif e.get("ultimo_enlace") and (date.fromisoformat(today) - date.fromisoformat(e["ultimo_enlace"])).days > 60:
            bad.append(f"- {e.get('nombre', url)}: sin convocatorias desde {e['ultimo_enlace']} (¿cambió de sistema?). {url}")
    head = f"# Salud del vigía ({today}): {len(estado)} páginas, {len(bad)} con problemas\n"
    return head + ("\n".join(bad) + "\n" if bad else "Todo bien.\n")


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    import json
    from datetime import date
    from pathlib import Path

    jobs: list[Job] = []
    pages = list(src.get("pages", []))
    root = Path(__file__).resolve().parents[2]
    if src.get("incluir_directorio", True):
        from .. import directorio

        pages += directorio.watch_pages(directorio.load(root, profile))
    from ..store import Store

    store = Store(root / "state/jobs.db")  # memoria del vigía en la misma base que ya se guarda con git
    estado = json.loads(store.kv_get("vigia_estado", "{}") or "{}")
    today = date.today().isoformat()
    pages = list({p["url"]: p for p in reversed(pages)}.values())[::-1]  # misma página para 2 empresas: una vez

    def bajar(page):  # descargas en paralelo (sitios distintos); el resto sigue en orden
        try:
            return page, Http(delay=http.delay, timeout=http.timeout).text(page["url"]), None
        except Exception as e:
            return page, None, e

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(src.get("paralelo", 8)) as ex:
        bajadas = list(ex.map(bajar, pages))
    for page, html, err in bajadas:
        url, name = page["url"], page.get("name", page["url"])
        est = estado.setdefault(url, {})
        est["nombre"] = name
        if err is not None:
            log.warning("vigía %s: no se pudo abrir (%s)", name, err)
            est["fallos"], est["error"] = est.get("fallos", 0) + 1, type(err).__name__
            continue
        est["fallos"] = 0
        est.setdefault("ultimo_enlace", today)
        if page.get("tipo") == "cambio":
            j = changed_job(page, html, est)
            if j:
                est["ultimo_enlace"] = today
                jobs.append(j)
            continue
        if page.get("tipo") == "rss":
            from ..http import find_emails, html_to_text

            items = [(u, t, d) for u, t, d in parse_rss(html) if not is_seen(u)][: page.get("max_new", 15)]
            log.info("vigía %s (RSS): %d nuevas", name, len(items))
            for u, t, d in items:
                desc = html_to_text(d)
                j = Job(source=f"vigia:{name}", url=u, title=t[:200], company=page.get("org", ""), country="BO",
                        location=page.get("location", "Bolivia"), description=desc[:8000], apply_url=u,
                        apply_emails=find_emails(desc), flags=["fuente_oficial"])
                j.posted_at = spanish_date(desc[:1500])
                j.valid_through = deadline_in_text(desc)
                jobs.append(j)
            continue
        links = extract_links(html, url, page.get("link_must_contain"), page.get("link_pattern"))
        # Impactpool y similares marcan estado en el texto del enlace
        links = [(u, re.sub(r"^(new job|closing soon|closing tomorrow|closing today|job is closed)\s*:?\s*", "", t, flags=re.I))
                 for u, t in links if not re.match(r"job is closed|closed", t, re.I)]
        if links:
            est["ultimo_enlace"] = today
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
            if not j.valid_through:  # Impactpool y similares: "Application deadline: November 22, 2026"
                m = re.search(r"(?:application deadline|deadline)\s*:?\s*([A-Z][a-z]+ \d{1,2}, 20\d\d)", j.description)
                if m:
                    try:
                        from datetime import datetime, timedelta, timezone
                        j.valid_through = datetime.strptime(m.group(1), "%B %d, %Y").replace(
                            hour=23, minute=59, tzinfo=timezone(timedelta(hours=-4)))
                    except ValueError:
                        pass
            if not j.posted_at:  # la fecha suele estar en la cabecera: leerla antes de recortar
                j.posted_at = spanish_date(j.description[:1500])
            if not j.valid_through:
                j.valid_through = deadline_in_text(j.description)
            # Cabecera fija del boletín Redesma
            cut = j.description.find("Canal de Boletín REDESMA")
            if 0 < cut < 4000:
                j.description = j.description[cut + len("Canal de Boletín REDESMA"):].strip()
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
    store.kv_set("vigia_estado", json.dumps(estado, ensure_ascii=False))
    store.commit()
    (root / "output").mkdir(exist_ok=True)
    (root / "output/vigia_salud.md").write_text(health_report(estado, today), encoding="utf-8")
    return jobs
