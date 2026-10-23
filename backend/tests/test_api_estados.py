import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app
from app.models import Comprobante, Lote
from tests.test_bbva import estado_sintetico


def _pdf():
    return {"archivos": ("estado.pdf", estado_sintetico(), "application/pdf")}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        for clave, nombre in (("40012", "BBVA MEXICO"), ("40127", "AZTECA"), ("40072", "BANORTE"), ("90722", "MERCADO PAGO")):
            assert c.post("/api/bancos", json={"nombre": nombre, "clave": clave}).status_code in (201, 409)
        bbva_id = next(b["id"] for b in c.get("/api/bancos").json() if b["clave"] == "40012")
        c.post(
            "/api/cuentas",
            json={"numero": "4152313818146602", "tipo": "tarjeta", "banco_receptor_id": bbva_id, "titular": "William BBVA"},
        )
        yield c


@pytest.fixture(scope="module")
def comprobantes(client):
    with Session(engine) as s:
        lote = Lote(nombre="conciliación")
        s.add(lote)
        s.flush()
        datos = {
            # OCR leyó "1" donde el estado de cuenta tiene "I".
            "rastreo": dict(fecha="2025-12-20", monto="200.00", clave_rastreo="2512200109810410251"),
            "folio": dict(fecha="2025-12-21", monto="1500.00", folio="44395732"),
            "monto_fecha": dict(fecha="2025-12-31", monto="400.00"),
            "ninguno": dict(fecha="2025-12-25", monto="999.00"),
        }
        ids = {}
        for nombre, campos in datos.items():
            c = Comprobante(lote_id=lote.id, archivo=f"{nombre}.png", nombre_original=nombre, estado="incompleto", **campos)
            s.add(c)
            s.flush()
            ids[nombre] = c.id
        s.commit()
        return lote.id, ids


def _por_nombre(client, lote_id):
    return {c["nombre_original"]: c for c in client.get(f"/api/lotes/{lote_id}").json()["comprobantes"]}


def test_flujo_conciliacion(client, comprobantes):
    lote_id, ids = comprobantes

    r = client.post("/api/estados-cuenta", files=_pdf())
    assert r.status_code == 201
    carga = r.json()[0]
    assert carga["error"] is None and carga["nuevos"] == 6
    assert carga["estado"]["numero_cuenta"] == "1234567890"
    assert carga["estado"]["conciliados"] == 3

    # El mismo estado de cuenta no se carga dos veces.
    assert "Ya está cargado" in client.post("/api/estados-cuenta", files=_pdf()).json()[0]["error"]

    c = _por_nombre(client, lote_id)
    assert c["rastreo"]["conciliacion"] == "encontrado"
    assert c["rastreo"]["conciliacion_diferencias"]["clave_rastreo"] == "251220010981041025I"
    assert c["rastreo"]["movimiento"]["referencia"] == "0114046014"
    assert c["folio"]["conciliacion"] == "encontrado"
    assert c["monto_fecha"]["conciliacion"] == "posible"
    assert c["ninguno"]["conciliacion"] == "no_encontrado"

    # Completar con los datos del estado de cuenta corrige la clave, emisor, receptor y cuenta.
    a = client.post(f"/api/comprobantes/{ids['rastreo']}/aplicar-movimiento", json={}).json()
    assert a["clave_rastreo"] == "251220010981041025I"
    assert a["emisor_clave"] == "40127"
    assert a["receptor_clave"] == "40012"
    assert a["cuenta"] is not None
    assert a["fuente"]["clave_rastreo"] == "estado_cuenta"
    assert a["fuente"]["receptor_clave"] == "estado_cuenta"
    assert a["fuente"]["cuenta"] == "estado_cuenta"
    assert a["conciliacion"] == "encontrado" and a["conciliacion_diferencias"] == {}

    # Un movimiento ya conciliado no se puede aplicar a otro comprobante.
    mov_folio = c["folio"]["movimiento"]["id"]
    r = client.post(f"/api/comprobantes/{ids['ninguno']}/aplicar-movimiento", json={"movimiento_id": mov_folio})
    assert r.status_code == 409

    # Editar el comprobante vuelve a conciliar.
    e = client.patch(f"/api/comprobantes/{ids['ninguno']}", json={"monto": "450.00", "fecha": "2025-12-23"}).json()
    assert e["conciliacion"] == "posible"
    mov_posible = e["movimiento"]["id"]
    aplicado = client.post(
        f"/api/comprobantes/{ids['ninguno']}/aplicar-movimiento", json={"movimiento_id": mov_posible}
    ).json()
    assert aplicado["folio"] == "0047207110" and aplicado["fuente"]["folio"] == "estado_cuenta"
    assert aplicado["conciliacion"] == "encontrado"
    desvinculado = client.post(f"/api/comprobantes/{ids['ninguno']}/desvincular-movimiento").json()
    assert desvinculado["folio"] is None
    assert desvinculado["conciliacion"] == "posible"


def test_movimientos_filtros(client, comprobantes):
    estado_id = client.get("/api/estados-cuenta").json()[0]["id"]
    total = lambda **p: client.get("/api/movimientos", params={"estado_cuenta": estado_id, **p}).json()["total"]
    assert total() == 6
    assert total(tipo="cargos") == 3
    assert total(tipo="spei_recibido") == 2
    assert total(q="0044395732") == 1
    assert total(q="1,500.00") == 1
    assert total(conciliado="true") == 4
    assert total(conciliado="false") == 2


def test_incidencias_incluyen_conciliacion(client, comprobantes):
    lote_id, _ = comprobantes
    csv = client.get(f"/api/lotes/{lote_id}/incidencias.csv").content.decode("utf-8-sig")
    assert "estado_de_cuenta" in csv.splitlines()[0]
    assert "Encontrado" in csv


def test_eliminar_estado_libera_comprobantes(client, comprobantes):
    lote_id, _ = comprobantes
    for e in client.get("/api/estados-cuenta").json():
        assert client.delete(f"/api/estados-cuenta/{e['id']}").status_code == 204
    c = _por_nombre(client, lote_id)
    assert c["rastreo"]["conciliacion"] == "" and c["rastreo"]["movimiento"] is None


def test_pdf_invalido(client):
    r = client.post("/api/estados-cuenta", files={"archivos": ("x.pdf", b"no es pdf", "application/pdf")})
    assert r.json()[0]["error"]
    r = client.post("/api/estados-cuenta", files={"archivos": ("x.txt", b"hola", "text/plain")})
    assert "PDF" in r.json()[0]["error"]
