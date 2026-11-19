"""Puntúa cada oferta contra tu perfil y CV con Claude, y redacta cartas para las mejores."""
from __future__ import annotations

import json
import logging

import anthropic

from .models import Job

log = logging.getLogger(__name__)
BATCH = 8

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "score": {"type": "integer", "description": "0-100 encaje real con el candidato"},
                    "verdict": {"type": "string", "enum": ["postular_ya", "vale_la_pena", "parcial", "descartar"]},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                    "gaps": {"type": "array", "items": {"type": "string"}},
                    "red_flags": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
                "required": ["id", "score", "verdict", "reasons", "gaps", "red_flags", "summary"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

LETTER_SCHEMA = {
    "type": "object",
    "properties": {
        "email_subject": {"type": "string"},
        "cover_letter": {"type": "string"},
        "cv_highlights": {"type": "array", "items": {"type": "string"}},
        "employer_type": {"type": "string", "enum": ["sector_publico", "organismo_internacional", "ong_cooperacion",
                                                      "banca_finanzas", "empresa_privada", "remoto_extranjero"]},
        "checklist": {"type": "array", "items": {"type": "string"},
                      "description": "Pasos y documentos concretos para postular a ESTA convocatoria"},
        "letter_language": {"type": "string", "enum": ["es", "en", "fr"]},
    },
    "required": ["email_subject", "cover_letter", "cv_highlights", "employer_type", "checklist", "letter_language"],
    "additionalProperties": False,
}


def _system(profile: dict, cv: str) -> list[dict]:
    prof = {k: v for k, v in profile.items() if k not in ("agente", "fuentes")}
    text = (
        "Eres un reclutador senior en Bolivia y Latinoamérica que evalúa ofertas de trabajo "
        "para UN candidato concreto. Eres honesto y exigente: un 80+ significa que el candidato "
        "cumple casi todos los requisitos y la oferta coincide con lo que busca; 60-79 vale la pena; "
        "40-59 encaje parcial; menos de 40 no encaja. No infles puntajes.\n\n"
        "Para cada oferta da: score, verdict, reasons (por qué encaja, citando requisitos concretos "
        "de la oferta y experiencia concreta del CV), gaps (requisitos que el candidato no cumple), "
        "red_flags (señales de que la oferta podría ser falsa, una estafa, un 'ghost job', o tener "
        "condiciones problemáticas: pide dinero, comisiones sin sueldo, datos vagos, empresa "
        "inexistente, contacto sólo por WhatsApp personal, etc.; lista vacía si no hay) y summary "
        "(1-2 frases en español: qué es el puesto y por qué le conviene o no).\n"
        "Respeta estrictamente las preferencias y deal-breakers del candidato.\n\n"
        f"<perfil>\n{json.dumps(prof, ensure_ascii=False, indent=1)}\n</perfil>\n\n<cv>\n{cv}\n</cv>"
    )
    # Perfil+CV es idéntico en todas las llamadas del día: se cachea.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _job_block(j: Job) -> str:
    return (
        f"<oferta id=\"{j.key}\">\nCargo: {j.title}\nEmpresa: {j.company or '(no indicada)'}\n"
        f"Ubicación: {j.location} {'(remoto)' if j.remote else ''}\nSalario: {j.salary or '(no indicado)'}\n"
        f"Publicada: {j.posted_at.date() if j.posted_at else '?'}\nPortal: {j.source}\n"
        f"Descripción:\n{j.description[:6000]}\n</oferta>"
    )


def _call(client: anthropic.Anthropic, model: str, system, user: str, schema: dict, max_tokens: int) -> dict | None:
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )
    if model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable")):
        # Si un clasificador de seguridad rechaza la petición, la API reintenta con otro modelo.
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        resp = client.beta.messages.create(**kwargs)
    else:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        log.warning("Claude rechazó la petición: %s", getattr(resp, "stop_details", None))
        return None
    if resp.stop_reason == "max_tokens":
        log.warning("Respuesta truncada (max_tokens)")
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    u = resp.usage
    log.info("tokens in=%s cache_read=%s out=%s", u.input_tokens, getattr(u, "cache_read_input_tokens", 0), u.output_tokens)
    return json.loads(text)


