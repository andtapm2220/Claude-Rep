"""Descubre la página de empleo de cada institución (una sola vez, sin IA).

Entrada: CSV con columnas nombre, categoria, sitio[, empleo_url]. Para cada sitio prueba, en orden barato:
  1. empleo_url ya conocida;
  2. enlaces de la portada con palabras de empleo ("trabaja con nosotros", "convocatorias", "careers"...)
     o que apuntan a una plataforma de postulación conocida (evaluar.com, Buk, Workday...);
  3. rutas típicas (/trabaja-con-nosotros, /empleos, /convocatorias, /careers...);
  4. el mapa del sitio (sitemap.xml).
Luego abre cada candidata y decide el modo del vigía:
  - "enlaces": la página lista ofertas con enlace propio que comparten ruta -> se arma `link_pattern` solo;
  - "cambio": la página existe pero no tiene enlaces por oferta -> el vigía compara renglones (tipo: cambio);
  - "sin_pagina" o "error:<tipo>": queda en la rotación de búsquedas web.

Uso: python -m jobagent descubrir entrada.csv [más.csv] --out state/descubrimiento.json [--inseguro]
"""
from __future__ import annotations

import csv
import json
import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .http import Http
from .models import norm
from .sources.watch import JOBISH, NOISE, extract_links

log = logging.getLogger(__name__)

CARRERA = re.compile(
    r"trabaj[ae]\s+con\s+nosotros|unete|[uú]nete|empleos?\b|convocatorias?|oportunidad(?:es)?\s+(?:laboral|de\s+empleo|de\s+trabajo)|"
    r"bolsa\s+de\s+trabajo|vacantes?|careers?|jobs?\b|talento\s+humano|recursos\s+humanos|postula|work\s+with\s+us|"
    r"trabaja-con-nosotros|trabaje-con-nosotros|carrera", re.I)
ATS = {
    "evaluar": r"\.evaluar\.com", "buk": r"\.buk\.(?:bo|cl|pe|co|mx)|buk\.co/", "workday": r"myworkdayjobs\.com",
    "successfactors": r"successfactors|jobs\.sap\.com", "teamtailor": r"teamtailor\.com", "hiringroom": r"hiringroom\.com",
    "computrabajo": r"computrabajo\.com", "trabajando": r"trabajando\.com", "lever": r"lever\.co",
    "greenhouse": r"greenhouse\.io", "careers-page": r"careers-page\.com", "airavirtual": r"airavirtual\.com",
    "odoo": r"/postulantes|/jobs/detail|/jobs/apply",
}
# Ruta de cada oferta en las plataformas conocidas: con esto basta una regla por plataforma
PATRON_ATS = {
    "evaluar": r"/trabajo/[^/?#]+/?$", "careers-page": r"/jobs/[0-9a-f-]{36}/?$", "teamtailor": r"/jobs/\d+-[^/?#]+$",
    "successfactors": r"/job/[^?#]+/\d+/?$", "workday": r"/job/[^?#]+_[A-Z0-9-]+$", "buk": r"/jobs?/\d+",
    "hiringroom": r"/jobs/get_vacancy/|/vacancy/", "lever": r"lever\.co/[^/]+/[0-9a-f-]{36}$",
    "greenhouse": r"/jobs/\d+", "odoo": r"/(?:postulantes/convocatoria|jobs/detail)/[^/?#]+/?$",
}
RUTAS = ["trabaja-con-nosotros", "trabaje-con-nosotros", "empleos", "empleo", "convocatorias", "careers",
         "oportunidades-laborales", "bolsa-de-trabajo", "unete", "talento-humano", "jobs"]


def plataforma(url: str) -> str:
    return next((k for k, p in ATS.items() if re.search(p, url, re.I)), "")


