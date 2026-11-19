"""Verificación de que una oferta es real, vigente y no es estafa.

Combina señales objetivas (fechas, enlace vivo, empresa identificable, dominio que
existe, publicada en varios portales) con patrones de estafa conocidos. Claude
agrega su propio juicio en `red_flags` al puntuar.
"""
from __future__ import annotations

import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import Job, norm

SCAM_PATTERNS = [
    (r"(deposit|pag(a|ar|o)|cancela(r)?|cuota|inversion)\s.{0,40}(inscripcion|capacitacion|curso|kit|material|garantia|registro)", "pide_pago"),
    (r"inversion (inicial|minima)", "pide_inversion"),
    (r"multinivel|network marketing|libertad financiera|se tu propio jefe", "multinivel"),
    (r"gana (hasta )?(bs|\$|usd)\s?\d+.{0,30}(semana|dia|desde casa)", "ganancias_irreales"),
    (r"(solo|unicamente) (por )?whatsapp", "solo_whatsapp"),
    (r"envia (tu )?(foto|fotografia) de cuerpo", "pedido_inapropiado"),
    (r"(numero de )?(cuenta bancaria|tarjeta de credito|pin)\b", "pide_datos_bancarios"),
]
ANON_COMPANY = ("importante empresa", "empresa confidencial", "confidencial", "empresa lider", "reconocida empresa", "")
FREE_MAIL = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.es", "live.com")


_DNS_OK: bool | None = None


def _dns_available() -> bool:
    """En algunos entornos (proxies) no hay DNS directo: entonces la señal no se usa."""
    global _DNS_OK
    if _DNS_OK is None:
        try:
            socket.setdefaulttimeout(5)
            socket.gethostbyname("www.google.com")
            _DNS_OK = True
        except OSError:
            _DNS_OK = False
    return _DNS_OK


def _domain_resolves(url: str) -> bool:
    host = urlparse(url if "://" in url else f"http://{url}").hostname
    if not host:
        return False
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def verify(job: Job, max_age_days: int = 21, check_dns: bool = True, now: datetime | None = None) -> Job:
    now = now or datetime.now(timezone.utc)
    flags, trust = [f for f in job.flags if f], 60  # el enlace se descargó bien => base 60
    text = norm(f"{job.title} {job.description}")

    age = job.age_days(now)
    if age is None:
        flags.append("sin_fecha"); trust -= 10
    elif age <= 7:
        flags.append("reciente"); trust += 10
    elif age > max_age_days:
        flags.append("antigua"); trust -= 25

    if job.valid_through and job.valid_through < now:
        flags.append("vencida"); trust -= 40

    if norm(job.company) in ANON_COMPANY:
        flags.append("empresa_anonima"); trust -= 10
    else:
        trust += 5

    if job.company_url and check_dns and _dns_available():
        if _domain_resolves(job.company_url):
            flags.append("web_empresa_ok"); trust += 10
        else:
            flags.append("web_empresa_no_resuelve"); trust -= 10

    if "empresa_verificada_portal" in flags:
        trust += 10
    if job.also_on:
        flags.append("en_varios_portales"); trust += 10

    for em in job.apply_emails:
        dom = em.split("@")[-1]
        if dom in FREE_MAIL:
            flags.append("email_gratuito"); trust -= 5
            break
        if job.company_url and dom.split(".")[0] in (urlparse(job.company_url).hostname or ""):
            flags.append("email_dominio_empresa"); trust += 5
            break

    if len(job.description) < 250:
        flags.append("descripcion_pobre"); trust -= 10

    for pat, name in SCAM_PATTERNS:
        if re.search(pat, text):
            flags.append(f"ESTAFA?:{name}"); trust -= 35

    job.flags = list(dict.fromkeys(flags))
    job.trust = max(0, min(100, trust))
    return job
