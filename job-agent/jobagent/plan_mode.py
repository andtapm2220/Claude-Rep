"""Modo "plan de Claude": sin API key.

El código hace lo mecánico (recolectar, verificar, prefiltrar, recordar lo visto) y
Claude, dentro de una sesión programada de Claude Code que usa el plan del usuario,
hace lo inteligente (búsqueda web, puntaje, cartas, notificación, planilla).

  1. Claude busca en la web y guarda hallazgos en state/web_jobs.json   (opcional)
  2. python -m jobagent collect   -> state/pending.json + output/candidatas.md
  3. Claude lee output/candidatas.md + CV y escribe state/scores.json
  4. python -m jobagent publish   -> output/ofertas_<fecha>.md, output/sheet_rows.json,
                                     marca todo como visto en state/jobs.db
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .filters import merge_duplicates, prefilter, select_candidates
from .http import Http, find_emails
from .models import Job, job_from_dict, job_to_dict
from .sources import all_fetchers, parse_iso
from .store import Store
from .verify import verify

log = logging.getLogger(__name__)


def _web_jobs(path: Path, http: Http, is_seen) -> list[Job]:
    """Hallazgos de la búsqueda web que hizo Claude en la sesión."""
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("web_jobs.json inválido, se ignora")
        return []
    jobs = []
    for it in items:
        url = it.get("url", "")
        if not url.startswith("http") or is_seen(url):
            continue
        try:  # enlace muerto (404/410) => convocatoria retirada o inventada
            r = http.s.get(url, timeout=20, allow_redirects=True)
            if r.status_code in (404, 410):
                log.info("web: enlace muerto, descartado: %s", url)
                continue
        except Exception:
            pass
        desc = it.get("description", "")
        jobs.append(Job(
            source=f"web:{it.get('theme', 'busqueda')}", url=url, title=it.get("title", "")[:200],
            company=it.get("organization", ""), location=it.get("location", ""),
            country="BO" if "bolivia" in (it.get("location", "") or "").lower() else "",
            remote=bool(it.get("remote")), posted_at=parse_iso(it.get("posted_date") or None),
            valid_through=parse_iso((it["deadline"] + "T23:59:59") if it.get("deadline") else None),
            description=desc, apply_emails=find_emails(desc + " " + it.get("contact_email", "")),
            apply_url=url, flags=["url_en_resultados_busqueda"],
        ))
    return jobs


def collect(root: Path, profile: dict, limit_sources: int = 0, max_cands: int | None = None) -> dict:
    agent = profile.get("agente", {})
    store = Store(root / "state/jobs.db")
    http = Http()
    found: list[Job] = []
    stats: dict[str, int | str] = {}
    for name, fetch in all_fetchers().items():
        src = (profile.get("fuentes") or {}).get(name, {})
        if not src.get("enabled", False) or name == "explorador_web":  # la búsqueda web la hace Claude en la sesión
            continue
        if limit_sources:
            src = {**src, "max_pages": 1, "max_details": limit_sources}
        try:
            jobs = fetch(src, profile, http, store.is_seen)
            stats[name] = len(jobs)
            found += jobs
        except Exception as e:
            log.exception("Fuente %s falló", name)
            stats[name] = f"error: {type(e).__name__}"
    web = _web_jobs(root / "state/web_jobs.json", http, store.is_seen)
    stats["busqueda_web_claude"] = len(web)
    found = merge_duplicates(found + web)
    for j in found:
        verify(j, max_age_days=agent.get("max_antiguedad_dias", 21))
    ranked = [j for j in prefilter(found, profile) if "vencida" not in j.flags]
    total = max_cands or agent.get("max_para_claude", 40)
    # Validación OBLIGATORIA de vigencia: se abre la página real de cada candidata
    from .validate import validate

    pool = select_candidates(ranked, int(total * 1.6) + 2, min(agent.get("max_vigia", 15), total))
    from .filters import titulo_no_cumple

    propios = profile.get("titulos_propios", [])
    cands, cerradas, sin_titulo = [], 0, []
    for j in pool:
        if len(cands) >= total:
            break
        if propios and titulo_no_cumple(f"{j.title}\n{j.description}", propios):
            j.flags.append("no_cumple_titulo")  # eliminatorio en Bolivia: no se gasta Claude en ella
            sin_titulo.append(j)
            continue
        if validate(j, http, max_age_days=agent.get("max_antiguedad_dias", 21)) == "cerrada":
            cerradas += 1
            continue
        cands.append(j)
    stats["descartadas_por_cerradas"] = cerradas
    stats["descartadas_por_titulo"] = len(sin_titulo)
    cand_keys = {j.key for j in cands}

    (root / "state").mkdir(exist_ok=True)
    (root / "state/pending.json").write_text(json.dumps({
        "stats": stats, "found": [job_to_dict(j) for j in found], "candidates": sorted(cand_keys),
    }, ensure_ascii=False), encoding="utf-8")

    lines = [f"# Candidatas {datetime.now().date()} — {len(cands)} de {len(found)} nuevas",
             "Puntúa cada una (id) contra el perfil y CV. Señales de verificación entre corchetes.\n"]
    for j in cands:
        lines.append(
            f"## id: {j.key}\n**{j.title}** — {j.company or '(empresa no indicada)'} · {j.location}"
            f"{' · remoto' if j.remote else ''} · {j.salary}\n"
            f"Vigencia verificada: {next((f.split(':',1)[1] for f in j.flags if f.startswith('vigencia:')), '?').upper()} · "
            f"Publicada: {j.posted_at.date() if j.posted_at else '?'} · Cierra: {j.valid_through.date() if j.valid_through else '?'}"
            f" · Fuente: {j.source} · Confianza: {j.trust} [{', '.join(j.flags)}]\n{j.url}\n\n{j.description[:1800]}\n")
    if sin_titulo:
        lines.append("## Descartadas por título (piden otra carrera; no las puntúes)")
        lines += [f"- {j.title} — {j.company} · {j.url}" for j in sin_titulo]
    (root / "output").mkdir(exist_ok=True)
    (root / "output/candidatas.md").write_text("\n".join(lines), encoding="utf-8")
    summary = {"nuevas": len(found), "candidatas": len(cands), "por_fuente": stats}
    log.info("collect: %s", summary)
    return summary


def publish(root: Path, profile: dict, parcial: bool = False) -> dict:
    """parcial=True: guarda solo lo ya puntuado y deja el resto pendiente (corridas largas que pueden cortarse)."""
    agent = profile.get("agente", {})
    pending = json.loads((root / "state/pending.json").read_text(encoding="utf-8"))
    scores = {s["id"]: s for s in json.loads((root / "state/scores.json").read_text(encoding="utf-8"))}
    found = [job_from_dict(d) for d in pending["found"]]
    cand = set(pending["candidates"])
    for j in found:
        s = scores.get(j.key)
        if s:
            j.score, j.verdict = int(s["score"]), s.get("verdict", "")
            j.reasons, j.gaps = s.get("reasons", []), s.get("gaps", [])
            j.red_flags, j.summary = s.get("red_flags", []), s.get("summary", "")
            if j.red_flags:
                j.trust = max(0, j.trust - 10 * len(j.red_flags))
    min_score, min_trust = agent.get("puntaje_minimo", 65), agent.get("confianza_minima", 50)
    from .validate import status_of

    # Solo se recomienda lo que el validador confirmó ABIERTO en la página real
    picks = sorted([j for j in found if j.score is not None and j.score >= min_score and j.trust >= min_trust
                    and status_of(j) == "abierta"
                    and j.verdict != "descartar"], key=lambda j: (j.score, j.trust), reverse=True)

    store = Store(root / "state/jobs.db")
    pick_keys = {j.key for j in picks}
    for j in found:
        if j.key in cand and j.score is None:
            continue  # candidata sin puntaje: se reintenta después
        if parcial and j.score is None:
            continue  # en modo parcial, las no candidatas se guardan al final
        store.save(j, status="notificado" if j.key in pick_keys else "visto")
    store.kv_set("last_run", datetime.now(timezone.utc).isoformat())
    store.commit()

    today = datetime.now().date().isoformat()
    md = [f"# Ofertas recomendadas {today}", f"{len(picks)} recomendadas de {len(found)} nuevas. "
          f"Fuentes: " + ", ".join(f"{k}: {v}" for k, v in pending["stats"].items()) + "\n"]
    rows = []
    for i, j in enumerate(picks, 1):
        md.append(f"## {i}. {j.title} — {j.company}\n🎯 {j.score}/100 · {j.verdict} · 🛡️ confianza {j.trust} · "
                  f"📍 {j.location}{' (remoto)' if j.remote else ''}"
                  f"{' · ⏳ cierra ' + str(j.valid_through.date()) if j.valid_through else ''}\n\n{j.summary}\n"
                  + "".join(f"- ✅ {r}\n" for r in j.reasons[:3]) + "".join(f"- ⚠️ {g}\n" for g in j.gaps[:2])
                  + (f"- 🚩 {'; '.join(j.red_flags)}\n" if j.red_flags else "")
                  + (f"- ✉️ Postular a: {', '.join(j.apply_emails)}\n" if j.apply_emails else "")
                  + f"- 🔗 {j.url}\n")
    # Las CERRADAS (incluye fantasmas) no van a la planilla, y las SIN VERIFICAR solo si valen 60 o más:
    # el resto ensucia la lista y verificarlas a mano gasta tokens (decisión de Fernando, 25-11)
    def to_sheet(x):
        st = status_of(x)
        return st != "cerrada" and (st == "abierta" or x.score >= 60)
    for j in [x for x in found if x.score is not None and x.score >= 40 and to_sheet(x)]:
        rows.append([today, j.score, j.verdict, j.trust, j.title, j.company, j.location, "sí" if j.remote else "no",
                     j.salary, j.valid_through.date().isoformat() if j.valid_through else "", j.source,
                     ", ".join(j.apply_emails), j.summary, j.url,
                     {"abierta": "nuevo", "cerrada": "CERRADA"}.get(
                         status_of(j), "SIN VERIFICAR: revisar plazo antes de postular")])
    (root / "output").mkdir(exist_ok=True)
    mode = "a" if parcial else "w"
    with open(root / f"output/ofertas_{today}.md", mode, encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    (root / "output/sheet_rows.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    if parcial:
        done = {j.key for j in found if j.score is not None}
        pending["found"] = [d for d, j in zip(pending["found"], found) if j.key not in done]
        pending["candidates"] = [k for k in pending["candidates"] if k not in done]
        (root / "state/pending.json").write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
        (root / "state/scores.json").unlink(missing_ok=True)
    else:
        for f in ("pending.json", "scores.json", "web_jobs.json"):
            (root / "state" / f).unlink(missing_ok=True)
    top = [{"titulo": j.title, "empresa": j.company, "puntaje": j.score} for j in picks[:3]]
    summary = {"recomendadas": len(picks), "nuevas": len(found), "top": top, "parcial": parcial,
               "pendientes": len(pending["candidates"]) if parcial else 0,
               "resumen": f"output/ofertas_{today}.md", "filas_planilla": len(rows)}
    log.info("publish: %s", summary)
    return summary


SHEET_HEADER = ["Fecha", "Puntaje", "Veredicto", "Confianza", "Cargo", "Organización", "Ubicación", "Remoto",
                "Salario", "Cierra", "Fuente", "Email postulación", "Resumen", "URL", "Estado"]
