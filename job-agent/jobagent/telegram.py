"""Telegram: envía el resumen diario y recibe tus aprobaciones (botones)."""
from __future__ import annotations

import html
import logging
import os

import requests

from .models import Job

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"

VERDICT = {"postular_ya": "🟢 Postular ya", "vale_la_pena": "🟡 Vale la pena", "parcial": "🟠 Parcial", "descartar": "⚪ Descartar"}
FLAG_TXT = {
    "reciente": "publicada hace ≤7 días", "web_empresa_ok": "web de la empresa existe",
    "en_varios_portales": "aparece en varios portales", "empresa_verificada_portal": "empresa verificada por el portal",
    "email_dominio_empresa": "email con dominio de la empresa", "empresa_anonima": "empresa anónima",
    "email_gratuito": "contacto con email gratuito", "sin_fecha": "sin fecha de publicación",
    "descripcion_pobre": "descripción muy corta",
    "url_en_resultados_busqueda": "enlace real encontrado en buscador", "alerta_oficial_portal": "llegó por tu alerta oficial del portal", "web_empresa_no_resuelve": "la web de la empresa no responde",
}


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def call(self, method: str, **params):
        r = requests.post(API.format(token=self.token, method=method), json=params, timeout=30)
        data = r.json()
        if not data.get("ok"):
            log.error("Telegram %s: %s", method, data)
        return data

    def send(self, text: str, buttons: list[list[dict]] | None = None):
        if not self.enabled:
            print("\n[TELEGRAM-DRY-RUN]\n" + text)
            return None
        params = {"chat_id": self.chat_id, "text": text[:4096], "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        return self.call("sendMessage", **params)

    def answer_callback(self, cb_id: str, text: str):
        if self.enabled:
            self.call("answerCallbackQuery", callback_query_id=cb_id, text=text[:190])

    def updates(self, offset: int) -> list[dict]:
        if not self.enabled:
            return []
        return self.call("getUpdates", offset=offset, timeout=0, allowed_updates=["callback_query", "message"]).get("result", [])


def job_message(j: Job, rank: int) -> tuple[str, list[list[dict]]]:
    e = html.escape
    lines = [
        f"<b>{rank}. {e(j.title)}</b>",
        f"🏢 {e(j.company or 'Empresa no indicada')} · 📍 {e(j.location or '-')}{' · 🌎 remoto' if j.remote else ''}",
        f"🎯 Encaje <b>{j.score}/100</b> · {VERDICT.get(j.verdict, j.verdict)} · 🛡️ Confianza {j.trust}/100",
    ]
    meta = []
    if j.salary:
        meta.append(f"💰 {e(j.salary)}")
    if j.posted_at:
        meta.append(f"🗓️ {j.posted_at.date()}")
    if j.valid_through:
        meta.append(f"⏳ cierra {j.valid_through.date()}")
    meta.append(f"🔗 {e(j.source)}" + (f" (+{', '.join(j.also_on)})" if j.also_on else ""))
    lines.append(" · ".join(meta))
    if j.summary:
        lines.append(f"\n{e(j.summary)}")
    if j.reasons:
        lines.append("✅ " + "\n✅ ".join(e(r) for r in j.reasons[:3]))
    if j.gaps:
        lines.append("⚠️ " + "\n⚠️ ".join(e(g) for g in j.gaps[:2]))
    checks = [FLAG_TXT[f] for f in j.flags if f in FLAG_TXT]
    if checks:
        lines.append("🔎 Verificación: " + ", ".join(checks))
    if j.red_flags or any(f.startswith("ESTAFA?") for f in j.flags):
        lines.append("🚩 " + e("; ".join(j.red_flags + [f for f in j.flags if f.startswith("ESTAFA?")])))
    row = [{"text": "🌐 Ver oferta", "url": j.apply_url or j.url}]
    if j.apply_emails:
        row.append({"text": "✉️ Postular por email", "callback_data": f"apply:{j.key}"})
    row.append({"text": "🙈 Descartar", "callback_data": f"skip:{j.key}"})
    return "\n".join(lines), [row]
