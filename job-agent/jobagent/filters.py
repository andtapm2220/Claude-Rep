"""Prefiltro barato (sin IA): descarta lo obvio y ordena para gastar Claude sólo en lo prometedor."""
from __future__ import annotations

import re

from .models import Job, norm


# Fuentes ya seleccionadas para el perfil (o institucionales): no se descartan por ubicación ni palabras clave
CURATED = ("web:", "alerta:", "vigia:", "pnud", "reliefweb", "manual")


def prefilter(jobs: list[Job], profile: dict) -> list[Job]:
    excl = [norm(x) for x in profile.get("excluir_titulo", [])]
    kws = [norm(k) for k in profile.get("keywords", [])]
    roles = [norm(r) for r in profile.get("roles_objetivo", []) if "completar" not in norm(r)]
    cities = [norm(c) for c in profile.get("ciudades", [])]
    countries = [norm(c) for c in profile.get("paises_region", [])]
    remote_ok = profile.get("acepta_remoto", True)
    max_age = profile.get("agente", {}).get("max_antiguedad_dias", 21)

    kept = []
    for j in jobs:
        title, desc = norm(j.title), norm(j.description)
        if any(e and e in title for e in excl):
            continue
        age = j.age_days()
        if age is not None and age > max_age:
            continue
        loc = norm(f"{j.location} {j.country}")
        curated = j.source.startswith(CURATED)
        in_place = curated or (
            j.remote and remote_ok
            or any(c in loc for c in cities)
            or j.country.upper() in ("BO",) and not cities
            or any(c in loc for c in countries)
        )
        if not in_place:
            continue
        s = 3.0 if curated else 0.0
        for r in roles:
            if r in title:
                s += 6
            elif all(w in title for w in r.split() if len(w) > 3):
                s += 3
        for k in kws:
            if k in title:
                s += 3
            elif k in desc:
                s += 1
        if age is not None:
            s += max(0, 2 - age / 7)  # pequeño bonus a lo reciente
        j.prefilter_score = s
        if s > 0 or not kws:
            kept.append(j)
    kept.sort(key=lambda j: j.prefilter_score, reverse=True)
    return kept


def merge_duplicates(jobs: list[Job]) -> list[Job]:
    """La misma oferta publicada en varios portales => una sola, con 'also_on' (y más confianza)."""
    by_fp: dict[str, Job] = {}
    for j in jobs:
        fp = j.fingerprint
        if fp in by_fp and fp.split("|")[0]:
            main = by_fp[fp]
            if j.source not in main.also_on and j.source != main.source:
                main.also_on.append(j.source)
            if len(j.description) > len(main.description):
                main.description = j.description
            main.apply_emails = list(dict.fromkeys(main.apply_emails + j.apply_emails))
        else:  # sin empresa no se puede saber si es la misma oferta: se conserva aparte (antes se pisaba)
            by_fp[fp if fp.split("|")[0] else fp + "|" + j.url] = j
    return list(by_fp.values())


def select_candidates(ranked: list[Job], total: int = 40, max_curated: int = 15) -> list[Job]:
    """Cupos para que ninguna fuente acapare la evaluación: primero lo que trajo la búsqueda web (ya elegido
    para el perfil), luego portales y LinkedIn, y del vigía/PNUD/alertas como máximo la mitad de las plazas
    (o `max_curated`). Si los portales no llenan su parte, el vigía completa el resto."""
    web = [j for j in ranked if j.source.startswith("web:")]
    curated_all = [j for j in ranked if j.source.startswith(CURATED) and not j.source.startswith("web:")]
    boards = [j for j in ranked if not j.source.startswith(CURATED)]
    out = web[:total]
    cap = min(max_curated, max(1, total // 2))
    curated = curated_all[:cap]
    out += boards[: max(0, total - len(out) - len(curated))]
    out += curated[: max(0, total - len(out))]
    out += curated_all[cap: cap + max(0, total - len(out))]  # rellena si sobran plazas
    return out


# Requisito de título: en las convocatorias bolivianas la "formación académica" es eliminatoria (cumple / no cumple).
# Si la oferta sólo nombra carreras ajenas (p. ej. "Ingeniería de Sistemas o Informática"), no vale gastar Claude en ella.
TITULO_VENTANA = re.compile(
    r"(formacion academica|formacion profesional|titulo (?:en provision nacional|profesional|universitario|a nivel)|"
    r"licenciatura en|licenciado en|grado academico|profesional (?:titulado |universitario )?en|degree in)(.{0,300})")
TITULO_AJENO = re.compile(
    r"sistemas|informatica|electronica|telecomunicaciones|ingenieria civil|mecanica|electrica|quimica|petrolera|"
    r"minas|geolog|agronom|medicina|enfermeria|bioquimica|farmac|odontolog|derecho|abogad|arquitectura|psicolog|"
    r"comunicacion social|trabajo social|veterinari|ambiental|computer science|software")


def titulo_no_cumple(text: str, propios: list[str]) -> bool:
    """True si la oferta pide títulos y NINGUNO es de la familia de Fernando (economía, finanzas, administración...)."""
    t = norm(text)
    ventanas = [m.group(2) for m in TITULO_VENTANA.finditer(t)]
    if not ventanas:
        return False
    own = [norm(p) for p in propios]
    if any(p in v for v in ventanas for p in own):
        return False
    return any(TITULO_AJENO.search(v) for v in ventanas)
