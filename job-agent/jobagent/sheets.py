"""Registro en Google Sheets: una fila por oferta, para seguimiento de postulaciones."""
from __future__ import annotations

import json
import logging
import os
from datetime import date

from .models import Job

log = logging.getLogger(__name__)
HEADER = ["Fecha", "Puntaje", "Veredicto", "Confianza", "Cargo", "Empresa", "Ubicación", "Remoto",
          "Salario", "Publicada", "Cierra", "Portal", "Email postulación", "Resumen", "Por qué encaja",
          "Brechas", "Alertas", "URL", "Estado", "Clave"]


def _sheet():
    raw, sid = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"), os.environ.get("GOOGLE_SHEET_ID")
    if not raw or not sid:
        return None
    import gspread

    gc = gspread.service_account_from_dict(json.loads(raw))
    ws = gc.open_by_key(sid).sheet1
    if ws.row_values(1) != HEADER:
        ws.update([HEADER], "A1")
    return ws


def append_jobs(jobs: list[Job]) -> None:
    try:
        ws = _sheet()
    except Exception as e:
        log.error("Google Sheets no disponible: %s", e)
        return
    if ws is None:
        log.info("Google Sheets no configurado (GOOGLE_SHEET_ID / GOOGLE_SERVICE_ACCOUNT_JSON); se omite")
        return
    rows = [[
        date.today().isoformat(), j.score, j.verdict, j.trust, j.title, j.company, j.location,
        "sí" if j.remote else "no", j.salary, j.posted_at.date().isoformat() if j.posted_at else "",
        j.valid_through.date().isoformat() if j.valid_through else "", "+".join([j.source] + j.also_on),
        ", ".join(j.apply_emails), j.summary, " | ".join(j.reasons), " | ".join(j.gaps),
        " | ".join(j.red_flags + [f for f in j.flags if f.startswith("ESTAFA?")]), j.url, "nuevo", j.key,
    ] for j in jobs]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info("Sheets: %d filas agregadas", len(rows))


def set_status(key: str, status: str) -> None:
    try:
        ws = _sheet()
        if ws is None:
            return
        cell = ws.find(key, in_column=len(HEADER))
        if cell:
            ws.update_cell(cell.row, HEADER.index("Estado") + 1, status)
    except Exception as e:
        log.error("Sheets set_status: %s", e)
