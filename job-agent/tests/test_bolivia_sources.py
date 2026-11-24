import json
from types import SimpleNamespace

from jobagent import networking
from jobagent.filters import prefilter
from jobagent.models import Job
from jobagent.sources import undp, watch
from jobagent.sources.generic import pdf_to_job

FEED = """<?xml version="1.0" encoding="ISO-8859-1" ?><rdf:RDF><item rdf:about="x">
<title>Analista de Finanzas - La Paz, Bolivia</title>
<description><![CDATA[Application Deadline: 30 November 2026<br/>]]></description>
<link>https&#x3a;&#x2f;&#x2f;estm.fa.em2.oraclecloud.com&#x2f;job&#x2f;36583</link>
<dc:date>2026-11-16T15:07:19-05:00</dc:date>
<undpjobs:job_title>Analista de Finanzas</undpjobs:job_title>
<undpjobs:duty_station>La Paz, Bolivia</undpjobs:duty_station>
<undpjobs:post_level>NPSA-9</undpjobs:post_level>
<undpjobs:job_deadline_d>2026-11-30T23:59:00-05:00</undpjobs:job_deadline_d></item></rdf:RDF>"""


def test_undp_feed():
    [j] = undp.parse_feed(FEED)
    assert j.title == "Analista de Finanzas" and j.url == "https://estm.fa.em2.oraclecloud.com/job/36583"
    assert j.valid_through.day == 30 and "NPSA-9" in j.description and j.location == "La Paz, Bolivia"


def test_watch_extracts_only_job_links():
    html = """<a href="/boletin/2026/FAO_6/boletin.html">FAO: Invita a presentarse a convocatorias</a>
      <a href="/boletin/2019/X/boletin.html">Convocatoria vieja</a>
      <a href="https://facebook.com/cebem">Convocatoria en Facebook</a>
      <a href="/contacto">Contacto</a>
      <a href="https://pcontrataciones@gmail.com">Convocatoria</a>
      <a href="/?page_id=1#content">Convocatorias</a>"""
    links = watch.extract_links(html, "https://cebem.org/?page_id=1", must_contain="/boletin/2026/")
    assert links == [("https://cebem.org/boletin/2026/FAO_6/boletin.html", "FAO: Invita a presentarse a convocatorias")]


def test_pdf_tdr_is_read():
    from io import BytesIO

    from pypdf import PdfWriter
    # PDF mínimo sin texto => None (PDF escaneado)
    buf = BytesIO()
    w = PdfWriter(); w.add_blank_page(200, 200); w.write(buf)
    assert pdf_to_job("https://x.org/tdr.pdf", buf.getvalue(), "vigia:x") is None


def test_curated_sources_skip_location_filter():
    profile = {"keywords": ["presupuesto"], "ciudades": ["La Paz"], "acepta_remoto": False, "paises_region": [],
               "agente": {"max_antiguedad_dias": 21}}
    j = Job(source="vigia:Redesma", url="https://cebem.org/b/1", title="Helvetas: consultoría de evaluación",
            location="Bolivia", country="BO", description="x" * 300)
    other = Job(source="trabajito", url="https://t.bo/1", title="Helvetas: consultoría", location="Santa Cruz",
                country="BO", description="x" * 300)
    kept = prefilter([j, other], profile)
    assert kept == [j]


def test_networking_marks_unverified_sources(monkeypatch):
    payload = {"targets": [
        {"organization": "BID", "signal": "Préstamo aprobado para gestión fiscal", "source_url": "https://iadb.org/news/1",
         "fit": "Presupuesto en el MEFP", "who_to_contact": "Especialista fiscal", "linkedin_search": "BID Bolivia fiscal",
         "message": "Hola..."},
        {"organization": "X", "signal": "s", "source_url": "https://inventada.bo", "fit": "f", "who_to_contact": "w",
         "linkedin_search": "l", "message": "m"}]}
    resp = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url="https://www.iadb.org/news/1")]),
        SimpleNamespace(type="text", text=json.dumps(payload))])
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: resp)))
    monkeypatch.setattr(networking.anthropic, "Anthropic", lambda: fake)
    t = networking.weekly_targets({}, "cv", "claude-opus-5-5")
    assert [x["verified_source"] for x in t] == [True, False]
    msgs = networking.format_message(t)
    assert "linkedin.com/search/results/people" in msgs[1] and "no verificada" in msgs[2]


