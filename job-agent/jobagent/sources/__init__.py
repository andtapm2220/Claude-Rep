from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..http import Http
from ..models import Job

# Firma común: fetch(cfg_fuente, cfg_perfil, http, is_seen) -> list[Job]
Fetcher = Callable[[dict, dict, Http, Callable[[str], bool]], list[Job]]


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone(timedelta(hours=-4)))  # hora de Bolivia
    except ValueError:
        return None


def json_ld(html: str, type_: str) -> list[dict]:
    """Bloques schema.org del tipo pedido (p. ej. JobPosting, ItemList)."""
    out = []
    for raw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for d in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(d, dict) and d.get("@type") == type_:
                out.append(d)
    return out


def relative_date(text: str, now: datetime | None = None) -> datetime | None:
    """'Hace 9 horas', 'Ayer', 'Hace 3 días', 'Hace más de 30 días' -> datetime."""
    from ..models import norm

    t = norm(text)
    now = now or datetime.now(timezone.utc)
    if any(w in t for w in ("hoy", "minuto", "ahora", "minute", "just now", "today")):
        return now
    if "ayer" in t or "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\s*(hora|hour|dia|day|semana|week|mes|month)", t)
    if not m:
        return None
    n = int(m.group(1))
    unit = {"hour": "hora", "day": "dia", "week": "semana", "month": "mes"}.get(m.group(2), m.group(2))
    return now - {"hora": timedelta(hours=n), "dia": timedelta(days=n),
                  "semana": timedelta(weeks=n), "mes": timedelta(days=30 * n)}[unit]


def all_fetchers() -> dict[str, Fetcher]:
    from . import computrabajo, email_alerts, explorer, getonbrd, linkedin, reliefweb, remotive, trabajito, trabajopolis

    return {
        "email_alerts": email_alerts.fetch,
        "linkedin": linkedin.fetch,
        "reliefweb": reliefweb.fetch,
        "trabajito": trabajito.fetch,
        "computrabajo": computrabajo.fetch,
        "trabajopolis": trabajopolis.fetch,
        "getonbrd": getonbrd.fetch,
        "remotive": remotive.fetch,
        "explorador_web": explorer.fetch,  # al final: es la fuente más cara
    }
