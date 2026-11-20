"""Directorio de empleadores (embajadas, organismos, mineras, transnacionales).

- Los que tienen `empleo_url` los revisa el vigía a diario.
- Los que tienen `cubierto_por` ya llegan por otra fuente diaria (p. ej. Impactpool) y no se buscan aparte.
- El resto entra en una rotación: alta a diario, media cada 3 días, baja cada 7.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

CADA = {"alta": 1, "media": 3, "baja": 7}


def load(root: Path, profile: dict) -> list[dict]:
    path = root / profile.get("directorio", "config/directorio.yaml")
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
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


def rotation_markdown(picked: list[dict], today: date | None = None) -> str:
    today = today or date.today()
    lines = [f"# Rotación de empleadores para hoy ({today})",
             f"{len(picked)} empleadores sin página de empleo vigilable. Busca convocatorias ABIERTAS de cada uno "
             "(agrupa 3-4 por búsqueda, p. ej. \"<empresa> Bolivia convocatoria OR vacante OR empleo 2026\"). "
             "Si un empleador ya no opera en Bolivia, anótalo en el informe para sacarlo del directorio.\n"]
    for cat in sorted({e["categoria"] for e in picked}):
        lines.append(f"## {cat}")
        for e in (x for x in picked if x["categoria"] == cat):
            extra = f" — {e['nota']}" if e.get("nota") else ""
            ver = "" if e.get("verificado") == "si" else " (verificar que opere en Bolivia)"
            lines.append(f"- {e['nombre']} [{e['prioridad']}]{ver}{extra}")
    return "\n".join(lines) + "\n"
