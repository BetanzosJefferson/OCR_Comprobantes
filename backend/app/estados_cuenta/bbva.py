"""Lectura de estados de cuenta BBVA en PDF con texto nativo (sin OCR).

Cada movimiento ocupa un bloque de renglones que empieza con "dd/MMM dd/MMM" (fecha de
operación y de liquidación). Un SPEI recibido, por ejemplo:

    09/SEP 09/SEP SPEI RECIBIDOSANTANDER                         900.00
    9738428ELLIOTH HERNANDEZ        Referencia 0113790843 014     <- ref. numérica + concepto | referencia + banco
    00014180567817199223                                          <- CLABE de la contraparte
    2026090940014BMOVP020416136290                                <- clave de rastreo
    YAFTE ELLIOT HERNANDEZ BLANQUEL                               <- nombre de la contraparte

El importe se clasifica como cargo o abono por su posición horizontal respecto a los
encabezados de columna. Los bloques pueden continuar en la página siguiente.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import IO, Dict, List, Optional, Sequence, Tuple, Union

MESES = {"ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
         "JUL": 7, "AGO": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DIC": 12}

R_INICIO = re.compile(r"^(\d{2})/([A-Z]{3})\s+(\d{2})/([A-Z]{3})\s+(.*)$")
R_IMPORTE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$")
R_REFERENCIA = re.compile(r"^(?P<concepto>.*?)\s*Referencia\s+(?P<ref>\S+)(?:\s+(?P<suf>\d{3}))?\s*$")
R_REF_NUMERICA = re.compile(r"^(\d{7})(.*)$")
R_PAGO_TERCERO = re.compile(r"^(?:BNET\s+)?(\d{10,18})\s*(.*)$")
R_CLABE = re.compile(r"^\d{18,20}$")
R_RASTREO = re.compile(r"^[A-Za-z0-9\-]{8,40}$")

R_NO_CLIENTE = re.compile(r"^No\.\s*de\s*Cliente", re.I)
R_DETALLE = re.compile(r"^Detalle de Movimientos", re.I)
R_FIN = re.compile(r"^Total de Movimientos", re.I)
R_PIE = re.compile(r"^(BBVA MEXICO, S\.A\.|La GAT Real|Av\. Paseo de la Reforma)", re.I)
R_ENCABEZADO = re.compile(r"^(FECHA\b.*SALDO|OPER\s+LIQ\b)", re.I)

# Borde derecho de cada columna de importes, medido en un estado de cuenta real (página de 612 pt).
COLUMNAS_POR_DEFECTO = {"cargo": 417.0, "abono": 464.0, "saldo_operacion": 520.0, "saldo_liquidacion": 594.0}
ENCABEZADOS_COLUMNA = {"CARGOS": "cargo", "ABONOS": "abono", "OPERACION": "saldo_operacion",
                       "LIQUIDACION": "saldo_liquidacion"}


class EstadoCuentaInvalido(ValueError):
    pass


@dataclass
class Palabra:
    texto: str
    x0: float
    x1: float
    top: float = 0.0


@dataclass
class Renglon:
    pagina: int
    palabras: List[Palabra]

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palabras)


@dataclass
class MovimientoBBVA:
    pagina: int
    fecha_operacion: str
    fecha_liquidacion: str
    tipo: str
    descripcion: str
    banco_texto: str = ""
    referencia: Optional[str] = None
    referencia_sufijo: Optional[str] = None
    referencia_numerica: Optional[str] = None
    concepto: str = ""
    cuenta_contraparte: Optional[str] = None
    clave_rastreo: Optional[str] = None
    nombre_contraparte: str = ""
    cargo: Optional[str] = None
    abono: Optional[str] = None
    texto_crudo: str = ""

    @property
    def monto(self) -> Optional[str]:
        return self.abono or self.cargo


@dataclass
class EstadoBBVA:
    numero_cuenta: str
    periodo_inicio: str
    periodo_fin: str
    paginas: int
    producto: str = ""
    clabe: str = ""
    total_cargos: Optional[str] = None
    total_abonos: Optional[str] = None
    movimientos: List[MovimientoBBVA] = field(default_factory=list)
    advertencias: List[str] = field(default_factory=list)


# ---------------------------------------------------------------- Lectura del PDF


def _renglones(palabras: Sequence[dict], pagina: int, tolerancia: float = 2.5) -> List[Renglon]:
    renglones: List[Renglon] = []
    actual: List[Palabra] = []
    top = None
    for w in sorted(palabras, key=lambda w: (round(w["top"]), w["x0"])):
        if top is not None and abs(w["top"] - top) > tolerancia:
            renglones.append(Renglon(pagina, sorted(actual, key=lambda p: p.x0)))
            actual = []
        if not actual:
            top = w["top"]
        actual.append(Palabra(w["text"], w["x0"], w["x1"], w["top"]))
    if actual:
        renglones.append(Renglon(pagina, sorted(actual, key=lambda p: p.x0)))
    return renglones


def parsear_pdf(fuente: Union[str, IO[bytes]]) -> EstadoBBVA:
    import pdfplumber

    try:
        pdf = pdfplumber.open(fuente)
    except Exception as e:  # noqa: BLE001 - pdfminer lanza varios tipos según el daño del archivo
        raise EstadoCuentaInvalido(f"No se pudo abrir el PDF: {e}") from e
    with pdf:
        paginas = []
        caracteres = 0
        for i, pagina in enumerate(pdf.pages, start=1):
            caracteres += len(pagina.chars)
            paginas.append(_renglones(pagina.extract_words(keep_blank_chars=False), i))
    if caracteres == 0:
        raise EstadoCuentaInvalido(
            "El PDF no tiene texto seleccionable (parece escaneado). Descarga el estado de cuenta original desde BBVA."
        )
    return parsear_paginas(paginas)


# ---------------------------------------------------------------- Interpretación


def _fecha(dia: str, mes: str, inicio: date, fin: date) -> str:
    m = MESES.get(mes)
    if not m:
        raise ValueError(f"Mes desconocido: {mes}")
    anio = inicio.year if (inicio.year == fin.year or m >= inicio.month) else fin.year
    return date(anio, m, int(dia)).isoformat()


def _fecha_dmy(texto: str) -> date:
    d, m, a = texto.split("/")
    return date(int(a), int(m), int(d))


def _importe(texto: str) -> str:
    return str(Decimal(texto.replace(",", "")).quantize(Decimal("0.01")))


def _columnas_de(renglon: Renglon) -> Optional[Dict[str, float]]:
    cols = {ENCABEZADOS_COLUMNA[p.texto]: p.x1 for p in renglon.palabras if p.texto in ENCABEZADOS_COLUMNA}
    if "cargo" in cols and "abono" in cols:
        return {**COLUMNAS_POR_DEFECTO, **cols}
    return None


def _separar_importes(renglon: Renglon, columnas: Dict[str, float]) -> Tuple[str, Dict[str, str]]:
    """Devuelve el texto del renglón sin importes y los importes por columna."""
    umbral = columnas["cargo"] - 60
    texto, importes = [], {}
    for p in renglon.palabras:
        if R_IMPORTE.match(p.texto) and p.x0 >= umbral:
            col = min(columnas, key=lambda c: abs(columnas[c] - p.x1))
            importes[col] = _importe(p.texto)
        else:
            texto.append(p.texto)
    return " ".join(texto), importes


def _tipo(descripcion: str) -> Tuple[str, str]:
    d = descripcion.upper()
    for prefijo, tipo in (("SPEI RECIBIDO", "spei_recibido"), ("SPEI ENVIADO", "spei_enviado"),
                          ("SPEI DEVUELTO", "spei_devuelto")):
        if d.startswith(prefijo):
            return tipo, descripcion[len(prefijo):].strip()
    if d.startswith("PAGO CUENTA DE TERCERO"):
        return "pago_tercero", "BBVA"
    return "otro", ""


def _bloque_a_movimiento(bloque: List[Renglon], columnas: Dict[str, float], inicio: date, fin: date) -> MovimientoBBVA:
    texto0, importes = _separar_importes(bloque[0], columnas)
    m = R_INICIO.match(texto0)
    descripcion = m.group(5).strip()
    tipo, banco = _tipo(descripcion)
    mov = MovimientoBBVA(
        pagina=bloque[0].pagina,
        fecha_operacion=_fecha(m.group(1), m.group(2), inicio, fin),
        fecha_liquidacion=_fecha(m.group(3), m.group(4), inicio, fin),
        tipo=tipo,
        descripcion=descripcion,
        banco_texto=banco,
        cargo=importes.get("cargo"),
        abono=importes.get("abono"),
        texto_crudo="\n".join(r.texto for r in bloque),
    )

    resto = [r.texto.strip() for r in bloque[1:] if r.texto.strip()]
    if resto:
        detalle = resto.pop(0)
        ref = R_REFERENCIA.match(detalle)
        concepto = detalle
        if ref:
            concepto = ref.group("concepto").strip()
            mov.referencia = ref.group("ref")
            mov.referencia_sufijo = ref.group("suf")
        if tipo.startswith("spei"):
            num = R_REF_NUMERICA.match(concepto)
            if num:
                mov.referencia_numerica, concepto = num.group(1), num.group(2).strip()
        elif tipo == "pago_tercero":
            pt = R_PAGO_TERCERO.match(concepto)
            if pt:
                mov.cuenta_contraparte, concepto = pt.group(1), pt.group(2).strip()
        mov.concepto = concepto

    nombres = []
    for linea in resto:
        compacta = linea.replace(" ", "")
        if mov.cuenta_contraparte is None and R_CLABE.match(compacta):
            # BBVA antepone ceros: 20 dígitos = "00" + CLABE de 18.
            mov.cuenta_contraparte = compacta[-18:] if len(compacta) > 18 else compacta
        elif (mov.clave_rastreo is None and tipo.startswith("spei") and " " not in linea
              and R_RASTREO.match(linea) and any(c.isdigit() for c in linea)):
            mov.clave_rastreo = linea
        else:
            nombres.append(linea)
    mov.nombre_contraparte = " ".join(nombres)
    return mov


def _encabezado(texto: str) -> Dict[str, str]:
    datos: Dict[str, str] = {}
    patrones = {
        "numero_cuenta": r"No\.\s*de\s*Cuenta\s+(\d{6,})",
        "periodo": r"Periodo\s+DEL\s+(\d{2}/\d{2}/\d{4})\s+AL\s+(\d{2}/\d{2}/\d{4})",
        "clabe": r"No\.\s*Cuenta\s*CLABE\s+([\d ]{18,24})",
        "total_cargos": r"TOTAL IMPORTE CARGOS\s+([\d,]+\.\d{2})",
        "total_abonos": r"TOTAL IMPORTE ABONOS\s+([\d,]+\.\d{2})",
        "n_cargos": r"TOTAL MOVIMIENTOS CARGOS\s+(\d+)",
        "n_abonos": r"TOTAL MOVIMIENTOS ABONOS\s+(\d+)",
    }
    for clave, patron in patrones.items():
        m = re.search(patron, texto, re.I)
        if not m:
            continue
        if clave == "periodo":
            datos["periodo_inicio"], datos["periodo_fin"] = m.group(1), m.group(2)
        elif clave == "clabe":
            datos["clabe"] = re.sub(r"\D", "", m.group(1))[:18]
        else:
            datos[clave] = m.group(1)
    m = re.search(r"Estado de Cuenta\s*\n\s*(.+)", texto)
    if m and not m.group(1).upper().startswith("PAGINA"):
        datos["producto"] = m.group(1).strip()
    return datos


def parsear_paginas(paginas: Sequence[List[Renglon]]) -> EstadoBBVA:
    texto = "\n".join(r.texto for pagina in paginas for r in pagina)
    if "BBVA" not in texto.upper():
        raise EstadoCuentaInvalido("El PDF no parece un estado de cuenta BBVA")
    datos = _encabezado(texto)
    if "numero_cuenta" not in datos or "periodo_inicio" not in datos:
        raise EstadoCuentaInvalido("No se encontró el número de cuenta o el periodo del estado de cuenta")
    inicio, fin = _fecha_dmy(datos["periodo_inicio"]), _fecha_dmy(datos["periodo_fin"])

    columnas = dict(COLUMNAS_POR_DEFECTO)
    bloques: List[List[Renglon]] = []
    actual: Optional[List[Renglon]] = None
    en_detalle = terminado = False
    for renglones in paginas:
        en_cuerpo = False
        for r in renglones:
            t = r.texto.strip()
            if not en_detalle:
                en_detalle = en_cuerpo = bool(R_DETALLE.match(t))
                continue
            if R_FIN.match(t):
                terminado = True
                break
            if R_PIE.match(t):
                break
            if R_ENCABEZADO.match(t):
                columnas = _columnas_de(r) or columnas
                en_cuerpo = True
                continue
            if not en_cuerpo:
                # Encabezado de página (cuenta, cliente...): termina en "No. de Cliente".
                if R_NO_CLIENTE.match(t):
                    en_cuerpo = True
                    continue
                if not R_INICIO.match(t):
                    continue
                en_cuerpo = True
            if R_INICIO.match(_separar_importes(r, columnas)[0]):
                actual = [r]
                bloques.append(actual)
            elif actual is not None:
                actual.append(r)
        if terminado:
            break
    if not en_detalle:
        raise EstadoCuentaInvalido("No se encontró la sección 'Detalle de Movimientos Realizados'")

    estado = EstadoBBVA(
        numero_cuenta=datos["numero_cuenta"],
        periodo_inicio=inicio.isoformat(),
        periodo_fin=fin.isoformat(),
        paginas=len(paginas),
        producto=datos.get("producto", ""),
        clabe=datos.get("clabe", ""),
        total_cargos=_importe(datos["total_cargos"]) if "total_cargos" in datos else None,
        total_abonos=_importe(datos["total_abonos"]) if "total_abonos" in datos else None,
    )
    for bloque in bloques:
        try:
            mov = _bloque_a_movimiento(bloque, columnas, inicio, fin)
        except ValueError as e:
            estado.advertencias.append(f"Página {bloque[0].pagina}: no se pudo leer '{bloque[0].texto}' ({e})")
            continue
        if mov.monto is None:
            estado.advertencias.append(f"Página {mov.pagina}: movimiento sin importe '{mov.descripcion}'")
        estado.movimientos.append(mov)
    _verificar_totales(estado, datos)
    return estado


def _verificar_totales(estado: EstadoBBVA, datos: Dict[str, str]) -> None:
    for columna, nombre in (("cargo", "cargos"), ("abono", "abonos")):
        valores = [Decimal(getattr(m, columna)) for m in estado.movimientos if getattr(m, columna)]
        esperado_n = datos.get(f"n_{nombre}")
        if esperado_n and int(esperado_n) != len(valores):
            estado.advertencias.append(
                f"Se leyeron {len(valores)} {nombre} y el estado de cuenta indica {esperado_n}"
            )
        esperado = getattr(estado, f"total_{nombre}")
        if esperado and Decimal(esperado) != sum(valores, Decimal("0")):
            estado.advertencias.append(
                f"La suma de {nombre} leídos ({sum(valores, Decimal('0')):.2f}) no coincide con el total {esperado}"
            )
