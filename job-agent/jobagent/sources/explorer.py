"""Explorador web con Claude (reemplaza a "buscar en Google").

Claude usa su herramienta de búsqueda web (servidor de Anthropic, misma API key)
para encontrar convocatorias en sitios que no tienen API: organismos
internacionales, embajadas, cooperación, ONG, sector público y publicaciones
públicas de Facebook/LinkedIn indexadas por buscadores.

Anti-invención: sólo se aceptan ofertas cuya URL aparece literalmente en los
resultados de búsqueda que devolvió la herramienta. Después se comprueba que el
enlace siga respondiendo.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import anthropic

from ..http import Http, find_emails
from ..models import Job
from . import parse_iso

log = logging.getLogger(__name__)

DEFAULT_THEMES = {
    "organismos_internacionales": (
        "Agencias de la ONU en Bolivia (PNUD/UNDP, UNICEF, FAO, OIT, OPS/OMS, ONU Mujeres, PMA/WFP, ACNUR, OIM, UNFPA, "
        "UNODC), BID/IDB e IDB Invest, Banco Mundial/IFC, CAF, FONPLATA, Delegación de la Unión Europea. Busca vacantes "
        "y consultorías con sede en Bolivia o remotas abiertas a bolivianos (incluye unjobs, impactpool, untalent, "
        "jobs.undp.org, careers.un.org/Inspira)."
    ),
    "cooperacion_y_embajadas": (
        "Embajadas en La Paz (EE.UU., Reino Unido, Alemania, Francia, España, Suecia, Suiza, Canadá, Japón, Brasil, Países "
        "Bajos, Italia, Corea) y agencias de cooperación: GIZ, KfW, JICA, KOICA, AECID, COSUDE/Helvetas, Enabel, AFD, "
        "Global Affairs Canada. Convocatorias de empleo local, asistentes de programa, consultorías."
    ),
    "ong_y_fundaciones": (
        "ONG y fundaciones con oficinas en Bolivia: Save the Children, Plan International, CARE, Visión Mundial, "
        "Ayuda en Acción, Oxfam, Educo, Swisscontact, WWF, WCS, Conservación Internacional, Hivos, Solidar Suiza, "
        "Fundación Jubileo, CIPCA, Fundación Milenio, CEDLA, ProMujer, FUNDAPRO. También devex.com y idealist."
    ),
    "sector_publico_y_financiero": (
        "Convocatorias públicas en Bolivia: ministerios (en especial Economía y Finanzas Públicas, Planificación), "
        "Banco Central de Bolivia, ASFI, APS, INE, Aduana, Impuestos Nacionales, YPFB, BDP, Banco Unión, gobiernos "
        "municipales y departamentales; consultorías individuales de línea publicadas en SICOES (sicoes.gob.bo) o en "
        "los sitios de cada entidad. También bancos privados y microfinancieras."
    ),
    "redes_sociales_publicas": (
        "Publicaciones PÚBLICAS indexadas en buscadores con convocatorias: site:facebook.com (páginas y grupos públicos "
        "de empleo en La Paz/Bolivia, páginas de empresas e instituciones) y site:linkedin.com/posts (reclutadores y "
        "organizaciones anunciando vacantes). Sólo lo que aparezca en los resultados de búsqueda."
    ),
    "remoto_usd_eur": (
        "Empleos REMOTOS pagados en USD/EUR abiertos a candidatos en Bolivia/LatAm para finanzas: FP&A, financial "
        "analyst, budget analyst, business analyst, finance operations. Empresas que contratan en LatAm vía Deel/"
        "Remote.com, startups, consultoras y organismos con trabajo remoto. Incluye Workana/Upwork solo si es un "
        "proyecto sustancial de análisis financiero."
    ),
    "cooperacion_francofona_y_europea": (
        "Organizaciones francófonas y europeas con presencia en Bolivia o la región donde el francés/inglés C1 es "
        "ventaja: AFD, Enabel (Bélgica), Embajadas de Francia y Bélgica, Alianza Francesa, Unión Europea, Expertise "
        "France, IRD, Médicos del Mundo, Handicap International, OCDE, y programas de la UE en LatAm (EUROsociAL, "
        "que trabaja finanzas públicas y fiscalidad)."
    ),
    "busqueda_general": (
        "Búsqueda general tipo Google de los cargos objetivo del candidato + 'convocatoria', 'vacancia', 'se busca', "
        "'trabaja con nosotros' en Bolivia, priorizando lo publicado en los últimos 15 días."
    ),
}

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "organization": {"type": "string"},
                    "location": {"type": "string"},
                    "remote": {"type": "boolean"},
                    "posted_date": {"type": "string", "description": "YYYY-MM-DD o vacío si no se sabe"},
                    "deadline": {"type": "string", "description": "YYYY-MM-DD o vacío"},
                    "description": {"type": "string", "description": "Requisitos y funciones según la fuente"},
                    "contact_email": {"type": "string"},
                },
                "required": ["url", "title", "organization", "location", "remote", "posted_date", "deadline",
                             "description", "contact_email"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["jobs"],
    "additionalProperties": False,
}


def _norm_url(u: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", re.sub(r"[#?].*$", "", u.strip())).rstrip("/").lower()


def _search_urls(content) -> set[str]:
    urls = set()
    for b in content:
        if getattr(b, "type", "") == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
            for r in b.content:
                if getattr(r, "url", None):
                    urls.add(_norm_url(r.url))
    return urls


def _prompt(theme: str, profile: dict, today: str) -> str:
    roles = ", ".join(r for r in profile.get("roles_objetivo", []) if "COMPLETAR" not in r) or ", ".join(profile.get("keywords", []))
    return (
        f"Hoy es {today}. Eres un headhunter en La Paz, Bolivia. Busca en la web convocatorias de empleo o consultoría "
        f"ABIERTAS (plazo no vencido) relevantes para un candidato que busca: {roles}. "
        f"Palabras clave: {', '.join(profile.get('keywords', []))}. Ciudades: {', '.join(profile.get('ciudades', []))}; "
        f"acepta remoto: {profile.get('acepta_remoto', True)}.\n\n"
        f"Ámbito de esta búsqueda: {theme}\n\n"
        "Haz varias búsquedas distintas y específicas (en español e inglés). Devuelve SOLO convocatorias concretas "
        "(un puesto, no la página general de empleos), cuya URL viste en los resultados de búsqueda; nunca inventes ni "
        "construyas URLs. Si una convocatoria ya cerró o no puedes ver su fecha y parece antigua (antes de este año), "
        "no la incluyas. Si no encuentras nada, devuelve una lista vacía."
    )


def _run(client, model: str, prompt: str, max_searches: int):
    tools = [{
        "type": "web_search_20260209", "name": "web_search", "max_uses": max_searches,
        "user_location": {"type": "approximate", "city": "La Paz", "country": "BO", "timezone": "America/La_Paz"},
    }]
    messages = [{"role": "user", "content": prompt}]
    content_all = []
    resp = None
    for _ in range(4):  # reanuda pause_turn como máximo 3 veces
        kwargs = dict(model=model, max_tokens=16000, tools=tools, messages=messages,
                      output_config={"effort": "medium", "format": {"type": "json_schema", "schema": RESULT_SCHEMA}})
        if model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable")):
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
        content_all += list(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": resp.content}]
    return resp, content_all


def explore(themes: dict[str, str], profile: dict, model: str, max_searches: int) -> list[tuple[str, dict]]:
    client = anthropic.Anthropic()
    today = datetime.now().date().isoformat()
    found: list[tuple[str, dict]] = []
    for name, theme in themes.items():
        try:
            resp, content = _run(client, model, _prompt(theme, profile, today), max_searches)
        except anthropic.APIStatusError as e:
            log.error("explorador '%s': error de API %s: %s", name, e.status_code, e.message)
            continue
        except anthropic.APIConnectionError as e:
            log.error("explorador: sin conexión a Claude: %s", e)
            break
        if resp.stop_reason == "refusal":
            log.warning("explorador '%s': rechazado", name)
            continue
        seen_urls = _search_urls(content)
        text = next((b.text for b in reversed(resp.content) if getattr(b, "type", "") == "text"), "")
        try:
            items = json.loads(text).get("jobs", [])
        except json.JSONDecodeError:
            log.warning("explorador '%s': respuesta no es JSON", name)
            continue
        ok = [it for it in items if _norm_url(it["url"]) in seen_urls]
        log.info("explorador '%s': %d propuestas, %d con URL verificada en resultados de búsqueda (%d búsquedas)",
                 name, len(items), len(ok), sum(1 for b in content if getattr(b, "type", "") == "server_tool_use"))
        found += [(name, it) for it in ok]
    return found


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    import os

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        log.info("explorador: sin ANTHROPIC_API_KEY, se omite")
        return []
    themes = {k: v for k, v in DEFAULT_THEMES.items() if k in src.get("themes", DEFAULT_THEMES)}
    themes.update(src.get("extra_themes") or {})
    model = src.get("model") or profile.get("agente", {}).get("modelo", "claude-opus-5-5")
    jobs: list[Job] = []
    for theme, it in explore(themes, profile, model, src.get("max_searches_per_theme", 5)):
        if is_seen(it["url"]):
            continue
        # El enlace debe seguir vivo (404/410 => convocatoria retirada)
        alive = True
        try:
            r = http.s.get(it["url"], timeout=20, allow_redirects=True)
            alive = r.status_code < 400 or r.status_code in (401, 403, 429, 999)  # 403/999: anti-bot, no prueba que no exista
        except Exception:
            pass  # sin red hacia ese sitio: no se puede comprobar, no se descarta
        if not alive:
            log.info("explorador: enlace muerto, descartado: %s", it["url"])
            continue
        desc = it.get("description", "")
        jobs.append(Job(
            source=f"web:{theme}", url=it["url"], title=it["title"], company=it["organization"],
            location=it["location"], country="BO" if "bolivia" in it["location"].lower() or "la paz" in it["location"].lower() else "",
            remote=it["remote"], posted_at=parse_iso(it["posted_date"] or None),
            valid_through=parse_iso((it["deadline"] + "T23:59:59") if it["deadline"] else None),
            description=desc, apply_emails=[e for e in [it.get("contact_email", "").lower()] if "@" in e] or find_emails(desc),
            apply_url=it["url"], flags=["url_en_resultados_busqueda"],
        ))
    return jobs
