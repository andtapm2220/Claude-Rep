"""Lee las alertas de empleo que te llegan por email (Gmail vía IMAP).

Es la forma más segura de cubrir LinkedIn, Trabajando.com.bo, Trabajópolis,
Computrabajo, Indeed, Bumeran, etc.: tú creas alertas en cada portal (función
oficial), y el agente lee esos correos. Nadie scrapea tu cuenta.

Para LinkedIn, además, toma el id de cada oferta del correo y descarga el detalle
público (sin login).
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import logging
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from html import unescape

from ..http import Http, html_to_text
from ..models import Job
from . import linkedin
from .generic import page_to_job

log = logging.getLogger(__name__)

SENDERS = {
    "linkedin": "linkedin.com",
    "computrabajo": "computrabajo.com",
    "trabajando": "trabajando.com",
    "trabajopolis": "trabajopolis.bo",
    "indeed": "indeed.com",
    "bumeran": "bumeran.com",
    "glassdoor": "glassdoor.com",
    "getonbrd": "getonbrd.com",
}
# Enlaces que parecen una oferta concreta (no "ver todas", "configurar alerta", etc.)
JOB_LINK = re.compile(
    r"https?://[^\s\"'<>]*(?:/jobs/view/\d+|/comm/jobs/view/\d+|/ofertas-de-trabajo/[^\s\"'<>]+|/trabajo/\d+/[^\s\"'<>]+|"
    r"/trabajo-empleo/[^\s\"'<>]+|/viewjob\?jk=[^\s\"'<>]+|/empleos/[^\s\"'<>]+-\d+\.html|/jobs/[a-z0-9-]+-[a-z0-9-]+)",
    re.I,
)


def _body(msg) -> str:
    parts = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype in ("text/html", "text/plain") and not part.get_filename():
            payload = part.get_payload(decode=True) or b""
            parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
    return "\n".join(parts)


def _anchor_texts(html: str) -> dict[str, str]:
    """url -> texto del enlace (en las alertas suele ser el cargo)."""
    out = {}
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        t = " ".join(unescape(re.sub(r"<[^>]+>", " ", inner)).split())
        if t and len(t) > 4 and unescape(href) not in out:
            out[unescape(href)] = t
    return out


def fetch(src: dict, profile: dict, http: Http, is_seen) -> list[Job]:
    user = os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER")
    pwd = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    if not (user and pwd):
        log.info("alertas email: sin IMAP_USER/IMAP_PASSWORD (o SMTP_*), se omite")
        return []
    since = (datetime.now() - timedelta(days=src.get("days", 2))).strftime("%d-%b-%Y")
    jobs: list[Job] = []
    li_ids: list[str] = []
    pending: list[tuple] = []
    try:
        M = imaplib.IMAP4_SSL(os.environ.get("IMAP_HOST", "imap.gmail.com"))
        M.login(user, pwd)
        M.select("INBOX", readonly=True)  # no marca nada como leído
        for portal, domain in SENDERS.items():
            if portal not in src.get("portals", list(SENDERS)):
                continue
            typ, data = M.search(None, f'(SINCE {since} FROM "{domain}")')
            ids = data[0].split() if typ == "OK" else []
            log.info("alertas email %s: %d correos", portal, len(ids))
            for mid in ids[-30:]:
                typ, raw = M.fetch(mid, "(RFC822)")
                if typ != "OK":
                    continue
                msg = email.message_from_bytes(raw[0][1])
                subject = str(make_header(decode_header(msg.get("Subject", ""))))
                html = _body(msg)
                anchors = _anchor_texts(html)
                for url in dict.fromkeys(JOB_LINK.findall(unescape(html))):
                    m = re.search(r"/jobs/view/(\d+)", url)
                    if portal == "linkedin" and m:
                        if not is_seen(linkedin.job_url(m.group(1))) and m.group(1) not in li_ids:
                            li_ids.append(m.group(1))
                        continue
                    clean = re.sub(r"[?#].*$", "", url) if "viewjob" not in url else url
                    if is_seen(clean):
                        continue
                    title = anchors.get(url, "") or subject
                    pending.append((portal, clean, title, subject, msg.get("Date")))
        M.logout()
    except imaplib.IMAP4.error as e:
        log.error("IMAP: no se pudo leer el correo (¿contraseña de aplicación?): %s", e)
    except OSError as e:
        log.error("IMAP: sin conexión: %s", e)
    for portal, url, title, subject, date in pending[: src.get("max_details", 40)]:
        j = page_to_job(url, http, source=f"alerta:{portal}")  # el portal puede bloquear (Cloudflare)
        if not j or len(j.description) < 200:
            j = Job(source=f"alerta:{portal}", url=url, title=title[:200], country="BO", apply_url=url,
                    description=f"Oferta recibida por alerta de {portal}. Asunto del correo: {subject}. Cargo: {title}. "
                                "(No se pudo abrir la página completa; evaluar sólo con estos datos.)")
        j.flags.append("alerta_oficial_portal")
        if date and not j.posted_at:
            j.posted_at = email.utils.parsedate_to_datetime(date)
        jobs.append(j)
    if li_ids:
        jobs += [j for j in linkedin.fetch_ids(li_ids, http, src.get("max_linkedin_details", 30))]
    # dedupe por URL
    uniq = {}
    for j in jobs:
        uniq.setdefault(j.key, j)
    return list(uniq.values())
