import json
from email.message import EmailMessage
from types import SimpleNamespace

from jobagent.sources import email_alerts, explorer, linkedin


def test_explorer_only_accepts_urls_seen_in_search_results(monkeypatch):
    real = "https://www.undp.org/es/bolivia/vacantes/consultor-economista-123"
    invented = "https://www.embajada-falsa.bo/empleo/999"
    payload = {"jobs": [
        {"url": real, "title": "Consultor/a economista", "organization": "PNUD", "location": "La Paz, Bolivia",
         "remote": False, "posted_date": "2026-11-15", "deadline": "2026-12-01", "description": "Requisitos...",
         "contact_email": ""},
        {"url": invented, "title": "Asistente", "organization": "Embajada X", "location": "La Paz", "remote": False,
         "posted_date": "", "deadline": "", "description": "", "contact_email": ""},
    ]}
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="server_tool_use"),
            SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url=real + "?utm=1")]),
            SimpleNamespace(type="text", text=json.dumps(payload)),
        ])

    fake = SimpleNamespace(messages=SimpleNamespace(create=create), beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(explorer.anthropic, "Anthropic", lambda: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    http = SimpleNamespace(s=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=200)))
    jobs = explorer.fetch({"themes": ["organismos_internacionales"]}, {"keywords": ["economista"]}, http, lambda u: False)
    assert [j.url for j in jobs] == [real]  # la URL inventada se descarta
    assert jobs[0].source == "web:organismos_internacionales" and jobs[0].valid_through.day == 1
    tool = calls[0]["tools"][0]
    assert tool["type"] == "web_search_20260209" and tool["max_uses"] == 5


def test_explorer_drops_dead_links(monkeypatch):
    url = "https://ong.org/vacante/1"
    payload = {"jobs": [{"url": url, "title": "T", "organization": "O", "location": "La Paz", "remote": False,
                         "posted_date": "", "deadline": "", "description": "d", "contact_email": ""}]}
    resp = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url=url)]),
        SimpleNamespace(type="text", text=json.dumps(payload))])
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **k: resp)))
    monkeypatch.setattr(explorer.anthropic, "Anthropic", lambda: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    http = SimpleNamespace(s=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(status_code=404)))
    assert explorer.fetch({"themes": ["ong_y_fundaciones"]}, {}, http, lambda u: False) == []


def test_linkedin_parse_search_and_detail():
    search = """<li><div class="base-card" data-entity-urn="urn:li:jobPosting:4491086217">
      <h3 class="base-search-card__title">Analista de riesgos</h3><h4 class="base-search-card__subtitle">Banco Unión</h4>
      <span class="job-search-card__location">La Paz, Bolivia</span><time datetime="2026-11-14"></time></div></li>"""
    assert linkedin.parse_search(search) == [("4491086217", "Analista de riesgos", "Banco Unión", "La Paz, Bolivia", "2026-11-14")]
    detail = """<h2 class="top-card-layout__title">Analista de riesgos</h2>
      <a class="topcard__org-name-link" href="https://bo.linkedin.com/company/bu?trk=x">Banco Unión</a>
      <span class="topcard__flavor--bullet">La Paz, Bolivia</span><span class="posted-time-ago__text">3 days ago</span>
      <div class="description__text">Enviar CV a rrhh@bancounion.com.bo</div>"""
    j = linkedin.parse_detail("4491086217", detail)
    assert j.url == "https://www.linkedin.com/jobs/view/4491086217" and j.company == "Banco Unión"
    assert j.apply_emails == ["rrhh@bancounion.com.bo"] and j.posted_at is not None and j.country == "BO"


def test_email_alert_link_extraction():
    msg = EmailMessage()
    msg["Subject"] = "Nuevas ofertas: economista"
    msg.set_content("x")
    msg.add_alternative(
        '<a href="https://www.linkedin.com/comm/jobs/view/4488095943/?trackingId=abc">Analista de Operaciones</a>'
        '<a href="https://www.trabajando.com.bo/trabajo-empleo/analista-economico/trabajo/12345">Analista económico</a>'
        '<a href="https://www.linkedin.com/jobs/search?keywords=x">Ver todas</a>', subtype="html")
    html = email_alerts._body(msg)
    links = list(dict.fromkeys(email_alerts.JOB_LINK.findall(html)))
    assert any("/jobs/view/4488095943" in l for l in links)
    assert any("trabajando.com.bo/trabajo-empleo/analista-economico" in l for l in links)
    assert not any("jobs/search" in l for l in links)
    anchors = email_alerts._anchor_texts(html)
    assert "Analista económico" in anchors.values()
