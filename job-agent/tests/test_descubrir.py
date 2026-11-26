"""Descubrimiento de páginas de empleo, modo cambio del vigía y filtro de título (26-11-2026)."""
from jobagent.descubrir import patron
from jobagent.filters import titulo_no_cumple
from jobagent.models import Job
from jobagent.sources.watch import changed_job
from jobagent.store import url_key

PROPIOS = ["financ", "econom", "administracion", "contadur", "auditor", "comercial"]


def test_patron_bcb_y_menus():
    bcb = [f"https://registros.bcb.gob.bo/postulantes/convocatoria/{n}" for n in (7, 8, 9)]
    pat = patron(bcb, "https://registros.bcb.gob.bo/postulantes/convocatorias")
    assert pat and "convocatoria" in pat
    menus = ["https://www.hansa.com.bo/automotriz/repuestos.php", "https://www.hansa.com.bo/automotriz/camiones.php"]
    assert patron(menus, "https://www.hansa.com.bo/oportunidades_de_trabajo.php") is None


def test_cambio_primera_foto_y_luego_solo_lo_nuevo():
    page = {"url": "https://x.bo/trabaja-con-nosotros", "name": "X"}
    est = {}
    html1 = "<p>Bienvenido a nuestra bolsa de trabajo</p><p>Envíanos tu hoja de vida al correo</p>"
    assert changed_job(page, html1, est) is None  # primera visita: sólo la foto
    assert changed_job(page, html1, est) is None  # sin cambios
    html2 = html1 + "<p>Analista Financiero Senior - La Paz, postulaciones hasta el 5 de diciembre de 2026</p>"
    j = changed_job(page, html2, est)
    assert j and "Analista Financiero" in j.title and "Bienvenido" not in j.description
    assert j.url.startswith(page["url"] + "#cambio-")


def test_cambio_tiene_id_propio_por_fecha():
    a, b = Job(source="s", url="https://x.bo/e#cambio-2026-11-26", title="t"), Job(source="s", url="https://x.bo/e#cambio-2026-12-03", title="t")
    assert a.key != b.key and url_key(a.url) != url_key(b.url)
    assert url_key("https://x.bo/e?utm=1#arriba") == "https://x.bo/e"


def test_titulo():
    bcb = ("Formación académica Título en Provisión Nacional o Título Profesional a nivel Licenciatura en Ingeniería "
           "de Sistemas o Informática o Ingeniería Electrónica.")
    assert titulo_no_cumple(bcb, PROPIOS)
    eco = "Formación académica: Licenciatura en Economía, Ingeniería Financiera, Administración o ramas afines."
    assert not titulo_no_cumple(eco, PROPIOS)
    assert not titulo_no_cumple("Buscamos analista con experiencia en Power BI", PROPIOS)  # no dice título
