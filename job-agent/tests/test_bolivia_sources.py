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
