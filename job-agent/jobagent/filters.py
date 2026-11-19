"""Prefiltro barato (sin IA): descarta lo obvio y ordena para gastar Claude sólo en lo prometedor."""
from __future__ import annotations

from .models import Job, norm


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
        in_place = (
            j.remote and remote_ok
            or any(c in loc for c in cities)
            or j.country.upper() in ("BO",) and not cities
            or any(c in loc for c in countries)
        )
        if not in_place:
            continue
        s = 3.0 if j.source.startswith(("web:", "alerta:")) else 0.0
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
        else:
            by_fp[fp] = j
    return list(by_fp.values())
