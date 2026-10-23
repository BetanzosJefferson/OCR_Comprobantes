import pytest

from app.ocr.extractors import CAMPOS, BancoCat, Catalogo, CuentaCat, extraer, extraer_mejor

CATALOGO = Catalogo(
    bancos=[
        BancoCat("40012", "BBVA MEXICO", ["BBVA", "BANCOMER"]),
        BancoCat("40014", "SANTANDER", ["SANTANDER"]),
        BancoCat("40072", "BANORTE", ["BANORTE"]),
        BancoCat("40058", "BANREGIO", ["BANREGIO"]),
        BancoCat("40102", "BANCO DESTINO DEMO", ["DEMOBANK"]),
        BancoCat("90638", "NU MEXICO", ["NU", "NU MEXICO"]),
        BancoCat("90722", "MERCADO PAGO W", ["MERCADO PAGO"]),
    ],
    cuentas=[
        CuentaCat("5533302929", "40102", "celular"),
        CuentaCat("012180001183597194", "40012", "clabe"),
        CuentaCat("4152313412345678", "40014", "tarjeta"),
    ],
)

BBVA = """
BBVA
Comprobante de transferencia
Fecha de operación: 06/09/2018 14:35:10
Importe: $1,200.50 MXN
Cuenta destino: 5533302929
Banco destino: DEMOBANK
Clave de rastreo: 11FEF28A36F
Referencia numérica: 1234567
Comisión: $0.00
"""

SANTANDER = """
Santander
Transferencia exitosa
20 de octubre de 2026
Monto
$ 3,450.00
Beneficiario: Juan Pérez
Tarjeta ****5678
Clave de Rastreo
SANT20261020123456789
Folio: 998877
"""

NU = """
nu
Transferencia enviada
Enviaste
$750.25
A: Maria Lopez
Cuenta CLABE: 012 180 00118359719 4
Fecha 15 OCT 2026, 10:21 a.m.
Banco origen: NU MEXICO
Clave de rastreo NU39383827HG
"""

INCOMPLETO = """
Mercado Pago
Le transferiste a
Pedro Gomez
$ 500
Fecha 03/02/2025
"""


def test_formato_bbva():
    r = extraer(BBVA, CATALOGO)
    assert r["fecha"].valor == "2018-09-06"
    assert r["clave_rastreo"].valor == "11FEF28A36F"
    assert r["monto"].valor == "1200.50"
    assert r["cuenta"].valor == "5533302929"
    assert r["receptor_clave"].valor == "40102"
    assert r["emisor_clave"].valor == "40012"
    assert all(r[c].confianza >= 0.6 for c in CAMPOS)
    assert r["referencia"].valor == "1234567"


def test_formato_santander_fecha_texto_y_tarjeta_enmascarada():
    r = extraer(SANTANDER, CATALOGO)
    assert r["fecha"].valor == "2026-10-20"
    assert r["monto"].valor == "3450.00"
    assert r["clave_rastreo"].valor == "SANT20261020123456789"
    assert r["cuenta"].valor == "4152313412345678"
    assert r["receptor_clave"].valor == "40014"
    # Emisor y receptor son el mismo banco y no hay etiqueta: se propone con baja confianza.
    assert r["emisor_clave"].valor == "40014"
    assert r["emisor_clave"].confianza < 0.6


def test_formato_nu_clabe_con_espacios():
    r = extraer(NU, CATALOGO)
    assert r["fecha"].valor == "2026-10-15"
    assert r["monto"].valor == "750.25"
    assert r["cuenta"].valor == "012180001183597194"
    assert r["receptor_clave"].valor == "40012"
    assert r["emisor_clave"].valor == "90638"
    assert r["clave_rastreo"].valor == "NU39383827HG"


def test_datos_faltantes_quedan_vacios():
    r = extraer(INCOMPLETO, CATALOGO)
    assert r["fecha"].valor == "2025-02-03"
    assert r["monto"].valor == "500.00"
    assert r["clave_rastreo"].valor is None
    assert r["cuenta"].valor is None
    assert r["receptor_clave"].valor is None
    assert r["emisor_clave"].valor == "90722"


AZTECA_OCR = """
Enviaste a una cuenta
5200.%
19/0ct/2026 13:27:43 (CST)
La Candelaria, Ciudad de México
Cuenta origen
Nomina Grupo Salinas ***7534
Cuenta destino
William
Bbva Bancomer ***G02
Referencia
8146602
Clave de rastreo
2610190113911497121
"""


def test_confusiones_ocr_en_fecha_cuenta_y_monto_superindice():
    cat = Catalogo(
        bancos=CATALOGO.bancos + [BancoCat("40127", "AZTECA", ["BANCO AZTECA", "GRUPO SALINAS"])],
        cuentas=CATALOGO.cuentas + [CuentaCat("4152313400001602", "40012", "tarjeta")],
    )
    r = extraer(AZTECA_OCR, cat)
    assert r["fecha"].valor == "2026-10-19"
    assert r["cuenta"].valor == "4152313400001602"
    assert r["receptor_clave"].valor == "40012"
    assert r["emisor_clave"].valor == "40127"
    # "$" leído como "5": se propone 200.00 pero con baja confianza para revisión.
    assert r["monto"].valor == "200.00"
    assert r["monto"].confianza < 0.6