def candidatos(home_html: str, base: str) -> list[str]:
    out = []
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', home_html, re.S | re.I):
        text = " ".join(unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        url = urljoin(base, unescape(href))
        if not url.startswith("http") or NOISE.search(url) and not plataforma(url):
            continue
        if plataforma(url) or CARRERA.search(norm(text)) or CARRERA.search(urlparse(url).path):
            if url not in out:
                out.append(url)
    # lo más específico primero: plataformas, luego "trabaja con nosotros", luego el resto
    return sorted(out, key=lambda u: (not plataforma(u), not re.search(r"trabaj|empleo|career|convocator", u, re.I)))[:6]


def patron(job_links: list[str], page: str) -> str | None:
    """Si >= 2 ofertas comparten la misma ruta padre (p. ej. /postulantes/convocatoria/7, /8, /9), arma el patrón."""
    host = urlparse(page).netloc.lower()
    stems = Counter()
    for u in job_links:
        p = urlparse(u)
        if p.netloc.lower() != host:
            continue
        parts = p.path.rstrip("/").rsplit("/", 1)
        if len(parts) == 2 and parts[0]:
            stems[parts[0]] += 1
    if not stems:
        return None
    stem, n = stems.most_common(1)[0]
    # la ruta común debe ser "de empleo" (o colgar de la misma sección que la página); si no, son menús del sitio
    seccion = urlparse(page).path.strip("/").split("/")[0]
    de_empleo = CARRERA.search(stem) or re.search(r"convocatoria|vacante|oferta|puesto|trabajo|job", stem, re.I) \
        or (seccion and stem.strip("/").split("/")[0] == seccion)
    return re.escape(stem) + r"/[^/?#]+/?$" if n >= 2 and de_empleo else None


def evaluar_pagina(url: str, http: Http) -> dict:
    html = http.text(url)
    plat = plataforma(url) or plataforma(html[:20000])
    pat = PATRON_ATS.get(plat)
    links = [u for u, _ in extract_links(html, url, link_pattern=pat)] if pat else []
    if len(links) < 1:  # plataforma propia: se deduce la ruta común de las ofertas
        links = [u for u, _ in extract_links(html, url)]
        pat = patron(links, url)
    hits = sum(1 for u in links if pat and re.search(pat, u, re.I))
    texto = norm(re.sub(r"<[^>]+>", " ", html))
    return {"url": url, "plataforma": plat, "enlaces": len(links),
            "link_pattern": pat, "ofertas_con_patron": hits, "parece_empleo": bool(CARRERA.search(texto[:20000])),
            "muestra": links[:3]}


def descubrir_uno(row: dict, http: Http) -> dict:
    nombre, sitio = row.get("nombre", "").strip(), (row.get("sitio") or "").strip()
    res = {"nombre": nombre, "categoria": row.get("categoria", ""), "sitio": sitio}
    urls: list[str] = [u for u in [(row.get("empleo_url") or "").strip()] if u]
    if sitio:
        try:
            home = http.text(sitio)
            urls += candidatos(home, sitio)
        except Exception as e:
            res["error_portada"] = type(e).__name__
        if not urls:
            base = sitio.rstrip("/") + "/"
            for r in RUTAS:
                try:
                    resp = http.s.get(base + r, timeout=12, allow_redirects=True)
                    if resp.status_code == 200 and CARRERA.search(norm(resp.text[:30000])):
                        urls.append(resp.url)
                        break
                except Exception:
                    continue
        if not urls:
            try:
                sm = http.s.get(sitio.rstrip("/") + "/sitemap.xml", timeout=12).text
                urls += [u for u in re.findall(r"<loc>([^<]+)</loc>", sm) if CARRERA.search(urlparse(u).path)][:2]
            except Exception:
                pass
    if not urls:
        res["modo"] = "error:" + res["error_portada"] if res.get("error_portada") else "sin_pagina"
        return res
    best = None
    for u in urls[:4]:
        try:
            ev = evaluar_pagina(u, http)
        except Exception as e:
            ev = {"url": u, "error": type(e).__name__}
        if "error" in ev:
            best = best or ev
            continue
        rank = (ev["ofertas_con_patron"] >= 1 and bool(ev["plataforma"]) or ev["ofertas_con_patron"] >= 2, bool(ev["plataforma"]), ev["parece_empleo"], ev["enlaces"])
        if best is None or "error" in best or rank > best["_rank"]:
            best = {**ev, "_rank": rank}
        if ev["ofertas_con_patron"] >= 1 and ev["plataforma"] or ev["ofertas_con_patron"] >= 2:
            break
    if "error" in best:
        res.update({"modo": "error:" + best["error"], "empleo_url": best["url"]})
        return res
    best.pop("_rank")
    res.update(best)
    res["empleo_url"] = best.pop("url")
    if best["ofertas_con_patron"] >= 2 or best["ofertas_con_patron"] >= 1 and best["plataforma"] in PATRON_ATS:
        res["modo"] = "enlaces"
    elif best["parece_empleo"] or best["plataforma"]:
        res["modo"] = "cambio"
    else:
        res["modo"] = "dudoso"  # Claude decide mirando solo esta fila
    return res


def run(csvs: list[str], out: str, inseguro: bool = False, workers: int = 8) -> list[dict]:
    rows = []
    for c in csvs:
        with open(c, encoding="utf-8-sig", newline="") as f:
            rows += list(csv.DictReader(f))

    def one(row):
        http = Http(delay=0.5, timeout=15)
        if inseguro:  # sólo en redes con inspección TLS (PC del trabajo); en la nube no hace falta
            import urllib3

            urllib3.disable_warnings()
            http.s.verify = False
        try:
            return descubrir_uno(row, http)
        except Exception as e:
            return {"nombre": row.get("nombre"), "categoria": row.get("categoria"), "sitio": row.get("sitio"),
                    "modo": f"error:{type(e).__name__}"}

    with ThreadPoolExecutor(workers) as ex:  # sitios distintos: en paralelo no se satura a nadie
        res = list(ex.map(one, rows))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    c = Counter(r["modo"].split(":")[0] for r in res)
    log.info("descubrimiento: %s", dict(c))
    return res
