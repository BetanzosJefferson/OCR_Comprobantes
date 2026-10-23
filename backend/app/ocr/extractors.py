"""Extracción de campos a partir del texto OCR de un comprobante.

Cada extractor devuelve una `Extraccion` con el valor normalizado y una confianza entre 0 y 1.
La confianza es heurística: refleja qué tan fuerte es la evidencia (etiqueta cercana,
coincidencia con catálogos, formato), no una probabilidad calibrada.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

from rapidfuzz import fuzz


@dataclass
class BancoCat:
    clave: str
    nombre: str
    alias: List[str] = field(default_factory=list)


@dataclass
class CuentaCat:
    numero: str
    banco_clave: str
    tipo: str = "clabe"
    titular: str = ""


@dataclass
class Catalogo:
    bancos: List[BancoCat] = field(default_factory=list)
    cuentas: List[CuentaCat] = field(default_factory=list)

    def banco_por_clabe(self, clabe: str) -> Optional[str]:
        """Los primeros 3 dígitos de una CLABE identifican al banco (sufijo de la clave SPEI)."""
        if len(clabe) != 18:
            return None
        candidatos = [b.clave for b in self.bancos if b.clave[-3:] == clabe[:3]]
        return candidatos[0] if len(candidatos) == 1 else None


@dataclass
class Extraccion:
    valor: Optional[str] = None
    confianza: float = 0.0
    # Entre lecturas, gana la de mayor prioridad aunque tenga menos confianza
    # (p. ej. una clave de rastreo siempre se prefiere sobre una referencia).
    prioridad: int = 0


CAMPOS = ["fecha", "clave_rastreo", "emisor_clave", "receptor_clave", "cuenta", "monto"]
CAMPOS_AUXILIARES = ["folio", "referencia"]


def _base(c: str) -> str:
    d = unicodedata.normalize("NFD", c)
    return d[0] if d else c


def normalizar(texto: str) -> str:
    """Mayúsculas y sin acentos, conservando la longitud para poder mapear posiciones al original."""
    return "".join(_base(c) for c in texto).upper()


@dataclass
class Linea:
    original: str
    norm: str


def _lineas(texto: str) -> List[Linea]:
    return [Linea(l.strip(), normalizar(l.strip())) for l in texto.splitlines() if l.strip()]


def _buscar(patron: "re.Pattern[str]", lineas: Sequence[Linea], i: int, atras: int = 0) -> bool:
    return any(patron.search(lineas[j].norm) for j in range(max(0, i - atras), i + 1))


# ---------------------------------------------------------------- Fecha

MESES = {
    "ENE": 1, "ENERO": 1, "JAN": 1, "FEB": 2, "FEBRERO": 2, "MAR": 3, "MARZO": 3,
    "ABR": 4, "ABRIL": 4, "APR": 4, "MAY": 5, "MAYO": 5, "JUN": 6, "JUNIO": 6,
    "JUL": 7, "JULIO": 7, "AGO": 8, "AGOSTO": 8, "AUG": 8, "SEP": 9, "SEPT": 9,
    "SET": 9, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCT": 10, "OCTUBRE": 10,
    "NOV": 11, "NOVIEMBRE": 11, "DIC": 12, "DICIEMBRE": 12, "DEC": 12,
}

R_FECHA_DMY = re.compile(r"(?<![\d/.\-])(\d{1,2})\s?[/\-.]\s?(\d{1,2})\s?[/\-.]\s?(\d{4}|\d{2})(?![\d/])")
R_FECHA_YMD = re.compile(r"(?<!\d)(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)")
# El mes admite "0" porque Tesseract suele leer "Oct" como "0ct".
R_FECHA_TXT = re.compile(
    r"(?<!\d)(\d{1,2})\s*(?:DE\s+)?[/\-.]?\s*([A-Z0]{3,10})\.?\s*[/\-.,]?\s*(?:DE\s+|DEL\s+)?(\d{4}|\d{2})(?!\d)"
)
R_FECHA_MDY_TXT = re.compile(r"\b([A-Z0]{3,10})\.?\s+(\d{1,2}),?\s+(\d{4})(?!\d)")


def _mes(token: str) -> Optional[int]:
    return MESES.get(token.replace("0", "O"))
R_ETQ_FECHA = re.compile(r"FECHA|DIA DE|REALIZAD|OPERACION|APLICACION|ENVIAD")
R_FECHA_NO = re.compile(r"VENCIMIENTO|NACIMIENTO|EXPIRA|VIGENCIA|CORTE")


def _fecha_valida(a: int, m: int, d: int) -> Optional[date]:
    if a < 100:
        a += 2000
    if not (2000 <= a <= date.today().year + 1):
        return None
    try:
        return date(a, m, d)
    except ValueError:
        return None


def extraer_fecha(lineas: Sequence[Linea]) -> Extraccion:
    mejor = Extraccion()
    for i, linea in enumerate(lineas):
        t = linea.norm
        if R_FECHA_NO.search(t):
            continue
        candidatos: List[Tuple[date, float]] = []
        for m in R_FECHA_YMD.finditer(t):
            f = _fecha_valida(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if f:
                candidatos.append((f, 0.65))
        for m in R_FECHA_DMY.finditer(t):
            d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
            f = _fecha_valida(a, mes, d)
            if f:
                candidatos.append((f, 0.6))
            elif mes > 12 >= d:
                # Formato mes/día (poco común en México): se acepta con menor confianza.
                f = _fecha_valida(a, d, mes)
                if f:
                    candidatos.append((f, 0.4))
        for m in R_FECHA_TXT.finditer(t):
            mes = _mes(m.group(2))
            f = mes and _fecha_valida(int(m.group(3)), mes, int(m.group(1)))
            if f:
                candidatos.append((f, 0.7))
        for m in R_FECHA_MDY_TXT.finditer(t):
            mes = _mes(m.group(1))
            f = mes and _fecha_valida(int(m.group(3)), mes, int(m.group(2)))
            if f:
                candidatos.append((f, 0.65))

        if not candidatos:
            continue
        bono = 0.0
        if R_ETQ_FECHA.search(t):
            bono = 0.25
        elif _buscar(R_ETQ_FECHA, lineas, i, atras=1):
            bono = 0.2
        for f, base in candidatos:
            conf = min(base + bono, 0.95)
            if conf > mejor.confianza:
                mejor = Extraccion(f.isoformat(), conf)
    return mejor


# ---------------------------------------------------------------- Clave de rastreo

# (patrón, confianza, prioridad). La clave de rastreo siempre gana; la referencia y el folio
# solo se usan si no hay clave, y con confianza baja para que el usuario lo revise.
PRIORIDAD_RASTREO = 2
ETIQUETAS_RASTREO = [
    (
        re.compile(r"(?:CLAVE|CVE\.?)\s*(?:DE\s*)?RASTREO|(?:NO\.?|NUMERO|FOLIO)\s*(?:DE\s*)?RASTREO|RASTREO"),
        0.95,
        PRIORIDAD_RASTREO,
    ),
    (re.compile(r"REFERENCIA\s*(?:DE\s*)?(?:OPERACION|TRANSFERENCIA|SPEI)?"), 0.5, 1),
    (
        re.compile(
            r"FOLIO(?:\s*(?:DE\s*)?(?:OPERACION|INTERNET|SPEI))?"
            r"|(?:NUMERO|NO\.?|NUM\.?)\s*DE\s*(?:OPERACION|AUTORIZACION|MOVIMIENTO|TRANSACCION)"
            r"|AUTORIZACION|ID\s*DE\s*(?:OPERACION|TRANSACCION|TRANSFERENCIA)"
        ),
        0.45,
        0,
    ),
]
# Una clave larga puede partirse en dos renglones ("NU3AQRT...EIGT" / "9TI").
LARGO_MINIMO_PARTIDA = 15
LARGO_MINIMO_ATRAS = 10
R_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{6,30}(?![A-Za-z0-9])")
R_RASTREO_SIN_ETIQUETA = re.compile(r"(?<![A-Z0-9])[A-Z]{4}\d{14,26}(?![A-Z0-9])")


CONFUSIONES_DIGITO = {"O": "0", "o": "0", "I": "1", "l": "1"}


def _corregir_confusiones(token: str) -> str:
    """En claves mayormente numéricas, Tesseract suele leer 0 como O y 1 como I/l junto a dígitos.

    La última letra se conserva: hay claves que terminan en letra (Azteca: "260909010981041025I").
    """
    if sum(c.isdigit() for c in token) / len(token) < 0.6:
        return token
    chars = list(token)
    for i, c in enumerate(chars[:-1]):
        if c in CONFUSIONES_DIGITO:
            vecinos = token[i - 1:i] + token[i + 1:i + 2]
            if any(v.isdigit() for v in vecinos):
                chars[i] = CONFUSIONES_DIGITO[c]
    return "".join(chars)


def _token_rastreo(texto: str) -> Optional[str]:
    for m in R_TOKEN.finditer(texto):
        token = m.group(0)
        if any(c.isdigit() for c in token):
            return _corregir_confusiones(token)
    return None


def _continuacion(linea: Linea) -> Optional[str]:
    """Fragmento final de una clave partida: un token corto, acompañado a lo sumo de ruido de 1-2 letras."""
    tokens = re.findall(r"[A-Za-z0-9]+", linea.original)
    if not tokens or any(len(t) > 2 for t in tokens[:-1]):
        return None
    ultimo = tokens[-1]
    if 1 <= len(ultimo) <= 8 and (any(c.isdigit() for c in ultimo) or ultimo.isupper()):
        return ultimo
    return None


def _con_continuacion(token: str, lineas: Sequence[Linea], j: int, etiqueta: int) -> str:
    """Une la clave encontrada en la línea j con su fragmento en la línea siguiente, si lo hay."""
    siguiente = j + 1
    if len(token) < LARGO_MINIMO_PARTIDA or siguiente >= len(lineas) or siguiente == etiqueta:
        return token
    resto = _continuacion(lineas[siguiente])
    return _corregir_confusiones(token + resto) if resto else token


def _valor_de_etiqueta(lineas: Sequence[Linea], i: int, fin_etiqueta: int, peso: float, buscar_atras: bool):
    """Busca el valor en la misma línea, en las dos siguientes y, si se permite, en las dos anteriores
    (diseños donde la etiqueta ocupa varios renglones y el valor queda alineado arriba)."""
    token = _token_rastreo(lineas[i].original[fin_etiqueta:])
    if token:
        return _con_continuacion(token, lineas, i, i), peso
    for j in range(i + 1, min(i + 3, len(lineas))):
        token = _token_rastreo(lineas[j].original)
        if token:
            return _con_continuacion(token, lineas, j, i), peso * 0.9
    if buscar_atras:
        for j in range(i - 1, max(-1, i - 3), -1):
            token = _token_rastreo(lineas[j].original)
            if token and len(token) >= LARGO_MINIMO_ATRAS:
                # Diseño ambiguo: se propone con confianza baja para que el usuario lo confirme.
                return _con_continuacion(token, lineas, j, i), 0.55
    return None, 0.0


def extraer_rastreo(lineas: Sequence[Linea]) -> Extraccion:
    mejor = Extraccion()
    for i, linea in enumerate(lineas):
        for patron, peso, prioridad in ETIQUETAS_RASTREO:
            m = patron.search(linea.norm)
            if not m:
                continue
            token, conf = _valor_de_etiqueta(lineas, i, m.end(), peso, prioridad == PRIORIDAD_RASTREO)
            if token and (prioridad, conf) > (mejor.prioridad, mejor.confianza):
                mejor = Extraccion(token, conf, prioridad)
            break  # una etiqueta por línea: la de mayor prioridad
    if mejor.prioridad < PRIORIDAD_RASTREO:
        for linea in lineas:
            m = R_RASTREO_SIN_ETIQUETA.search(linea.norm)
            if m:
                return Extraccion(linea.original[m.start():m.end()], 0.4, PRIORIDAD_RASTREO)
    return mejor


# ---------------------------------------------------------------- Folio y referencia
# No van al TXT: sirven para encontrar el comprobante en el estado de cuenta (la referencia
# BBVA de un pago a terceros es el folio del comprobante).

R_ETQ_FOLIO = re.compile(
    r"FOLIO(?:\s*(?:DE\s*)?(?:OPERACION|INTERNET|SPEI|TRANSACCION))?(?!\s*(?:DE\s*)?RASTREO)"
    r"|(?:NUMERO|NO\.?|NUM\.?)\s*DE\s*(?:OPERACION|FOLIO|MOVIMIENTO|TRANSACCION)"
)
R_ETQ_REFERENCIA = re.compile(
    r"(?:(?:NUMERO|NO\.?|NUM\.?)\s*DE\s*)?REFERENCIA(?:\s*(?:NUMERICA|DE\s*PAGO|BANCARIA))?(?!\s*(?:DE\s*)?RASTREO)"
)


def _extraer_etiquetado(lineas: Sequence[Linea], etiqueta: "re.Pattern[str]") -> Extraccion:
    mejor = Extraccion()
    for i, linea in enumerate(lineas):
        m = etiqueta.search(linea.norm)
        if not m:
            continue
        token = _token_rastreo(linea.original[m.end():])
        conf = 0.8
        if not token and i + 1 < len(lineas) and not etiqueta.search(lineas[i + 1].norm):
            token, conf = _token_rastreo(lineas[i + 1].original), 0.7
        if token and conf > mejor.confianza:
            mejor = Extraccion(token, conf)
    return mejor


def extraer_folio(lineas: Sequence[Linea]) -> Extraccion:
    return _extraer_etiquetado(lineas, R_ETQ_FOLIO)


def extraer_referencia(lineas: Sequence[Linea]) -> Extraccion:
    return _extraer_etiquetado(lineas, R_ETQ_REFERENCIA)


# ---------------------------------------------------------------- Monto

R_MONTO = re.compile(
    r"(?P<moneda>\$|MXN\s*\$?|(?<![A-Z])S(?=\s?\d))?\s?"
    r"(?<![\d.,/:\-])(?P<entero>\d{1,3}(?:,\d{3})+|\d{1,9})(?P<dec>\.\d{1,2})?"
    r"(?![\d/:\-]|,\d|\.\d)"
)
R_ETQ_MONTO = re.compile(
    r"MONTO|IMPORTE|TOTAL|CANTIDAD|VALOR|TRANSFERISTE|ENVIASTE|PAGASTE|ENVIADO|TRANSFERIDO|DEPOSITADO|ABONO"
)
R_MONTO_NO = re.compile(r"COMISION|\bIVA\b|SALDO|DISPONIBLE|LIMITE|INTERES")
# Monto grande con "$" y centavos en superíndice mal leídos: "5200.%", ">200.°°", "$200.oo".
R_MONTO_SUPERINDICE = re.compile(
    r"^\W{0,2}?(?P<pre>[$S5>»])?\s?(?P<entero>\d{1,3}(?:,\d{3})+|\d{1,7})\s?[.,]\s?(?P<cola>\S{0,3})$"
)


def _monto_superindice(t: str) -> Optional[Extraccion]:
    """Interpreta una línea que contiene solo un monto en formato de superíndice.

    Siempre devuelve confianza baja para que el usuario lo confirme: el "$" leído como "5"
    es indistinguible de un 5 real.
    """
    m = R_MONTO_SUPERINDICE.match(t.strip())
    if not m:
        return None
    cola = m.group("cola")
    centavos = cola if re.fullmatch(r"\d{2}", cola) else "00"
    try:
        valor = Decimal(f"{m.group('entero').replace(',', '')}.{centavos}")
    except InvalidOperation:
        return None
    if valor <= 0:
        return None
    conf = 0.4 if m.group("pre") in ("5", "S") else 0.5
    return Extraccion(f"{valor}", conf)


def extraer_monto(lineas: Sequence[Linea]) -> Extraccion:
    mejor = Extraccion()
    for i, linea in enumerate(lineas):
        t = linea.norm
        etiqueta = bool(R_ETQ_MONTO.search(t))
        etiqueta_previa = i > 0 and bool(R_ETQ_MONTO.search(lineas[i - 1].norm))
        if etiqueta_previa:
            sup = _monto_superindice(t)
            if sup and sup.confianza > mejor.confianza:
                mejor = sup
        for m in R_MONTO.finditer(t):
            moneda = bool(m.group("moneda"))
            dec = m.group("dec")
            entero = m.group("entero")
            agrupado = "," in entero
            if not (moneda or (dec and len(dec) == 3) or (agrupado and (etiqueta or etiqueta_previa))):
                continue
            try:
                valor = Decimal(entero.replace(",", "") + (dec or ""))
            except InvalidOperation:
                continue
            if valor <= 0:
                continue
            conf = 0.35
            if moneda:
                conf += 0.25
            if dec and len(dec) == 3:
                conf += 0.1
            if "MXN" in t or "PESOS" in t:
                conf += 0.05
            if etiqueta:
                conf += 0.3
            elif etiqueta_previa:
                conf += 0.25
            if R_MONTO_NO.search(t):
                conf *= 0.2
            conf = min(conf, 0.97)
            if conf > mejor.confianza:
                mejor = Extraccion(f"{valor.quantize(Decimal('0.01'))}", conf)
    return mejor


# ---------------------------------------------------------------- Cuenta beneficiaria

R_DIGITOS = re.compile(r"(?<![\dA-Z])\+?\d[\d \-]{2,30}\d(?!\d)")
# Los últimos dígitos admiten letras que Tesseract confunde con números ("***G02" = "***602").
R_ENMASCARADA = re.compile(r"[*•X·.+]{2,}\s?-?\s?([0-9GSBOIL]{3,4})(?![0-9A-Z])")
R_TERMINACION = re.compile(r"TERMINA(?:CION|DA)?\s*(?:EN)?\s*:?\s*([0-9GSBOIL]{4})(?![0-9A-Z])")
LETRAS_COMO_DIGITO = str.maketrans({"G": "6", "S": "5", "B": "8", "O": "0", "I": "1", "L": "1"})


def _digitos_finales(token: str) -> Optional[str]:
    if sum(c.isdigit() for c in token) < 2:
        return None
    return token.translate(LETRAS_COMO_DIGITO)
R_ETQ_BENEF = re.compile(
    r"DESTINO|BENEFICIARI|RECEPTOR|ABONO|DEPOSITO|PARA|CLABE|CUENTA|TARJETA|CELULAR|DESTINATARIO"
)
R_ETQ_ORIGEN = re.compile(r"ORIGEN|ORDENANTE|EMISOR|CARGO|RETIRO|DE TU CUENTA|DESDE")


@dataclass
class _CandidatoCuenta:
    cuenta: CuentaCat
    confianza: float


def _ajustar_por_contexto(conf: float, lineas: Sequence[Linea], i: int) -> float:
    if _buscar(R_ETQ_ORIGEN, lineas, i, atras=1) and not _buscar(R_ETQ_BENEF, lineas, i):
        return conf * 0.5
    if _buscar(R_ETQ_BENEF, lineas, i, atras=1):
        return min(conf + 0.05, 0.99)
    return conf


def _candidatos_cuenta(lineas: Sequence[Linea], cat: Catalogo) -> List[Tuple[_CandidatoCuenta, int]]:
    resultado: List[Tuple[_CandidatoCuenta, int]] = []
    cuentas = cat.cuentas
    for i, linea in enumerate(lineas):
        t = linea.norm
        for m in R_DIGITOS.finditer(t):
            digitos = re.sub(r"\D", "", m.group(0))
            if len(digitos) < 4:
                continue
            for c in cuentas:
                if digitos == c.numero:
                    conf = 0.98
                elif min(len(digitos), len(c.numero)) >= 8 and (
                    digitos.endswith(c.numero) or c.numero.endswith(digitos)
                ):
                    conf = 0.85
                elif len(digitos) == 4 and c.numero.endswith(digitos) and _buscar(R_ETQ_BENEF, lineas, i, atras=1):
                    conf = 0.6
                else:
                    continue
                resultado.append((_CandidatoCuenta(c, _ajustar_por_contexto(conf, lineas, i)), i))

        tokens = [m.group(1) for m in R_ENMASCARADA.finditer(t)] + [m.group(1) for m in R_TERMINACION.finditer(t)]
        for fin in filter(None, map(_digitos_finales, tokens)):
            coincidencias = [c for c in cuentas if c.numero.endswith(fin)]
            if not coincidencias:
                continue
            conf = 0.8 if len(coincidencias) == 1 else 0.35
            for c in coincidencias[:1]:
                resultado.append((_CandidatoCuenta(c, _ajustar_por_contexto(conf, lineas, i)), i))
    return resultado


def extraer_cuenta(lineas: Sequence[Linea], cat: Catalogo) -> Tuple[Extraccion, Optional[CuentaCat]]:
    candidatos = _candidatos_cuenta(lineas, cat)
    if not candidatos:
        return Extraccion(), None
    mejor, _ = max(candidatos, key=lambda x: x[0].confianza)
    return Extraccion(mejor.cuenta.numero, round(mejor.confianza, 3)), mejor.cuenta


# ---------------------------------------------------------------- Bancos

R_ETQ_RECEPTOR = re.compile(
    r"BANCO\s*(?:DE\s*)?(?:DESTINO|RECEPTOR|BENEFICIARI)|INSTITUCION\s*(?:RECEPTORA|BENEFICIARIA|DESTINO)"
    r"|DESTINO|RECEPTOR|BENEFICIARI|DESTINATARIO|\bPARA\b"
)
R_ETQ_EMISOR = re.compile(
    r"BANCO\s*(?:DE\s*)?(?:ORIGEN|EMISOR|ORDENANTE)|INSTITUCION\s*(?:EMISORA|ORDENANTE|ORIGEN)"
    r"|ORDENANTE|EMISOR|ORIGEN"
)
R_CLABE = re.compile(r"(?<!\d)\d{18}(?!\d)")
LINEAS_ENCABEZADO = 6


@dataclass
class _Mencion:
    linea: int
    clave: str
    exacta: bool


def _menciones_bancos(lineas: Sequence[Linea], cat: Catalogo) -> List[_Mencion]:
    bancos: List[Tuple[str, List[Tuple[str, "re.Pattern[str]"]]]] = []
    for b in cat.bancos:
        terminos = sorted(
            {normalizar(t.strip()) for t in [b.nombre, *b.alias] if len(t.strip()) >= 2}, key=len, reverse=True
        )
        bancos.append(
            (b.clave, [(t, re.compile(r"(?<![A-Z0-9])" + re.escape(t) + r"(?![A-Z0-9])")) for t in terminos])
        )

    menciones: List[_Mencion] = []
    for i, linea in enumerate(lineas):
        for clave, terminos in bancos:
            if any(p.search(linea.norm) for _, p in terminos):
                menciones.append(_Mencion(i, clave, True))
            elif any(
                len(t) >= 5 and len(linea.norm) >= len(t) and fuzz.partial_ratio(t, linea.norm) >= 90
                for t, _ in terminos
            ):
                menciones.append(_Mencion(i, clave, False))
    return menciones


def _banco_en_etiqueta(
    lineas: Sequence[Linea], menciones: List[_Mencion], etiqueta: "re.Pattern[str]"
) -> Tuple[Optional[str], set]:
    """Busca un banco en la línea de la etiqueta o en las dos siguientes."""
    lineas_etiqueta = set()
    encontrado: Optional[str] = None
    for i, linea in enumerate(lineas):
        if not etiqueta.search(linea.norm):
            continue
        lineas_etiqueta.add(i)
        for j in range(i, min(i + 3, len(lineas))):
            en_linea = [m for m in menciones if m.linea == j]
            if en_linea:
                lineas_etiqueta.add(j)
                if encontrado is None:
                    encontrado = en_linea[0].clave
                break
    return encontrado, lineas_etiqueta


def _clabe_en_contexto(lineas: Sequence[Linea], cat: Catalogo, etiqueta: "re.Pattern[str]", excluir: set) -> Optional[str]:
    for i, linea in enumerate(lineas):
        for m in R_CLABE.finditer(re.sub(r"[ \-]", "", linea.norm)):
            if m.group(0) in excluir:
                continue
            if _buscar(etiqueta, lineas, i, atras=1):
                clave = cat.banco_por_clabe(m.group(0))
                if clave:
                    return clave
    return None


def extraer_bancos(
    lineas: Sequence[Linea], cat: Catalogo, cuenta: Optional[CuentaCat], conf_cuenta: float
) -> Tuple[Extraccion, Extraccion]:
    menciones = _menciones_bancos(lineas, cat)
    cuentas_configuradas = {c.numero for c in cat.cuentas}

    # Receptor
    receptor_etq, lineas_receptor = _banco_en_etiqueta(lineas, menciones, R_ETQ_RECEPTOR)
    if cuenta:
        receptor = Extraccion(cuenta.banco_clave, conf_cuenta)
    elif receptor_etq:
        receptor = Extraccion(receptor_etq, 0.75)
    else:
        clave = _clabe_en_contexto(lineas, cat, R_ETQ_BENEF, set())
        receptor = Extraccion(clave, 0.55) if clave else Extraccion()

    # Emisor
    emisor_etq, _ = _banco_en_etiqueta(lineas, menciones, R_ETQ_EMISOR)
    if emisor_etq:
        return Extraccion(emisor_etq, 0.85), receptor

    clave = _clabe_en_contexto(lineas, cat, R_ETQ_ORIGEN, cuentas_configuradas)
    if clave:
        return Extraccion(clave, 0.7), receptor

    libres = [m for m in menciones if m.linea not in lineas_receptor and m.clave != receptor.valor]
    encabezado = [m for m in libres if m.linea < LINEAS_ENCABEZADO]
    if encabezado:
        m = encabezado[0]
        return Extraccion(m.clave, 0.7 if m.exacta else 0.55), receptor
    if libres:
        m = libres[0]
        return Extraccion(m.clave, 0.5 if m.exacta else 0.4), receptor

    # Solo aparece el banco receptor: puede ser una transferencia entre cuentas del mismo banco.
    mismo = [m for m in menciones if m.clave == receptor.valor and m.linea < LINEAS_ENCABEZADO]
    if mismo:
        return Extraccion(mismo[0].clave, 0.35), receptor
    return Extraccion(), receptor


# ---------------------------------------------------------------- API pública


def extraer(texto: str, cat: Catalogo) -> Dict[str, Extraccion]:
    lineas = _lineas(texto)
    cuenta_ext, cuenta = extraer_cuenta(lineas, cat)
    emisor, receptor = extraer_bancos(lineas, cat, cuenta, cuenta_ext.confianza)
    return {
        "fecha": extraer_fecha(lineas),
        "clave_rastreo": extraer_rastreo(lineas),
        "emisor_clave": emisor,
        "receptor_clave": receptor,
        "cuenta": cuenta_ext,
        "monto": extraer_monto(lineas),
        "folio": extraer_folio(lineas),
        "referencia": extraer_referencia(lineas),
    }


def extraer_mejor(textos: Sequence[str], cat: Catalogo) -> Dict[str, Extraccion]:
    """Combina los resultados de varias lecturas OCR quedándose, por campo, con el de mayor
    prioridad y, a igual prioridad, con el de mayor confianza.

    Ante empate gana el texto que aparece primero (mayor confianza media de Tesseract).
    """
    mejor = {c: Extraccion() for c in CAMPOS + CAMPOS_AUXILIARES}
    for texto in textos:
        for campo, ext in extraer(texto, cat).items():
            actual = mejor[campo]
            if ext.valor is not None and (
                actual.valor is None or (ext.prioridad, ext.confianza) > (actual.prioridad, actual.confianza)
            ):
                mejor[campo] = ext
    for campo in mejor:
        mejor[campo].confianza = round(mejor[campo].confianza, 3)
    return mejor