@pytest.mark.parametrize(
    "linea,esperado",
    [(">200.%", "200.00"), ("$1,500.°°", "1500.00"), ("$350.50", "350.50"), ("S75.oo", "75.00")],
)
def test_monto_superindice(linea, esperado):
    assert extraer(f"Enviaste\n{linea}", CATALOGO)["monto"].valor == esperado


def test_monto_superindice_requiere_etiqueta():
    assert extraer("Hola\n5200.%", CATALOGO)["monto"].valor is None


def test_cuenta_enmascarada_no_acepta_solo_letras():
    cat = Catalogo(cuentas=[CuentaCat("0000000000006808", "40012")])
    assert extraer("Cuenta destino ***GOB", cat)["cuenta"].valor is None


NU_ETIQUETA_PARTIDA = """
Monto $200.00
Número de referencia 191026
Folio QWGLRTFDW
Estatus Aceptada
PA NU3AQRT3Q9Q19GQBM2JDFEIGT
e 9TI
rastreo
Cuenta origen
Referencia interna
Gad6fa3d-4dd8-46a1-8828-177dd78f137
"""


def test_rastreo_tiene_prioridad_sobre_referencia_con_etiqueta_partida():
    r = extraer(NU_ETIQUETA_PARTIDA, CATALOGO)
    assert r["clave_rastreo"].valor == "NU3AQRT3Q9Q19GQBM2JDFEIGT9TI"
    assert r["clave_rastreo"].confianza < 0.6


def test_rastreo_gana_entre_lecturas_aunque_referencia_tenga_mas_confianza():
    solo_referencia = "Número de referencia 191026"
    con_rastreo = "Referencia 191026\nClave de rastreo\nMBAN01002610140012345"
    r = extraer_mejor([solo_referencia, con_rastreo], CATALOGO)
    assert r["clave_rastreo"].valor == "MBAN01002610140012345"


def test_referencia_se_usa_si_no_hay_rastreo_pero_para_revision():
    r = extraer("Número de referencia 191026\nFolio QWGLRT5", CATALOGO)
    assert r["clave_rastreo"].valor == "191026"
    assert r["clave_rastreo"].confianza < 0.6


def test_clave_partida_en_dos_renglones_despues_de_etiqueta():
    r = extraer("Clave de rastreo\nNU3AQRT3Q9Q19GQBM2JDFEIGT\n9TI\nCuenta origen", CATALOGO)
    assert r["clave_rastreo"].valor == "NU3AQRT3Q9Q19GQBM2JDFEIGT9TI"


def test_rastreo_corrige_o_por_cero():
    r = extraer("Clave de rastreo: MBANO1002610140012345", CATALOGO)
    assert r["clave_rastreo"].valor == "MBAN01002610140012345"
    assert extraer("Clave de rastreo: 11FEF28A36F", CATALOGO)["clave_rastreo"].valor == "11FEF28A36F"


def test_cuenta_no_registrada_no_se_acepta():
    r = extraer("Cuenta destino: 9999888877\nMonto $10.00", CATALOGO)
    assert r["cuenta"].valor is None


def test_comision_no_es_monto():
    r = extraer("Comisión $5.00\nImporte transferido $100.00", CATALOGO)
    assert r["monto"].valor == "100.00"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Fecha: 2024-01-31", "2024-01-31"),
        ("Fecha: 31/01/24", "2024-01-31"),
        ("06-SEP-2018", "2018-09-06"),
        ("Oct 5, 2026", "2026-10-05"),
        ("Fecha de aplicación 1 de diciembre del 2025", "2025-12-01"),
        ("Fecha 31/13/2024", None),
    ],
)
def test_formatos_fecha(texto, esperado):
    assert extraer(texto, CATALOGO)["fecha"].valor == esperado


def test_extraer_mejor_combina_lecturas():
    lectura_mala = "BBVA\nImporte: $1,2O0.5O\nClave de rastreo: 11FEF28A36F"
    lectura_buena = "Importe: $1,200.50\nFecha: 06/09/2018"
    r = extraer_mejor([lectura_mala, lectura_buena], CATALOGO)
    assert r["monto"].valor == "1200.50"
    assert r["fecha"].valor == "2018-09-06"
    assert r["clave_rastreo"].valor == "11FEF28A36F"
    assert r["emisor_clave"].valor == "40012"


def test_rastreo_conserva_letra_final():
    r = extraer("Clave de rastreo: 26O909010981041025I", CATALOGO)
    assert r["clave_rastreo"].valor == "260909010981041025I"


def test_folio_y_referencia():
    r = extraer(NU_ETIQUETA_PARTIDA, CATALOGO)
    assert r["referencia"].valor == "191026"
    assert r["folio"].valor is None  # "QWGLRTFDW" no tiene dígitos
    r = extraer("Folio de internet: 0044395732\nFolio de rastreo ABC1234567", CATALOGO)
    assert r["folio"].valor == "0044395732"
    assert r["clave_rastreo"].valor == "ABC1234567"
    assert extraer(AZTECA_OCR, CATALOGO)["referencia"].valor == "8146602"
