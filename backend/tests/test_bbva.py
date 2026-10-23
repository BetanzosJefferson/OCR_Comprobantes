import io

import pytest

from app.estados_cuenta.bbva import EstadoCuentaInvalido, parsear_pdf
from tests.pdf_sintetico import Hoja, pdf

CUENTA = "1234567890"


def estado_sintetico(total_cargos: str = "3,567.00") -> bytes:
    p1 = Hoja().encabezado_pagina(1, 2, CUENTA)
    p1.renglon("Periodo DEL 15/12/2025 AL 14/01/2026", x=400)
    p1.renglon("No. Cuenta CLABE 012 180 01234567890 1", x=400)
    p1.renglon("Detalle de Movimientos Realizados", x=21).columnas()
    p1.movimiento("20/DIC 20/DIC", "SPEI RECIBIDOAZTECA", abono="200.00")
    p1.renglon("1234567Pago renta Referencia 0114046014 127")
    p1.renglon("00127180001234567890")
    p1.renglon("251220010981041025I")
    p1.renglon("PEREZ LOPEZ JUAN")
    p1.movimiento("21/DIC 22/DIC", "PAGO CUENTA DE TERCERO", cargo="1,500.00")
    p1.renglon("BNET 1500000001 Transf a ANA Referencia 0044395732")
    p1.movimiento("23/DIC 23/DIC", "PAGO CUENTA DE TERCERO", abono="450.00")
    p1.renglon("BNET 1500000002 pasaje Referencia 0047207110")
    p1.movimiento("31/DIC 31/DIC", "SPEI RECIBIDOMercado Pago", abono="400.00")
    p1.renglon("7605883ANTICIPO Referencia 0113976337 722")
    p1.renglon("00722969020700000001")
    p1.pie()

    # El último movimiento de la página 1 continúa en la página 2.
    p2 = Hoja().encabezado_pagina(2, 2, CUENTA)
    p2.renglon("CPO177147605883")
    p2.renglon("MARIA GARCIA")
    p2.movimiento("02/ENE 02/ENE", "SPEI ENVIADO BANORTE", cargo="2,000.00")
    p2.renglon("0201260renta Referencia 0085714998 072")
    p2.renglon("00072180000000000001")
    p2.renglon("MBAN01002601020085714998")
    p2.renglon("Pedro")
    p2.movimiento("03/ENE 03/ENE", "OXXO LOS SAUCES", cargo="67.00", saldo="1,000.00")
    p2.renglon("RFC: CCO 8605231N4 21:34 AUT: 822216 Referencia ******5872")
    p2.renglon("Total de Movimientos", x=21)
    p2.renglon(f"TOTAL IMPORTE CARGOS {total_cargos} TOTAL MOVIMIENTOS CARGOS 3", x=21)
    p2.renglon("TOTAL IMPORTE ABONOS 1,050.00 TOTAL MOVIMIENTOS ABONOS 3", x=21)
    p2.renglon("Estado de cuenta de Apartados Vigentes", x=21)
    p2.renglon("01/ENE 01/ENE NO ES UN MOVIMIENTO", x=21, abono="9.99")
    p2.pie()
    return pdf([p1.textos, p2.textos])


@pytest.fixture(scope="module")
def estado():
    return parsear_pdf(io.BytesIO(estado_sintetico()))


def test_encabezado(estado):
    assert estado.numero_cuenta == CUENTA
    assert estado.clabe == "012180012345678901"
    assert (estado.periodo_inicio, estado.periodo_fin) == ("2025-12-15", "2026-01-14")
    assert estado.producto == "Libreton Basico Cuenta Digital"
    assert (estado.total_cargos, estado.total_abonos) == ("3567.00", "1050.00")
    assert estado.paginas == 2
    assert estado.advertencias == []


def test_movimientos_y_tipos(estado):
    assert [m.tipo for m in estado.movimientos] == [
        "spei_recibido", "pago_tercero", "pago_tercero", "spei_recibido", "spei_enviado", "otro",
    ]


def test_cargo_o_abono_por_columna(estado):
    # "PAGO CUENTA DE TERCERO" puede ser cargo o abono: lo decide la posición del importe.
    _, pago_enviado, pago_recibido, *_ = estado.movimientos
    assert (pago_enviado.cargo, pago_enviado.abono) == ("1500.00", None)
    assert (pago_recibido.cargo, pago_recibido.abono) == (None, "450.00")
    oxxo = estado.movimientos[-1]
    assert (oxxo.cargo, oxxo.abono) == ("67.00", None)  # los saldos no se confunden con importes


def test_spei_recibido(estado):
    m = estado.movimientos[0]
    assert m.fecha_operacion == "2025-12-20"
    assert m.banco_texto == "AZTECA"
    assert m.referencia == "0114046014" and m.referencia_sufijo == "127"
    assert m.referencia_numerica == "1234567"
    assert m.concepto == "Pago renta"
    assert m.cuenta_contraparte == "127180001234567890"
    assert m.clave_rastreo == "251220010981041025I"
    assert m.nombre_contraparte == "PEREZ LOPEZ JUAN"


def test_pago_tercero(estado):
    m = estado.movimientos[1]
    assert (m.fecha_operacion, m.fecha_liquidacion) == ("2025-12-21", "2025-12-22")
    assert m.cuenta_contraparte == "1500000001"
    assert m.concepto == "Transf a ANA"
    assert m.referencia == "0044395732"
    assert m.clave_rastreo is None


def test_bloque_partido_entre_paginas(estado):
    m = estado.movimientos[3]
    assert m.pagina == 1
    assert m.clave_rastreo == "CPO177147605883"
    assert m.nombre_contraparte == "MARIA GARCIA"


def test_anio_al_cruzar_diciembre_enero(estado):
    enviado = estado.movimientos[4]
    assert enviado.fecha_operacion == "2026-01-02"
    assert enviado.clave_rastreo == "MBAN01002601020085714998"
    assert enviado.nombre_contraparte == "Pedro"


def test_ignora_lo_que_sigue_al_total(estado):
    assert all(m.descripcion != "NO ES UN MOVIMIENTO" for m in estado.movimientos)


def test_advierte_si_los_totales_no_cuadran():
    e = parsear_pdf(io.BytesIO(estado_sintetico(total_cargos="9,999.00")))
    assert any("no coincide" in a for a in e.advertencias)


def test_pdf_escaneado():
    with pytest.raises(EstadoCuentaInvalido, match="escaneado"):
        parsear_pdf(io.BytesIO(pdf([[]])))


def test_pdf_que_no_es_bbva():
    with pytest.raises(EstadoCuentaInvalido, match="BBVA"):
        parsear_pdf(io.BytesIO(pdf([[(50, 50, "Estado de cuenta de otro banco")]])))
