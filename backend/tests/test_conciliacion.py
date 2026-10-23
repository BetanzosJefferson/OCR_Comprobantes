from app.conciliacion import DatosComprobante, DatosMovimiento, conciliar, normalizar_rastreo

PERIODO = [("2026-09-09", "2026-10-08")]


def mov(id, monto="200.00", fecha="2026-09-09", tipo="spei_recibido", rastreo=None, referencia=None,
        ref_num=None, bancos=("40127",)):
    return DatosMovimiento(id, fecha, fecha, tipo, monto, rastreo, referencia, ref_num, set(bancos))


def comp(id, monto="200.00", fecha="2026-09-09", rastreo=None, emisor=None, folio=None, referencia=None):
    return DatosComprobante(id, fecha, rastreo, monto, emisor, None, folio, referencia)


def test_normalizacion_tolera_confusiones_ocr():
    assert normalizar_rastreo("260909010981041025I") == normalizar_rastreo("26O9O9010981041025l")
    assert normalizar_rastreo("SPIN-2026") == "SP1N2026"


def test_rastreo_exacto_con_confusion_i_1():
    r = conciliar([comp(1, rastreo="2609090109810410251")], [mov(10, rastreo="260909010981041025I")])[1]
    assert (r.estado, r.movimiento_id) == ("encontrado", 10)
    assert r.diferencias["clave_rastreo"] == "260909010981041025I"


def test_rastreo_aproximado_propone_la_clave_correcta():
    movs = [mov(10, rastreo="NU3AQRT3Q9Q19GQBM2JDFEIGT9TI")]
    r = conciliar([comp(1, rastreo="NUSAQRT3Q9Q19GQBM2JDFEIGT9TI")], movs)[1]
    assert (r.estado, r.movimiento_id) == ("encontrado", 10)
    assert "casi idéntica" in r.criterio
    assert r.diferencias["clave_rastreo"] == "NU3AQRT3Q9Q19GQBM2JDFEIGT9TI"


def test_rastreo_aproximado_exige_mismo_monto():
    movs = [mov(10, monto="250.00", rastreo="NU3AQRT3Q9Q19GQBM2JDFEIGT9TI")]
    assert conciliar([comp(1, rastreo="NUSAQRT3Q9Q19GQBM2JDFEIGT9TI")], movs, PERIODO)[1].estado == "no_encontrado"


def test_folio_igual_a_referencia_sin_ceros():
    movs = [mov(10, tipo="pago_tercero", referencia="0044395732", bancos=("40012",))]
    r = conciliar([comp(1, folio="44395732")], movs)[1]
    assert (r.estado, r.movimiento_id) == ("encontrado", 10)


def test_referencia_numerica_unica():
    movs = [mov(10, ref_num="8146602", referencia="0114046014"), mov(11, monto="450.00", ref_num="8146602")]
    r = conciliar([comp(1, referencia="8146602")], movs)[1]
    assert (r.estado, r.movimiento_id) == ("encontrado", 10)


def test_referencia_numerica_repetida_no_decide_sola():
    movs = [mov(10, ref_num="8146602"), mov(11, ref_num="8146602")]
    r = conciliar([comp(1, referencia="8146602")], movs, PERIODO)[1]
    assert r.estado == "no_encontrado" and r.movimiento_id is None
    assert sorted(r.candidatos) == [10, 11]


def test_monto_fecha_y_banco_es_probable():
    movs = [mov(10, bancos=("40127",)), mov(11, bancos=("40014",))]
    r = conciliar([comp(1, emisor="40014")], movs)[1]
    assert (r.estado, r.movimiento_id) == ("probable", 11)


def test_monto_y_fecha_con_candidato_unico_es_posible():
    r = conciliar([comp(1, fecha="2026-09-10")], [mov(10, fecha="2026-09-09")])[1]
    assert (r.estado, r.movimiento_id) == ("posible", 10)


def test_monto_y_fecha_ambiguo_no_se_asigna():
    r = conciliar([comp(1)], [mov(10), mov(11)], PERIODO)[1]
    assert r.estado == "no_encontrado" and sorted(r.candidatos) == [10, 11]


def test_movimiento_usado_dos_veces():
    movs = [mov(10, rastreo="MBAN01002609140081193537")]
    r = conciliar([comp(1, rastreo="MBAN01002609140081193537"), comp(2, rastreo="MBAN01002609140081193537")], movs)
    assert (r[1].estado, r[1].movimiento_id) == ("encontrado", 10)
    assert (r[2].estado, r[2].movimiento_id) == ("usado", 10)
    assert "#1" in r[2].criterio


def test_conflicto_de_monto():
    movs = [mov(10, monto="200.00", rastreo="MBAN01002609140081193537")]
    r = conciliar([comp(1, monto="2000.00", rastreo="MBAN01002609140081193537")], movs)[1]
    assert (r.estado, r.movimiento_id) == ("conflicto", 10)
    assert r.diferencias["monto"] == "200.00"


def test_la_clave_gana_sobre_monto_y_fecha():
    # El comprobante 2 coincide por monto/fecha con el mismo movimiento que el 1 encontró por clave.
    movs = [mov(10, rastreo="MBAN01002609140081193537"), mov(11, monto="999.00")]
    r = conciliar([comp(2), comp(1, rastreo="MBAN01002609140081193537")], movs, PERIODO)
    assert r[1].movimiento_id == 10
    assert r[2].estado == "no_encontrado"


def test_fuera_del_periodo_cargado():
    assert conciliar([comp(1, fecha="2026-12-01")], [mov(10)], PERIODO)[1].estado == "sin_estado"


def test_sin_estados_de_cuenta():
    assert conciliar([comp(1)], [])[1].estado == ""