def test_spanish_dates_and_quotas():
    from jobagent.filters import select_candidates
    from jobagent.sources import spanish_date
    assert spanish_date("Boletín 20-141 EXTRA XI:  10 de Noviembre de 2026 REDESMA").month == 11
    assert spanish_date("Fecha de publicación 16 septiembre, 2026").day == 16
    web = [Job(source="web:x", url=f"https://w/{i}", title="t") for i in range(2)]
    vig = [Job(source="vigia:R", url=f"https://v/{i}", title="t") for i in range(30)]
    board = [Job(source="trabajito", url=f"https://b/{i}", title="t") for i in range(30)]
    out = select_candidates(vig + board + web, total=40, max_curated=15)
    assert len(out) == 40 and out[:2] == web
    assert sum(j.source.startswith("vigia") for j in out) == 15 and sum(j.source == "trabajito" for j in out) == 23


def test_deadline_in_text_takes_latest():
    from jobagent.sources import deadline_in_text
    t = ("Técnico - Samaipata vence el 26 de noviembre 2026 a horas 17:59. Técnico - Tarija vence el 27 de noviembre 2026. "
         "Presentar hasta el lunes 16 de noviembre de 2026.")
    d = deadline_in_text(t)
    assert (d.month, d.day) == (11, 27)
    assert deadline_in_text("sin fechas") is None


def test_directorio_rotation_covers_everyone_in_14_days():
    from datetime import date, timedelta

    from jobagent import directorio
    entries = ([{"nombre": f"A{i}", "prioridad": "alta", "categoria": "x"} for i in range(9)]
               + [{"nombre": f"M{i}", "prioridad": "media", "categoria": "y"} for i in range(14)]
               + [{"nombre": f"B{i}", "prioridad": "baja", "categoria": "z"} for i in range(14)]
               + [{"nombre": "W", "prioridad": "alta", "categoria": "x", "empleo_url": "https://w"}])
    d0 = date(2026, 11, 20)
    days = [directorio.rotation(entries, d0 + timedelta(d)) for d in range(14)]
    seen = {e["nombre"] for day in days for e in day}
    assert len(seen) == 37 and "W" not in seen  # la que tiene página vigilada no entra en la rotación
    assert all(sum(e["prioridad"] == "alta" for e in day) == 9 for day in days)  # alta: todos los días
    assert directorio.watch_pages(entries)[0]["url"] == "https://w"


def test_watch_rss_and_link_pattern():
    rss = """<rss><channel><item><title><![CDATA[PEC Consultant (La Paz, BO)]]></title>
      <link>https://jobs.iadb.org/job/1</link><description><![CDATA[<p>Plazo: hasta el 30 de noviembre de 2026</p>]]></description></item></channel></rss>"""
    assert watch.parse_rss(rss) == [("https://jobs.iadb.org/job/1", "PEC Consultant (La Paz, BO)",
                                     "<p>Plazo: hasta el 30 de noviembre de 2026</p>")]
    html = '<a href="/jobs/1249113">New job: Consultant IDB</a><a href="/about">About</a>'
    assert watch.extract_links(html, "https://www.impactpool.org/countries/Bolivia", link_pattern=r"/jobs/\d+") == [
        ("https://www.impactpool.org/jobs/1249113", "New job: Consultant IDB")]


def test_publish_parcial_keeps_unscored(tmp_path):
    import json as _json

    from jobagent.models import job_to_dict
    from jobagent.plan_mode import publish
    (tmp_path / "state").mkdir()
    a = Job(source="t", url="https://x/a", title="A", description="d" * 300, flags=["vigencia:abierta"])
    b = Job(source="t", url="https://x/b", title="B", description="d" * 300)
    (tmp_path / "state/pending.json").write_text(_json.dumps(
        {"stats": {}, "found": [job_to_dict(a), job_to_dict(b)], "candidates": [a.key, b.key]}))
    (tmp_path / "state/scores.json").write_text(_json.dumps([{"id": a.key, "score": 80, "verdict": "postular_ya"}]))
    out = publish(tmp_path, {"agente": {"confianza_minima": 0}}, parcial=True)
    assert out["recomendadas"] == 1 and out["pendientes"] == 1
    left = _json.loads((tmp_path / "state/pending.json").read_text())
    assert left["candidates"] == [b.key] and len(left["found"]) == 1


def test_curated_never_takes_all_slots_but_fills_leftovers():
    from jobagent.filters import select_candidates
    vig = [Job(source="vigia:R", url=f"https://v/{i}", title="t") for i in range(20)]
    board = [Job(source="linkedin", url=f"https://b/{i}", title="t") for i in range(20)]
    out = select_candidates(vig + board, total=10, max_curated=20)
    assert sum(j.source == "linkedin" for j in out) == 5 and len(out) == 10
    out = select_candidates(vig + board[:2], total=10, max_curated=20)  # pocos portales: el vigía completa
    assert len(out) == 10 and sum(j.source == "linkedin" for j in out) == 2


