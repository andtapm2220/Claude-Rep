"""Postulación por email (muy común en Bolivia: 'enviar CV a rrhh@empresa.com').

Sólo se envía después de que apruebas la oferta con el botón de Telegram.
Usa SMTP (p. ej. Gmail con contraseña de aplicación).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)


def smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASSWORD"))


def send_application(to: str, subject: str, body: str, cv_pdf: Path | None, sender_name: str) -> None:
    user = os.environ["SMTP_USER"]
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Reply-To"] = os.environ.get("REPLY_TO", user)
    msg.set_content(body)
    if cv_pdf and cv_pdf.exists():
        msg.add_attachment(cv_pdf.read_bytes(), maintype="application", subtype="pdf", filename=cv_pdf.name)
    else:
        log.warning("No hay CV en PDF; se envía sin adjunto")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(user, os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
    log.info("Postulación enviada a %s", to)
