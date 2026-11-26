from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone


def norm(text: str | None) -> str:
    """Minúsculas, sin tildes ni espacios repetidos: para comparar texto."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


@dataclass
class Job:
    source: str
    url: str
    title: str
    company: str = ""
    company_url: str = ""
    location: str = ""
    country: str = ""
    remote: bool = False
    posted_at: datetime | None = None
    valid_through: datetime | None = None
    salary: str = ""
    description: str = ""
    apply_emails: list[str] = field(default_factory=list)
    apply_url: str = ""
    # Rellenado por el pipeline
    prefilter_score: float = 0.0
    flags: list[str] = field(default_factory=list)  # señales de verificación
    trust: int = 0  # 0-100, confianza en que la oferta es real y vigente
    score: int | None = None  # 0-100, encaje con el perfil (Claude)
    verdict: str = ""
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    summary: str = ""
    also_on: list[str] = field(default_factory=list)  # otros portales con la misma oferta

    @property
    def key(self) -> str:
        """Id estable por URL (sin query/fragmento)."""
        base = re.sub(r"\?.*?(?=#cambio-|$)|#(?!cambio-).*$", "", self.url.strip().lower())
        return hashlib.sha1(base.encode()).hexdigest()[:16]

    @property
    def fingerprint(self) -> str:
        """Empresa + cargo normalizados, para detectar la misma oferta en varios portales."""
        title = re.sub(r"[^a-z0-9 ]", "", norm(self.title))
        title = re.sub(r"\b(la paz|el alto|santa cruz|cochabamba|bolivia|lp|scz|cbba)\b", "", title)
        comp = re.sub(r"[^a-z0-9]", "", norm(self.company))
        comp = re.sub(r"(srl|sa|ltda|ifd|sociedad|anonima)$", "", comp)
        return f"{comp}|{' '.join(title.split())}"

    def age_days(self, now: datetime | None = None) -> float | None:
        if not self.posted_at:
            return None
        now = now or datetime.now(timezone.utc)
        posted = self.posted_at if self.posted_at.tzinfo else self.posted_at.replace(tzinfo=timezone.utc)
        return (now - posted).total_seconds() / 86400


def job_to_dict(job: Job) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in job.__dict__.items()}


def job_from_dict(d: dict) -> Job:
    fields = {k: v for k, v in d.items() if k in Job.__dataclass_fields__}
    for k in ("posted_at", "valid_through"):
        if fields.get(k):
            fields[k] = datetime.fromisoformat(fields[k])
    return Job(**fields)
