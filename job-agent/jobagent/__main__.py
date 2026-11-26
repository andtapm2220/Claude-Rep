"""
Uso (modo plan, el que corre a diario):
  python -m jobagent collect [--max N]                      recolecta y verifica vigencia -> output/candidatas.md
  python -m jobagent publish [--parcial]                    aplica state/scores.json -> resumen y filas de planilla
  python -m jobagent rotacion [--todo]                      empleadores del directorio que toca buscar
  python -m jobagent fuentes                                rendimiento por fuente -> output/fuentes.md
Modo API (respaldo, GitHub Actions):
  python -m jobagent run [--no-llm] [--limit-sources N]   corrida diaria completa
  python -m jobagent poll                                   procesa botones de Telegram (postular/descartar)
  python -m jobagent chatid                                 muestra tu chat_id de Telegram (setup)
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import sheets
from .apply_email import send_application, smtp_configured
from .filters import merge_duplicates, prefilter
from .http import Http
from .models import Job
from .sources import all_fetchers
from .store import Store
from .telegram import Telegram, job_message
from .verify import verify

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("jobagent")


def load_profile() -> tuple[dict, str]:
    profile = yaml.safe_load((ROOT / "config/profile.yaml").read_text(encoding="utf-8"))
    local = ROOT / "config/cv.local.md"  # no se sube al repo (.gitignore)
    cv = os.environ.get("CV_TEXT") or (local if local.exists() else ROOT / "config/cv.md").read_text(encoding="utf-8")
    return profile, cv


def cv_pdf_path() -> Path | None:
    p = Path(os.environ.get("CV_PDF_PATH", ROOT / "config/cv.pdf"))
    return p if p.exists() else None


def digest_markdown(jobs: list[Job], stats: dict) -> str:
    out = [f"# Ofertas {datetime.now().date()}\n", "Fuentes: " + ", ".join(f"{k}: {v}" for k, v in stats.items()) + "\n"]
    for i, j in enumerate(jobs, 1):
        out.append(f"## {i}. {j.title} — {j.company}\n- Encaje: {j.score} ({j.verdict}) · Confianza: {j.trust}"
                   f"\n- {j.location} {'(remoto)' if j.remote else ''} · {j.salary}\n- {j.url}\n- {j.summary}\n"
                   + "".join(f"  - ✅ {r}\n" for r in j.reasons) + "".join(f"  - ⚠️ {g}\n" for g in j.gaps)
                   + (f"- Señales: {', '.join(j.flags)}\n" if j.flags else ""))
    return "\n".join(out)


def cmd_run(args) -> int:
    profile, cv = load_profile()
    agent = profile.get("agente", {})
    store = Store(ROOT / "state/jobs.db")
    http = Http(delay=float(os.environ.get("HTTP_DELAY", "1.5")))
    tg = Telegram()

    # 1. Recolectar
    found: list[Job] = []
    stats: dict[str, int | str] = {}
    for name, fetch in all_fetchers().items():
        src = (profile.get("fuentes") or {}).get(name, {})
        if not src.get("enabled", False):
            continue
        if args.limit_sources:
            src = {**src, "max_pages": 1, "max_details": args.limit_sources}
        try:
            jobs = fetch(src, profile, http, store.is_seen)
            stats[name] = len(jobs)
            found += jobs
        except Exception as e:  # una fuente caída no detiene las demás
            log.exception("Fuente %s falló", name)
            stats[name] = f"error: {type(e).__name__}"
    log.info("Nuevas ofertas por fuente: %s", stats)

    # 2. Unificar duplicados, verificar, prefiltrar
    found = merge_duplicates(found)
    max_age = agent.get("max_antiguedad_dias", 21)
    for j in found:
        verify(j, max_age_days=max_age)
    candidates = [j for j in prefilter(found, profile) if "vencida" not in j.flags]
    top = candidates[: agent.get("max_para_claude", 40)]
    log.info("%d nuevas, %d pasan prefiltro, %d van a Claude", len(found), len(candidates), len(top))

    # 3. Puntuar con Claude
    use_llm = not args.no_llm and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if use_llm and top:
        from .scorer import score_jobs

        score_jobs(top, profile, cv, agent.get("modelo", "claude-opus-5-5"))
    elif top:
        log.warning("Sin ANTHROPIC_API_KEY o con --no-llm: se usa sólo el prefiltro (sin puntaje IA)")
        best = max(j.prefilter_score for j in top) or 1
        for j in top:
            j.score, j.verdict, j.summary = int(100 * j.prefilter_score / best), "parcial", "(sin evaluación IA)"

    # 4. Seleccionar lo que vale la pena notificar
    min_score, min_trust = agent.get("puntaje_minimo", 65), agent.get("confianza_minima", 50)
    picks = sorted(
        [j for j in top if j.score is not None and j.score >= min_score and j.trust >= min_trust and j.verdict != "descartar"],
        key=lambda j: (j.score, j.trust), reverse=True,
    )

    # 5. Cartas de presentación para las mejores
    if use_llm:
        from .scorer import draft_application

        for j in picks[: agent.get("cartas_para_top", 5)]:
            letter = draft_application(j, profile, cv, agent.get("modelo", "claude-opus-5-5"))
            if letter:
                store.kv_set(f"letter:{j.key}", json.dumps(letter, ensure_ascii=False))
                out = ROOT / "output/cartas" / f"{datetime.now().date()}_{j.key}.md"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(f"# {j.title} — {j.company}\n{j.url}\n\n**Asunto:** {letter['email_subject']}\n\n"
                               f"{letter['cover_letter']}\n\n## Destacar del CV\n"
                               + "".join(f"- {h}\n" for h in letter["cv_highlights"])
                               + f"\n## Cómo postular ({letter.get('employer_type', '')})\n"
                               + "".join(f"- [ ] {c}\n" for c in letter.get("checklist", [])), encoding="utf-8")

    # 6. Notificar
    header = (f"🗂️ <b>Ofertas del {datetime.now().date()}</b>\n"
              f"Revisadas: {len(found)} nuevas · prefiltro: {len(candidates)} · {'evaluadas por IA: ' + str(sum(j.score is not None for j in top)) if use_llm else 'SIN IA (falta ANTHROPIC_API_KEY)'}\n"
              f"Recomendadas (≥{min_score}, confianza ≥{min_trust}): <b>{len(picks)}</b>\n"
              + " · ".join(f"{html.escape(k)}: {v}" for k, v in stats.items()))
    tg.send(header if picks else header + "\n\nHoy no hubo ofertas nuevas que encajen. Mañana vuelvo a buscar. 🔁")
    for i, j in enumerate(picks, 1):
        text, buttons = job_message(j, i)
        tg.send(text, buttons)
    sheets.append_jobs([j for j in top if j.score is not None and j.score >= 40])

    # 7. Persistir: todo lo visto, salvo lo que debía puntuarse y no se pudo (se reintenta mañana)
    top_ids, pick_ids = {id(j) for j in top}, {id(j) for j in picks}
    for j in found:
        if id(j) in top_ids and j.score is None:
            continue
        store.save(j, status="notificado" if id(j) in pick_ids else "visto")
    store.kv_set("last_run", datetime.now(timezone.utc).isoformat())
    store.commit()
    out = ROOT / "output" / f"{datetime.now().date()}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(digest_markdown(picks, stats), encoding="utf-8")
    log.info("Listo: %d recomendadas. Resumen en %s", len(picks), out)
    return 0


def cmd_collect(args) -> int:
    from .plan_mode import collect

    profile, _ = load_profile()
    print(json.dumps(collect(ROOT, profile, args.limit_sources, args.max), ensure_ascii=False))
    return 0


def cmd_rotacion(args) -> int:
    from . import directorio

    profile, _ = load_profile()
    entries = directorio.load(ROOT, profile)
    picked = directorio.everyone(entries) if args.todo else directorio.rotation(entries)
    md = directorio.rotation_markdown(picked)
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output/rotacion_hoy.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_fuentes(args) -> int:
    """Rendimiento por fuente desde state/jobs.db: cuántas vistas, puntuadas y recomendables (>= puntaje_minimo)."""
    import sqlite3

    profile, _ = load_profile()
    minimo = int(profile.get("agente", {}).get("puntaje_minimo", 65))
    db = sqlite3.connect(str(ROOT / "state/jobs.db"))
    rows = db.execute(
        "SELECT CASE WHEN instr(source, ':') > 0 AND source NOT LIKE 'vigia:%' "
        "THEN substr(source, 1, instr(source, ':') - 1) ELSE source END AS fuente, "
        "COUNT(*), COUNT(score), SUM(score >= ?), MAX(first_seen) "
        "FROM jobs GROUP BY fuente ORDER BY SUM(score >= ?) DESC, COUNT(score) DESC", (minimo, minimo)).fetchall()
    lines = [f"# Rendimiento por fuente (recomendable = puntaje >= {minimo})", "",
             "| Fuente | Vistas | Puntuadas | Recomendables | Última vista |", "|---|---:|---:|---:|---|"]
    lines += [f"| {f} | {v} | {p} | {r or 0} | {(u or '')[:10]} |" for f, v, p, r, u in rows]
    md = "\n".join(lines) + "\n"
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output/fuentes.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def cmd_descubrir(args) -> int:
    from .descubrir import run

    res = run(args.csv, args.out, args.inseguro)
    print(json.dumps({"total": len(res)}, ensure_ascii=False))
    return 0


def cmd_publish(args) -> int:
    from .plan_mode import publish

    profile, _ = load_profile()
    print(json.dumps(publish(ROOT, profile, args.parcial), ensure_ascii=False))
    return 0


def checklist_text(letter: dict) -> str:
    items = letter.get("checklist") or []
    if not items:
        return ""
    return "\n\n📋 <b>Checklist para esta postulación</b>\n" + "\n".join(f"☐ {html.escape(c)}" for c in items)


def cmd_network(args) -> int:
    from .networking import format_message, weekly_targets

    profile, cv = load_profile()
    tg = Telegram()
    model = (profile.get("fuentes", {}).get("explorador_web", {}) or {}).get("model") or profile.get("agente", {}).get("modelo", "claude-opus-5-5")
    targets = weekly_targets(profile, cv, model)
    for part in format_message(targets):
        tg.send(part)
    out = ROOT / "output" / f"pituto_{datetime.now().date()}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(targets, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Pituto: %d organizaciones sugeridas", len(targets))
    return 0


def evaluate_manual(text: str, profile: dict, cv: str, store: Store, tg: Telegram) -> None:
    """Le mandas al bot un enlace (p. ej. un post de Facebook o una página de una ONG) o el texto
    de una oferta, y te responde con la evaluación y los botones de siempre."""
    from .sources.generic import page_to_job

    urls = re.findall(r"https?://\S+", text)
    jobs: list[Job] = []
    for u in urls[:5]:
        j = page_to_job(u, Http(delay=0.5), source="manual")
        if j and len(j.description) < 300 and len(text) > 300:
            j.description = text  # la página no dejó leer (p. ej. Facebook): usa el texto que pegaste
        jobs.append(j or Job(source="manual", url=u, title="Oferta compartida", description=text, apply_url=u))
    if not urls:
        if len(text) < 80:
            tg.send("Mándame el enlace de una oferta o pega su texto completo y la evalúo. 🔎")
            return
        first = text.strip().splitlines()[0][:120]
        jobs.append(Job(source="manual", url=f"manual://{abs(hash(text))}", title=first, description=text))
    agent = profile.get("agente", {})
    for j in jobs:
        verify(j, max_age_days=agent.get("max_antiguedad_dias", 21))
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        from .scorer import score_jobs

        score_jobs(jobs, profile, cv, agent.get("modelo", "claude-opus-5-5"))
    for i, j in enumerate(jobs, 1):
        if j.score is None:
            tg.send(f"No pude evaluar {html.escape(j.url)} (¿falta ANTHROPIC_API_KEY?)")
            continue
        store.save(j, status="notificado")
        body, buttons = job_message(j, i)
        tg.send("🔎 <b>Evaluación de lo que me enviaste</b>\n\n" + body, buttons)


def cmd_poll(args) -> int:
    profile, cv = load_profile()
    store, tg = Store(ROOT / "state/jobs.db"), Telegram()
    if not tg.enabled:
        log.error("Falta TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return 1
    offset = int(store.kv_get("tg_offset", "0"))
    for upd in tg.updates(offset):
        offset = max(offset, upd["update_id"] + 1)
        msg = upd.get("message") or {}
        if msg.get("text") and str(msg["chat"]["id"]) == str(tg.chat_id) and not msg["text"].startswith("/"):
            evaluate_manual(msg["text"], profile, cv, store, tg)
            continue
        cb = upd.get("callback_query")
        if not cb or str(cb["message"]["chat"]["id"]) != str(tg.chat_id):
            continue  # sólo obedece a tu propio chat
        action, _, key = cb.get("data", "").partition(":")
        job = store.get(key)
        if not job:
            tg.answer_callback(cb["id"], "No encuentro esa oferta")
            continue
        if action == "skip":
            store.set_status(key, "descartado"); sheets.set_status(key, "descartado")
            tg.answer_callback(cb["id"], "Descartada 👍")
        elif action == "apply":
            if job["status"] == "postulado":
                tg.answer_callback(cb["id"], "Ya postulaste a esta oferta")
                continue
            letter = json.loads(store.kv_get(f"letter:{key}", "null") or "null")
            if not letter:
                from .scorer import draft_application

                j = Job(**{k: v for k, v in job.items() if k in Job.__dataclass_fields__ and k not in ("posted_at", "valid_through")})
                letter = draft_application(j, profile, cv, profile.get("agente", {}).get("modelo", "claude-opus-5-5"))
            if not letter:
                tg.answer_callback(cb["id"], "No pude redactar la carta")
                continue
            to = job["apply_emails"][0]
            if smtp_configured():
                try:
                    send_application(to, letter["email_subject"], letter["cover_letter"], cv_pdf_path(), profile.get("nombre", ""))
                except Exception as e:
                    log.exception("SMTP")
                    tg.send(f"❌ Error enviando a {html.escape(to)}: {html.escape(str(e))}")
                    continue
                store.set_status(key, "postulado"); sheets.set_status(key, "postulado")
                tg.answer_callback(cb["id"], "Postulación enviada ✅")
                tg.send(f"✅ Postulación enviada a <b>{html.escape(to)}</b> para <b>{html.escape(job['title'])}</b>\n"
                        f"Asunto: {html.escape(letter['email_subject'])}" + checklist_text(letter))
            else:
                tg.answer_callback(cb["id"], "SMTP no configurado: te mando la carta para copiar")
                tg.send(f"📝 Para: {html.escape(to)}\nAsunto: {html.escape(letter['email_subject'])}\n\n"
                        f"{html.escape(letter['cover_letter'])}" + checklist_text(letter))
    store.kv_set("tg_offset", str(offset))
    store.commit()
    return 0


def cmd_chatid(args) -> int:
    tg = Telegram(chat_id="-")
    for u in tg.updates(0):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat:
            print(f"chat_id={chat['id']}  ({chat.get('first_name', '')} {chat.get('username', '')})")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="jobagent")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--no-llm", action="store_true", help="no usar Claude (sólo prefiltro)")
    r.add_argument("--limit-sources", type=int, default=0, help="prueba rápida: N detalles por fuente")
    sub.add_parser("poll")
    sub.add_parser("network", help="sugerencias semanales de contactos (pituto)")
    c = sub.add_parser("collect", help="modo plan: recolecta y verifica sin IA")
    c.add_argument("--limit-sources", type=int, default=0)
    c.add_argument("--max", type=int, default=None, help="máximo de candidatas para evaluar")
    pb = sub.add_parser("publish", help="modo plan: aplica state/scores.json y genera el resumen")
    pb.add_argument("--parcial", action="store_true", help="guarda lo puntuado y deja el resto pendiente")
    ro = sub.add_parser("rotacion", help="empleadores del directorio que toca buscar hoy")
    ro.add_argument("--todo", action="store_true", help="todo el directorio (corrida profunda del domingo)")
    sub.add_parser("fuentes", help="rendimiento por fuente (vistas, puntuadas, recomendables)")
    de = sub.add_parser("descubrir", help="una vez: encuentra la página de empleo de cada institución de un CSV")
    de.add_argument("csv", nargs="+")
    de.add_argument("--out", default="state/descubrimiento.json")
    de.add_argument("--inseguro", action="store_true", help="no verificar TLS (sólo en la red del trabajo)")
    sub.add_parser("chatid")
    args = p.parse_args(argv)
    return {"run": cmd_run, "poll": cmd_poll, "chatid": cmd_chatid, "network": cmd_network,
            "collect": cmd_collect, "publish": cmd_publish,
            "rotacion": cmd_rotacion, "fuentes": cmd_fuentes, "descubrir": cmd_descubrir}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
