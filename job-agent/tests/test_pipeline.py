import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from jobagent import scorer
from jobagent.filters import merge_duplicates, prefilter
from jobagent.models import Job
from jobagent.sources import computrabajo, relative_date, trabajito
from jobagent.verify import verify

NOW = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
PROFILE = {
    "keywords": ["analista", "economista"], "roles_objetivo": ["Analista económico"],
    "excluir_titulo": ["vendedor"], "ciudades": ["La Paz"], "acepta_remoto": True,
    "paises_region": [], "agente": {"max_antiguedad_dias": 21},
}


def job(**kw):
    base = dict(source="t", url="https://x.bo/1", title="Analista económico", company="ACME SRL",
                location="La Paz, La Paz", country="BO", posted_at=NOW - timedelta(days=2),
                description="Buscamos analista económico con experiencia en presupuesto público. " * 10)
    base.update(kw)
    return Job(**base)


def test_verify_scam_and_stale():
    good = verify(job(), now=NOW, check_dns=False)
    assert good.trust >= 60 and "reciente" in good.flags
    scam = verify(job(description="Gana Bs 5000 por semana desde casa. Debes pagar la cuota de inscripción al curso. " * 5),
                  now=NOW, check_dns=False)
    assert any(f.startswith("ESTAFA?") for f in scam.flags) and scam.trust < 50
    old = verify(job(posted_at=NOW - timedelta(days=60), valid_through=NOW - timedelta(days=1)), now=NOW, check_dns=False)
    assert "antigua" in old.flags and "vencida" in old.flags and old.trust < 30


def test_prefilter_excludes_and_ranks():
    jobs = [
        job(url="https://x.bo/1", title="Vendedor mayorista"),
        job(url="https://x.bo/2", title="Analista económico senior"),
        job(url="https://x.bo/3", title="Contador", description="economista deseable " * 30),
        job(url="https://x.bo/4", title="Analista", location="Santa Cruz", remote=False),
        job(url="https://x.bo/5", title="Analista", location="Remoto", country="", remote=True),
    ]
    kept = prefilter(jobs, PROFILE)
    titles = [j.title for j in kept]
    assert "Vendedor mayorista" not in titles  # excluido por título
    assert all(j.location != "Santa Cruz" for j in kept)  # fuera de ciudad y no remoto
    assert titles[0] == "Analista económico senior"  # el rol objetivo queda primero
    assert any(j.remote for j in kept)


def test_merge_duplicates_across_portals():
    a = job(source="trabajito", url="https://a.bo/1", title="Analista Económico - La Paz", company="ACME S.R.L.")
    b = job(source="computrabajo", url="https://b.bo/9", title="ANALISTA ECONOMICO", company="Acme SRL",
            apply_emails=["rrhh@acme.bo"])
    out = merge_duplicates([a, b])
    assert len(out) == 1 and out[0].also_on == ["computrabajo"] and out[0].apply_emails == ["rrhh@acme.bo"]


def test_relative_date():
    assert relative_date("Hace 9 horas", NOW) == NOW - timedelta(hours=9)
    assert relative_date("Ayer", NOW) == NOW - timedelta(days=1)
    assert relative_date("Hace más de 30 días", NOW) == NOW - timedelta(days=30)


def test_trabajito_detail_jsonld():
    ld = {"@context": "https://schema.org/", "@type": "JobPosting", "title": "ANALISTA  X",
          "description": "<p>Enviar CV a rrhh@acme.com.bo</p>", "datePosted": "2026-11-17T15:04:32-04:00",
          "validThrough": "2026-12-18T23:59:59-04:00", "hiringOrganization": {"name": "acme", "sameAs": "https://acme.bo"},
          "jobLocation": {"@type": "Place", "address": {"addressLocality": "La Paz", "addressRegion": "La Paz", "addressCountry": "BO"}}}
    html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    j = trabajito.parse_detail("https://www.trabajito.com.bo/trabajo/la-paz/x-1", html)
    assert j.title == "ANALISTA X" and j.company == "acme" and j.apply_emails == ["rrhh@acme.com.bo"]
    assert j.posted_at.year == 2026 and j.location == "La Paz, La Paz"


def test_computrabajo_list():
    html = """<article><h2><a class="js-o-link" href="/ofertas-de-trabajo/oferta-x-ABC#lc=1">Analista</a></h2>
      <p><span class="i_verificada"></span><a offer-grid-article-company-url href="#">ACME</a></p>
      <p><span>El Alto, La Paz</span></p><div><span><span class="icon i_salary"></span>3.300,00 $ (Mensual)</span></div>
      <p>Hace 9 horas</p></article>"""
    [j] = computrabajo.parse_list(html)
    assert j.url == "https://bo.computrabajo.com/ofertas-de-trabajo/oferta-x-ABC"
    assert j.company == "ACME" and j.location == "El Alto, La Paz" and "3.300" in j.salary
    assert "empresa_verificada_portal" in j.flags and j.posted_at is not None


def test_score_jobs_with_fake_claude(monkeypatch):
    j1, j2 = job(url="https://x.bo/a"), job(url="https://x.bo/b")
    payload = {"results": [
        {"id": j1.key, "score": 88, "verdict": "postular_ya", "reasons": ["r"], "gaps": [], "red_flags": [], "summary": "s"},
        {"id": j2.key, "score": 30, "verdict": "descartar", "reasons": [], "gaps": ["g"], "red_flags": ["pide dinero"], "summary": "s"},
    ]}
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0))

    fake = SimpleNamespace(messages=SimpleNamespace(create=create), beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(scorer.anthropic, "Anthropic", lambda: fake)
    j2.trust = 60
    scorer.score_jobs([j1, j2], PROFILE, "CV", "claude-opus-5-5")
    assert (j1.score, j1.verdict) == (88, "postular_ya")
    assert j2.score == 30 and j2.trust == 50  # red flag de Claude baja la confianza
    sent = calls[0]
    assert sent["fallbacks"] == "default" and sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