def test_find_emails_skips_non_apply_addresses():
    from jobagent.http import find_emails
    assert find_emails("Escribe a rrhh@bid.org o accommodations@iadb.org, noreply@x.com") == ["rrhh@bid.org"]


def _fake_http(html, status=200):
    from types import SimpleNamespace
    resp = SimpleNamespace(status_code=status, headers={"content-type": "text/html"}, content=html.encode(), text=html)
    return SimpleNamespace(get=lambda url: resp)


def test_validate_detects_closed_and_expired():
    from datetime import datetime, timezone
    from jobagent.validate import validate
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    j = Job(source="web:x", url="https://www.impactpool.org/jobs/1230232", title="UNICEF")
    page = "<p>Consultant level Speaks Spanish Application deadline: August 13, 2026 Closed Summary by Impactpool</p>"
    assert validate(j, _fake_http(page), now=now) == "cerrada"
    j2 = Job(source="web:x", url="https://x/2", title="T")
    assert validate(j2, _fake_http("<p>Plazo: hasta el 10 de octubre de 2026</p>"), now=now) == "cerrada"
    j3 = Job(source="web:x", url="https://x/3", title="T")
    assert validate(j3, _fake_http("<p>Application deadline: November 27, 2026 Closing soon Apply</p>"), now=now) == "abierta"
    assert j3.valid_through.day == 27
    j4 = Job(source="web:x", url="https://x/4", title="T")
    assert validate(j4, _fake_http("<p>Sin fechas</p>"), now=now) == "no_verificada"
    j5 = Job(source="web:x", url="https://x/5", title="T")
    assert validate(j5, _fake_http("", status=404), now=now) == "no_verificada"


def test_publish_only_recommends_verified_open(tmp_path):
    import json as _json

    from jobagent.models import job_to_dict
    from jobagent.plan_mode import publish
    (tmp_path / "state").mkdir()
    ok = Job(source="t", url="https://x/ok", title="OK", flags=["vigencia:abierta"])
    unk = Job(source="t", url="https://x/unk", title="UNK", flags=["vigencia:no_verificada"])
    (tmp_path / "state/pending.json").write_text(_json.dumps(
        {"stats": {}, "found": [job_to_dict(ok), job_to_dict(unk)], "candidates": [ok.key, unk.key]}))
    (tmp_path / "state/scores.json").write_text(_json.dumps(
        [{"id": ok.key, "score": 80, "verdict": "postular_ya"}, {"id": unk.key, "score": 90, "verdict": "postular_ya"}]))
    out = publish(tmp_path, {"agente": {"confianza_minima": 0}})
    assert [t["titulo"] for t in out["top"]] == ["OK"]
    rows = _json.loads((tmp_path / "output/sheet_rows.json").read_text())
    assert any(r[-1].startswith("SIN VERIFICAR") for r in rows)


def test_validate_flags_ghost_jobs_with_auto_renewed_deadline():
    from datetime import datetime, timezone
    from jobagent.validate import validate
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    page = ('<script type="application/ld+json">{"@type":"JobPosting","datePosted":"2026-03-31T14:03:33Z",'
            '"validThrough":"2026-12-23T23:59:59Z"}</script><p>Fecha de publicación 31 mar 2026 Vigente hasta 23 dic 2026</p>')
    j = Job(source="web:x", url="https://cazvid.com/empleo/x", title="T")
    assert validate(j, _fake_http(page), now=now) == "cerrada"
    assert "oferta_fantasma_publicada_hace_mas_de_60_dias" in j.flags


def test_validate_audit_fixes_never_false_open():
    """Hallazgos de la auditoría del 24-11-2026: ninguno de estos casos puede salir "abierta"."""
    from datetime import datetime, timezone
    from jobagent.filters import merge_duplicates
    from jobagent.validate import validate
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    casos = [
        "<p>Plazo de postulación: 10 de noviembre de 2026. Contrato hasta el 31 de diciembre de 2027.</p>",
        "<p>Inicio de labores: 15 de diciembre de 2026</p>",
        "<p>This role has been filled. Posted 3 days ago</p>",
        "<p>Applications have closed. Posted 2 days ago</p>",
    ]
    for i, page in enumerate(casos):
        j = Job(source="web:x", url=f"https://x/a{i}", title="T")
        assert validate(j, _fake_http(page), now=now) != "abierta", page
    j = Job(source="web:x", url="https://x/naive", title="T", posted_at=datetime(2026, 11, 20))
    assert validate(j, _fake_http("<p>Analista</p>"), now=now) == "abierta"  # fecha sin zona ya no se cae
    a = Job(source="trabajito", url="https://x/1", title="Analista")
    b = Job(source="trabajito", url="https://x/2", title="Analista")
    assert len(merge_duplicates([a, b])) == 2  # sin empresa no se pisan
