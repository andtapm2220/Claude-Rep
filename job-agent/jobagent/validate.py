"""Validación obligatoria de vigencia: abre la página REAL de cada oferta y decide si sigue abierta.

Regla: una oferta solo puede recomendarse si su estado es "abierta":
  - la página responde, no tiene señales de cierre ("Closed", "convocatoria cerrada", "expired"...), y
  - tiene una fecha de cierre futura, o (si no muestra fecha de cierre) fue publicada hace <= 21 días.
Si la página dice cerrada o la fecha de cierre ya pasó -> "cerrada" (se descarta).
Si no se puede abrir la página o no hay ninguna fecha -> "no_verificada" (va a la planilla, nunca como recomendada).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from .http import Http, html_to_text
from .models import Job
from .sources import deadline_in_text, json_ld, parse_iso, relative_date, spanish_date

log = logging.getLogger(__name__)
BO = timezone(timedelta(hours=-4))

CLOSED = re.compile(
    r"\bjob is closed\b|\bposition (?:has been )?(?:closed|filled)\b|\bno longer (?:accepting|available)\b|"
    r"\bthis (?:job|vacancy|posting) has expired\b|\bapplications? (?:are )?closed\b|\bvacancy closed\b|"
    r"convocatoria (?:cerrada|finalizada|concluida|vencida)|oferta (?:cerrada|finalizada|vencida|expirada)|"
    r"\b(?:has|have) (?:been )?(?:filled|closed|expired)\b|\bno longer open\b|\bposting (?:has )?expired\b|"
    r"ya no (?:est[aá] disponible|acepta postulaciones)|proceso (?:cerrado|concluido)|\bya cerr[oó]\b|"
    r"(?:application deadline|deadline)\s*:?\s*[A-Z][a-z]+ \d{1,2}, 20\d\d\s+closed\b|"
    r"^\s*closed\s*$",  # Impactpool: la palabra "Closed" sola en su línea
    re.I | re.M)
EN_DEADLINE = re.compile(
    r"(?:application deadline|closing date|deadline|apply by|applications close)\s*:?\s*"
    r"(?:\w+,\s*)?([A-Z][a-z]+ \d{1,2},? 20\d\d|\d{1,2} [A-Z][a-z]+,? 20\d\d)", re.I)
NUM_DEADLINE = re.compile(
    r"(?:cierre|plazo|vence|vencimiento|hasta el|fecha l[ií]mite|deadline)[^0-9\n]{0,40}(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)", re.I)


# Solo "hace N días" / "N days ago" (no cualquier "5 días" del texto)
AGO = re.compile(r"\bhace\s+\d+\s*(?:minutos?|horas?|d[ií]as?|semanas?)\b|\b\d+\s*(?:minutes?|hours?|days?|weeks?)\s+ago\b", re.I)


def _en_date(s: str) -> datetime | None:
    for fmt in ("%B %d, %Y", "%B %d %Y", "%d %B %Y", "%d %B, %Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).replace(hour=23, minute=59, tzinfo=BO)
        except ValueError:
            continue
    return None


def deadlines_in(text: str) -> list[datetime]:
    out = []
    d = deadline_in_text(text)
    if d:
        out.append(d)
    out += [x for x in (_en_date(m.group(1)) for m in EN_DEADLINE.finditer(text)) if x]
    for m in NUM_DEADLINE.finditer(text):
        try:
            out.append(datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), 23, 59, tzinfo=BO))
        except ValueError:
            pass
    return out


def page_text(url: str, http: Http) -> tuple[str, dict] | None:
    """Texto VISIBLE de la página (sin scripts ni estilos, donde viven textos de plantilla que confunden)
    y los datos estructurados de la oferta (JSON-LD JobPosting: validThrough, datePosted)."""
    try:
        r = http.get(url)
    except Exception as e:
        log.info("validación: no se pudo abrir %s (%s)", url, e)
        return None
    if r.status_code >= 400:
        return None
    if "pdf" in r.headers.get("content-type", "").lower() or r.content[:5] == b"%PDF-":
        import io

        from pypdf import PdfReader
        try:
            return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages[:8]), {}
        except Exception:
            return None
    html = r.text
    ld = {}
    posts = json_ld(html, "JobPosting")
    if posts:
        ld = {"valid_through": parse_iso(posts[0].get("validThrough")), "posted": parse_iso(posts[0].get("datePosted"))}
    visible = re.sub(r"(?is)<(script|style|noscript|template)\b.*?</\1>", " ", html)
    return html_to_text(visible), ld


MAX_PUBLICADA_DIAS = 60  # más vieja que esto = oferta fantasma, aunque su "vigente hasta" se renueve solo


def validate(job: Job, http: Http, now: datetime | None = None, max_age_days: int = 21) -> str:
    """Devuelve 'abierta' | 'cerrada' | 'no_verificada' y actualiza job.valid_through / job.flags."""
    now = now or datetime.now(timezone.utc)
    # fechas sin zona (p. ej. alertas por email) rompían las restas: se asumen hora de Bolivia
    job.posted_at, job.valid_through = (d.replace(tzinfo=BO) if d and d.tzinfo is None else d
                                        for d in (job.posted_at, job.valid_through))
    got = page_text(job.url, http)
    if got is None:
        status = "no_verificada"
        job.flags.append("pagina_no_accesible")
    else:
        text, ld = got
        dls = deadlines_in(text)
        if not dls and ld.get("valid_through"):  # la fecha escrita en la convocatoria manda sobre la del portal
            dls.append(ld["valid_through"])
        if ld.get("posted") and not job.posted_at:
            job.posted_at = ld["posted"]
        if dls:
            # varios cargos en una misma convocatoria: vale el plazo más tardío
            job.valid_through = max(dls)
        pub = re.search(r"(?:fecha de publicaci[oó]n|publicad[oa] (?:el )?)\s*:?\s*(\d{1,2}\s*(?:de\s+)?[a-zé]+\.?\s*(?:de\s+)?20\d\d)", text, re.I)
        posted_page = spanish_date(pub.group(1)) if pub else None
        if posted_page and not ld.get("posted"):
            job.posted_at = job.posted_at or posted_page
        oldest = min([d for d in (ld.get("posted"), posted_page) if d], default=None)
        if CLOSED.search(text):
            status = "cerrada"
        elif oldest and (now - oldest).days > MAX_PUBLICADA_DIAS:
            status = "cerrada"
            job.flags.append("oferta_fantasma_publicada_hace_mas_de_60_dias")
        elif dls and min(dls) < now <= max(dls):
            # un plazo vencido y otra fecha futura en la misma página (p. ej. "contrato hasta 2027" u otra
            # oferta enlazada): no se puede saber cuál manda, así que no se recomienda
            status = "no_verificada"
            job.flags.append("plazos_contradictorios")
        elif job.valid_through:
            status = "abierta" if job.valid_through >= now else "cerrada"
        else:
            # solo fechas que dicen ser de publicación; antes cualquier fecha del texto ("inicio de labores")
            # contaba como publicación, y una fecha futura salía "abierta"
            ago = AGO.search(text)
            posted = job.posted_at or posted_page or (relative_date(ago.group(0)) if ago else None)
            age = (now - posted).days if posted else None
            status = "abierta" if age is not None and 0 <= age <= max_age_days else "no_verificada"
            if status == "no_verificada":
                job.flags.append("sin_fecha_verificable")
    job.flags = [f for f in job.flags if not f.startswith("vigencia:")] + [f"vigencia:{status}"]
    return status


def status_of(job: Job) -> str:
    return next((f.split(":", 1)[1] for f in job.flags if f.startswith("vigencia:")), "no_verificada")
