"""Directorio de empleadores (embajadas, organismos, mineras, transnacionales).

- Los que tienen `empleo_url` los revisa el vigía a diario.
- Los que tienen `cubierto_por` ya llegan por otra fuente diaria (p. ej. Impactpool) y no se buscan aparte.
- El resto entra en una rotación: alta cada 2 días (el domingo se busca todo), media cada 3 días, baja cada 7, mensual cada 30.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

CADA = {"alta": 2, "media": 3, "baja": 7, "mensual": 30}


def load(root: Path, profile: dict) -> list[dict]:
    paths = profile.get("directorio", "config/directorio.yaml")
    out = []
    for p in [paths] if isinstance(paths, str) else paths:  # uno o varios archivos de directorio
        path = root / p
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for categoria, items in data.items():
            for it in items or []:
                out.append({**it, "categoria": categoria, "prioridad": it.get("prioridad", "media")})
    return out


def watch_pages(entries: list[dict]) -> list[dict]:
    return [{"name": e["nombre"], "url": e["empleo_url"], "org": e.get("org", e["nombre"]), "max_new": e.get("max_new", 10),
             "tipo": e.get("tipo"), "link_pattern": e.get("link_pattern")}
            for e in entries if e.get("empleo_url")]


def rotation(entries: list[dict], today: date | None = None) -> list[dict]:
    """Empleadores sin página vigilable que toca buscar hoy (determinista por fecha)."""
    today = today or date.today()
    pending = [e for e in entries if not e.get("empleo_url") and not e.get("cubierto_por")]
    picked = []
    for prio, every in CADA.items():
        tier = sorted((e for e in pending if e["prioridad"] == prio), key=lambda e: e["nombre"])
        picked += [e for i, e in enumerate(tier) if i % every == today.toordinal() % every]
    return picked


def everyone(entries: list[dict]) -> list[dict]:
    """Todo el directorio sin página vigilable ni agregador (corrida profunda), alta primero."""
    order = {"alta": 0, "media": 1, "baja": 2, "mensual": 3}
    pending = [e for e in entries if not e.get("empleo_url") and not e.get("cubierto_por")]
    return sorted(pending, key=lambda e: (order.get(e["prioridad"], 9), e["nombre"]))


def rotation_markdown(picked: list[dict], today: date | None = None) -> str:
    today = today or date.today()
    lines = [f"# Rotación de empleadores para hoy ({today})",
             f"{len(picked)} empleadores sin página de empleo vigilable. Busca convocatorias ABIERTAS de cada uno "
             "(agrupa 4-5 por búsqueda; los bancos y SAFI se pueden juntar en una sola con OR, p. ej. \"<empresa> Bolivia convocatoria OR vacante OR empleo 2026\"). "
             "Si un empleador ya no opera en Bolivia, anótalo en el informe para sacarlo del directorio.\n"]
    for cat in sorted({e["categoria"] for e in picked}):
        lines.append(f"## {cat}")
        if cat.startswith("internacional"):
            lines.append("Sede FUERA de Bolivia: busca SIN la palabra Bolivia (p. ej. \"<organismo> vacancies OR convocatoria "
                         "OR vacantes 2026 finance OR economist OR budget\"), y si tiene `empleo_url` ábrela. Sirven "
                         "puestos internacionales, de jóvenes profesionales y pasantías pagadas.")
        for e in (x for x in picked if x["categoria"] == cat):
            extra = f" — {e['nota']}" if e.get("nota") else ""
            ver = "" if e.get("verificado") == "si" or cat.startswith("internacional") else " (verificar que opere en Bolivia)"
            lines.append(f"- {e['nombre']} [{e['prioridad']}]{ver}{extra}")
    return "\n".join(lines) + "\n"
