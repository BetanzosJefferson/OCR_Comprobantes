import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import app
from app.ocr.engine import tesseract_disponible

FUENTES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _imagen_comprobante(lineas, oscuro=False) -> bytes:
    fuente_path = next((f for f in FUENTES if Path(f).exists()), None)
    fuente = ImageFont.truetype(fuente_path, 34) if fuente_path else ImageFont.load_default()
    fondo, tinta = ((20, 20, 30), (240, 240, 240)) if oscuro else ((255, 255, 255), (20, 20, 20))
    img = Image.new("RGB", (900, 80 + 60 * len(lineas)), fondo)
    d = ImageDraw.Draw(img)
    for i, linea in enumerate(lineas):
        d.text((40, 40 + 60 * i), linea, fill=tinta, font=fuente)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        b1 = c.post("/api/bancos", json={"nombre": "BBVA MEXICO", "clave": "40012", "alias": ["BBVA", "BANCOMER"]})
        b2 = c.post("/api/bancos", json={"nombre": "BANCO DEMO", "clave": "40102", "alias": ["DEMOBANK"]})
        assert b1.status_code == 201 and b2.status_code == 201
        r = c.post(
            "/api/cuentas",
            json={"numero": "55 3330 2929", "tipo": "celular", "banco_receptor_id": b2.json()["id"], "titular": "Yo"},
        )
        assert r.status_code == 201 and r.json()["numero"] == "5533302929"
        yield c


def test_catalogos_validaciones(client):
    assert client.post("/api/bancos", json={"nombre": "X", "clave": "40012"}).status_code == 409
    assert client.post("/api/bancos", json={"nombre": "X", "clave": "ABC"}).status_code == 422
    csv = "clave,nombre,alias\n40014,SANTANDER,SANTANDER|SANT\n,SIN CLAVE,\n"
    r = client.post("/api/bancos/import", files={"archivo": ("b.csv", csv, "text/csv")})
    assert r.json()["creados"] == 1 and len(r.json()["errores"]) == 1


@pytest.mark.skipif(not tesseract_disponible(), reason="Tesseract no instalado")
def test_flujo_completo(client):
    completo = _imagen_comprobante(
        [
            "BBVA",
            "Comprobante de transferencia",
            "Fecha de operacion: 06/09/2018",
            "Importe: $1,200.50 MXN",
            "Cuenta destino: 5533302929",
            "Banco destino: DEMOBANK",
            "Clave de rastreo: 11FEF28A36F",
        ]
    )
    incompleto = _imagen_comprobante(["BBVA", "Transferencia enviada", "Importe: $500.00"], oscuro=True)

    r = client.post(
        "/api/lotes",
        files=[("archivos", ("a.png", completo, "image/png")), ("archivos", ("b.png", incompleto, "image/png"))],
        data={"nombre": "Prueba"},
    )
    assert r.status_code == 201
    lote_id = r.json()["id"]

    detalle = client.get(f"/api/lotes/{lote_id}").json()
    a, b = detalle["comprobantes"]
    assert a["estado"] == "completo", (a["errores"], a["texto_ocr"])
    assert (a["fecha"], a["clave_rastreo"], a["emisor_clave"], a["receptor_clave"], a["cuenta"], a["monto"]) == (
        "2018-09-06", "11FEF28A36F", "40012", "40102", "5533302929", "1200.50",
    )
    assert b["estado"] == "incompleto"
    assert {"fecha", "clave_rastreo", "cuenta"} <= set(b["errores"])

    txt = client.get(f"/api/lotes/{lote_id}/export.txt")
    assert txt.text == "2018-09-06,11FEF28A36F,40012,40102,5533302929,1200.50\n"
    assert txt.headers["x-omitidos"] == "1"
    exportado = client.get(f"/api/lotes/{lote_id}/export.json").json()
    assert exportado == [{"id": "a", "date": "2018-09-06", "key": "11FEF28A36F", "wallet": "5533302929"}]

    # Captura manual de lo que faltaba.
    r = client.patch(
        f"/api/comprobantes/{b['id']}",
        json={"fecha": "07/09/2018", "clave_rastreo": "ABC123", "cuenta": "5533302929", "receptor_clave": "40102"},
    )
    assert r.status_code == 200
    b = r.json()
    assert b["fecha"] == "2018-09-07" and b["fuente"]["fecha"] == "manual"
    assert b["errores"] == {}
    r = client.patch(f"/api/comprobantes/{b['id']}", json={"estado": "revisado"})
    assert r.json()["estado"] == "revisado"

    lineas = client.get(f"/api/lotes/{lote_id}/export.txt").text.splitlines()
    assert lineas[1] == "2018-09-07,ABC123,40012,40102,5533302929,500.00"

    # Incidencia: se excluye del TXT y aparece en el reporte.
    client.patch(f"/api/comprobantes/{b['id']}", json={"estado": "incidencia", "comentario": "Foto borrosa"})
    assert len(client.get(f"/api/lotes/{lote_id}/export.txt").text.splitlines()) == 1
    reporte = client.get(f"/api/lotes/{lote_id}/incidencias.csv").content.decode("utf-8-sig")
    assert "b.png" in reporte and "Foto borrosa" in reporte

    # Duplicado: el mismo comprobante subido otra vez queda bloqueado.
    r = client.post(f"/api/lotes/{lote_id}/comprobantes", files=[("archivos", ("c.png", completo, "image/png"))])
    c = client.get(f"/api/lotes/{lote_id}").json()["comprobantes"][-1]
    assert "Duplicado" in c["errores"].get("clave_rastreo", "")
    assert not c["exportable"]


def test_revisado_requiere_datos_validos(client):
    lote = client.post(
        "/api/lotes", files=[("archivos", ("x.png", _imagen_comprobante(["hola"]), "image/png"))]
    ).json()
    comp = client.get(f"/api/lotes/{lote['id']}").json()["comprobantes"][0]
    r = client.patch(f"/api/comprobantes/{comp['id']}", json={"estado": "revisado"})
    assert r.status_code == 422


def test_formato_no_soportado(client):
    r = client.post("/api/lotes", files=[("archivos", ("x.pdf", b"%PDF", "application/pdf"))])
    assert r.status_code == 422
