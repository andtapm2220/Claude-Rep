"""Módulo "pituto" semanal: cómo llegar a empleos que nunca se publican.

En Latinoamérica ~70% de la gente se entera de vacantes por contactos (BID). Cada
lunes Claude busca en la web señales de contratación que vienen ANTES de la
convocatoria: préstamos y proyectos nuevos del BID/Banco Mundial/CAF con Bolivia,
programas de cooperación recién aprobados, empresas que se expanden, nuevas
autoridades. De ahí propone 5 organizaciones, a qué perfil de persona escribirle,
una búsqueda de LinkedIn (enlace, no scraping) y un mensaje listo para enviar.
"""
from __future__ import annotations

import html
import json
import logging
from datetime import datetime
from urllib.parse import quote

import anthropic

from .sources.explorer import _norm_url, _search_urls

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "targets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "organization": {"type": "string"},
                    "signal": {"type": "string", "description": "Qué pasó y por qué implica contratación próxima"},
                    "source_url": {"type": "string"},
                    "fit": {"type": "string", "description": "Por qué encaja con el candidato, citando su CV"},
                    "who_to_contact": {"type": "string", "description": "Cargo/rol de la persona a contactar"},
                    "linkedin_search": {"type": "string", "description": "Palabras para buscar a esa persona en LinkedIn"},
                    "message": {"type": "string", "description": "Mensaje breve (≤600 caracteres) para LinkedIn o email"},
                },
                "required": ["organization", "signal", "source_url", "fit", "who_to_contact", "linkedin_search", "message"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["targets"],
    "additionalProperties": False,
}


def weekly_targets(profile: dict, cv: str, model: str, max_searches: int = 8) -> list[dict]:
    client = anthropic.Anthropic()
    today = datetime.now().date().isoformat()
    prompt = (
        f"Hoy es {today}. Eres un headhunter senior en La Paz. Tu tarea NO es buscar convocatorias publicadas, sino "
        "SEÑALES de contratación próximas en Bolivia de las últimas 4-6 semanas, para que el candidato llegue antes por "
        "contactos: préstamos o proyectos nuevos aprobados del BID, Banco Mundial, CAF, FONPLATA con Bolivia (generan "
        "unidades ejecutoras y consultorías), programas de cooperación nuevos (UE, GIZ, AFD, JICA, KOICA, AECID, "
        "Enabel, COSUDE), ONG que ganaron fondos, bancos/microfinancieras o empresas que se expanden, fondos de "
        "inversión de impacto, cambios de autoridades en entidades públicas económicas. "
        "Elige las 5 organizaciones donde el perfil del candidato tenga más ventaja y, para cada una, di a quién "
        "escribirle (cargo, no nombres inventados), qué buscar en LinkedIn para encontrarlo y redacta un mensaje "
        "corto, natural y específico (sin pedir trabajo de forma directa en el primer mensaje: pedir una conversación "
        "breve, mencionando la señal y un logro concreto del CV). source_url debe ser una URL que viste en los "
        f"resultados de búsqueda.\n\n<perfil>{json.dumps({k: v for k, v in profile.items() if k not in ('agente', 'fuentes')}, ensure_ascii=False)}</perfil>\n<cv>{cv}</cv>"
    )
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches,
              "user_location": {"type": "approximate", "city": "La Paz", "country": "BO", "timezone": "America/La_Paz"}}]
    kwargs = dict(model=model, max_tokens=16000, tools=tools, messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}})
    content = []
    for _ in range(4):
        if model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable")):
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            resp = client.messages.create(**kwargs)
        content += list(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        kwargs["messages"] = [kwargs["messages"][0], {"role": "assistant", "content": resp.content}]
    if resp.stop_reason == "refusal":
        log.warning("networking: rechazado")
        return []
    text = next((b.text for b in reversed(resp.content) if getattr(b, "type", "") == "text"), "{}")
    targets = json.loads(text).get("targets", [])
    seen = _search_urls(content)
    for t in targets:  # marca si la fuente no salió de la búsqueda real
        t["verified_source"] = _norm_url(t["source_url"]) in seen
    return targets


def format_message(targets: list[dict]) -> list[str]:
    e = html.escape
    out = [f"🤝 <b>Pituto inteligente — semana del {datetime.now().date()}</b>\n"
           "Organizaciones con señales de contratación próxima donde tu perfil tiene ventaja. "
           "Escríbeles ANTES de que publiquen la convocatoria."]
    for i, t in enumerate(targets, 1):
        li = "https://www.linkedin.com/search/results/people/?keywords=" + quote(t["linkedin_search"])
        src = f'<a href="{e(t["source_url"])}">fuente</a>' + ("" if t.get("verified_source") else " (⚠️ no verificada)")
        out.append(
            f"<b>{i}. {e(t['organization'])}</b>\n📡 {e(t['signal'])} ({src})\n🎯 {e(t['fit'])}\n"
            f"👤 Contactar: {e(t['who_to_contact'])} — <a href=\"{li}\">buscar en LinkedIn</a>\n"
            f"✍️ Mensaje sugerido:\n<i>{e(t['message'])}</i>"
        )
    return out