def score_jobs(jobs: list[Job], profile: dict, cv: str, model: str) -> list[Job]:
    client = anthropic.Anthropic()
    system = _system(profile, cv)
    by_key = {j.key: j for j in jobs}
    for i in range(0, len(jobs), BATCH):
        chunk = jobs[i : i + BATCH]
        user = "Evalúa estas ofertas para el candidato. Devuelve un resultado por cada id.\n\n" + "\n\n".join(
            _job_block(j) for j in chunk
        )
        try:
            out = _call(client, model, system, user, SCORE_SCHEMA, 16000)
        except anthropic.RateLimitError as e:
            log.error("Rate limit de Claude, se detiene el puntaje: %s", e)
            break
        except anthropic.APIStatusError as e:
            log.error("Error de API (%s) en lote %d: %s", e.status_code, i // BATCH, e.message)
            continue
        except anthropic.APIConnectionError as e:
            log.error("Sin conexión a la API de Claude: %s", e)
            break
        for r in (out or {}).get("results", []):
            j = by_key.get(r["id"])
            if j:
                j.score, j.verdict = max(0, min(100, r["score"])), r["verdict"]
                j.reasons, j.gaps, j.red_flags, j.summary = r["reasons"], r["gaps"], r["red_flags"], r["summary"]
                if j.red_flags:
                    j.trust = max(0, j.trust - 10 * len(j.red_flags))
    return jobs


def draft_application(job: Job, profile: dict, cv: str, model: str) -> dict | None:
    client = anthropic.Anthropic()
    user = (
        "Redacta la postulación del candidato a esta oferta, en español profesional boliviano, "
        "sin inventar experiencia que no esté en el CV. cover_letter: 180-260 palabras, lista para "
        "pegar en un email (saludo, por qué encaja con 2-3 logros concretos del CV conectados a "
        "requisitos de la oferta, cierre con disponibilidad). email_subject: corto e incluye el cargo. "
        "cv_highlights: 3-5 viñetas del CV que conviene destacar/mover arriba para esta oferta. "
        "Escribe la carta en el idioma de la convocatoria (letter_language). "
        "Clasifica employer_type y arma checklist según cómo se postula realmente en Bolivia: "
        "sector_publico -> formulario/hoja de vida en el formato de la entidad, FIRMADA (sin firma descalifica), "
        "fotocopias de respaldo de experiencia general y específica, título en provisión nacional, declaración jurada, "
        "CI, sobre cerrado o SICOES si aplica, respetar el plazo exacto; organismo_internacional -> registro en su "
        "portal (Quantum/PNUD, Inspira/ONU, ERA/EE.UU., Workday/BID), formato P11/CV propio, 'experiencia específica' "
        "medida en años, referencias; ong_cooperacion -> CV de máximo 3 páginas, carta con pretensión salarial, 3 "
        "referencias, propuesta técnica/económica si es consultoría por producto; banca_finanzas / empresa_privada -> "
        "CV de 1-2 páginas con logros cuantificados, LinkedIn actualizado, pretensión salarial si la piden; "
        "remoto_extranjero -> CV en inglés, LinkedIn en inglés, disponibilidad horaria, forma de cobro (Deel/Payoneer). "
        "Incluye en el checklist cualquier requisito específico que aparezca en la oferta (fecha límite, código, "
        "documentos). No inventes requisitos que la oferta contradiga.\n\n"
        + _job_block(job)
    )
    try:
        return _call(client, model, _system(profile, cv), user, LETTER_SCHEMA, 16000)
    except anthropic.APIError as e:
        log.error("No se pudo redactar carta para %s: %s", job.title, e)
        return None
