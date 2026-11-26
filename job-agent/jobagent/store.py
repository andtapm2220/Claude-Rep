"""Estado persistente en SQLite: ofertas ya vistas, puntajes y postulaciones."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job


def url_key(url: str) -> str:
    return re.sub(r"\?.*?(?=#cambio-|$)|#(?!cambio-).*$", "", url.strip().lower())


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              key TEXT PRIMARY KEY, url TEXT, source TEXT, title TEXT, company TEXT,
              first_seen TEXT, score INTEGER, trust INTEGER, status TEXT DEFAULT 'nuevo',
              data TEXT
            );
            CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
            """
        )
        self._seen = {r[0] for r in self.db.execute("SELECT url FROM jobs")}

    def is_seen(self, url: str) -> bool:
        return url_key(url) in self._seen

    def save(self, job: Job, status: str = "nuevo") -> None:
        data = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in job.__dict__.items()}
        self.db.execute(
            "INSERT OR IGNORE INTO jobs (key,url,source,title,company,first_seen,score,trust,status,data)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job.key, url_key(job.url), job.source, job.title, job.company,
             datetime.now(timezone.utc).isoformat(), job.score, job.trust, status, json.dumps(data, ensure_ascii=False)),
        )
        self._seen.add(url_key(job.url))

    def get(self, key: str) -> dict | None:
        row = self.db.execute("SELECT data, status FROM jobs WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        d = json.loads(row[0])
        d["status"] = row[1]
        return d

    def set_status(self, key: str, status: str) -> None:
        self.db.execute("UPDATE jobs SET status=? WHERE key=?", (status, key))

    def kv_get(self, k: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row[0] if row else default

    def kv_set(self, k: str, v: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv (k,v) VALUES (?,?)", (k, v))

    def commit(self) -> None:
        self.db.commit()
