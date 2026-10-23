"""Conciliación de comprobantes contra los movimientos de los estados de cuenta.

Criterios, de más a menos fuerte:
  100  clave de rastreo idéntica (tolerando O/0 e I/1/L)
   85  clave de rastreo con 1-2 caracteres distintos y mismo monto
   80  folio/referencia del comprobante = referencia del movimiento, mismo monto
   75  referencia numérica del concepto + monto + fecha
   60  monto + fecha (±1 día) + banco, candidato único          -> "probable"
   40  monto + fecha, candidato único                           -> "posible"

Un movimiento se asigna a un solo comprobante. Si un comprobante coincide por clave con un
movimiento ya tomado, se marca "usado" (comprobante reenviado o duplicado). Si la clave
coincide pero el monto o la fecha no, es un "conflicto" (posible comprobante alterado).
"""
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Set, Tuple

from rapidfuzz.distance import Levenshtein
from sqlmodel import Session, select

from .models import Comprobante, EstadoCuenta, Movimiento
from .ocr.extractors import Catalogo, normalizar

PUNTAJE_FUERTE = 70
TOLERANCIA_DIAS = 1
DISTANCIA_RASTREO = 2
LARGO_MINIMO_APROXIMADO = 10
LARGO_MINIMO_REFERENCIA = 6

TRADUCCION_RASTREO = str.maketrans({"O": "0", "I": "1", "L": "1"})

_lock = threading.Lock()


def normalizar_rastreo(valor: Optional[str]) -> str:
    if not valor:
        return ""
    return re.sub(r"[^A-Z0-9]", "", valor.upper()).translate(TRADUCCION_RASTREO)


def _sin_ceros(valor: Optional[str]) -> str:
    v = re.sub(r"\s", "", valor or "").upper()
    return v.lstrip("0") if v.isdigit() else v


@dataclass
class DatosComprobante:
    id: int
    fecha: Optional[str] = None
    clave_rastreo: Optional[str] = None
    monto: Optional[str] = None
    emisor_clave: Optional[str] = None
    receptor_clave: Optional[str] = None
    folio: Optional[str] = None
    referencia: Optional[str] = None
    cuenta: Optional[str] = None


@dataclass
class DatosMovimiento:
    id: int
    fecha_operacion: str
    fecha_liquidacion: str
    tipo: str
    monto: Optional[str]
    clave_rastreo: Optional[str] = None
    referencia: Optional[str] = None
    referencia_numerica: Optional[str] = None
    claves_banco: Set[str] = field(default_factory=set)
    banco_propio: Optional[str] = None
    cuenta_propia: Optional[str] = None


@dataclass
class Resultado:
    estado: str
    movimiento_id: Optional[int] = None
    criterio: str = ""
    diferencias: Dict[str, str] = field(default_factory=dict)
    candidatos: List[int] = field(default_factory=list)


@dataclass
class _Candidato:
    puntaje: int
    estado: str
    criterio: str
    mov: DatosMovimiento
    dias: int


def _dias(c: DatosComprobante, m: DatosMovimiento) -> Optional[int]:
    if not c.fecha:
        return None
    try:
        f = date.fromisoformat(c.fecha)
        return min(abs((f - date.fromisoformat(x)).days) for x in (m.fecha_operacion, m.fecha_liquidacion))
    except ValueError:
        return None


def _fecha_ok(c: DatosComprobante, m: DatosMovimiento) -> bool:
    d = _dias(c, m)
    return d is None or d <= TOLERANCIA_DIAS


def _banco_ok(c: DatosComprobante, m: DatosMovimiento) -> bool:
    banco = c.receptor_clave if m.tipo == "spei_enviado" else c.emisor_clave
    return bool(banco) and banco in m.claves_banco


def diferencias(c: DatosComprobante, m: DatosMovimiento) -> Dict[str, str]:
    """Datos del movimiento que faltan o difieren en el comprobante (para completarlo o revisarlo)."""
    difs: Dict[str, str] = {}
    if m.monto and c.monto != m.monto:
        difs["monto"] = m.monto
    if c.fecha not in (m.fecha_operacion, m.fecha_liquidacion):
        difs["fecha"] = m.fecha_operacion
    # Comparación literal: aunque la conciliación tolere O/0 e I/1, el TXT debe llevar la clave exacta.
    if m.clave_rastreo and (c.clave_rastreo or "").strip().upper() != m.clave_rastreo.upper():
        difs["clave_rastreo"] = m.clave_rastreo
    elif not m.clave_rastreo and m.referencia and not c.clave_rastreo:
        difs["clave_rastreo"] = m.referencia
    if m.tipo == "spei_enviado":
        if m.banco_propio and c.emisor_clave != m.banco_propio:
            difs["emisor_clave"] = m.banco_propio
        if len(m.claves_banco) == 1 and c.receptor_clave not in m.claves_banco:
            difs["receptor_clave"] = next(iter(m.claves_banco))
    else:
        if len(m.claves_banco) == 1 and c.emisor_clave not in m.claves_banco:
            difs["emisor_clave"] = next(iter(m.claves_banco))
        if m.banco_propio and c.receptor_clave != m.banco_propio:
            difs["receptor_clave"] = m.banco_propio
        if m.cuenta_propia and c.cuenta != m.cuenta_propia:
            difs["cuenta"] = m.cuenta_propia
    return difs


class _Indices:
    def __init__(self, movimientos: Sequence[DatosMovimiento]):
        self.rastreo: Dict[str, List[DatosMovimiento]] = {}
        self.referencia: Dict[str, List[DatosMovimiento]] = {}
        self.ref_numerica: Dict[str, List[DatosMovimiento]] = {}
        self.monto: Dict[str, List[DatosMovimiento]] = {}
        for m in movimientos:
            if m.clave_rastreo:
                self.rastreo.setdefault(normalizar_rastreo(m.clave_rastreo), []).append(m)
            if m.referencia:
                self.referencia.setdefault(_sin_ceros(m.referencia), []).append(m)
            if m.referencia_numerica:
                self.ref_numerica.setdefault(_sin_ceros(m.referencia_numerica), []).append(m)
            if m.monto:
                self.monto.setdefault(m.monto, []).append(m)


def _candidatos_fuertes(c: DatosComprobante, idx: _Indices) -> List[_Candidato]:
    cands: Dict[int, _Candidato] = {}

    def agregar(puntaje: int, estado: str, criterio: str, m: DatosMovimiento) -> None:
        actual = cands.get(m.id)
        if actual is None or puntaje > actual.puntaje:
            d = _dias(c, m)
            cands[m.id] = _Candidato(puntaje, estado, criterio, m, 99 if d is None else d)

    def problemas(m: DatosMovimiento) -> List[str]:
        p = []
        if c.monto and m.monto and c.monto != m.monto:
            p.append(f"el monto difiere ({c.monto} vs {m.monto})")
        if not _fecha_ok(c, m):
            p.append(f"la fecha difiere ({c.fecha} vs {m.fecha_operacion})")
        return p

    rastreo = normalizar_rastreo(c.clave_rastreo)
    if len(rastreo) >= LARGO_MINIMO_REFERENCIA:
        for m in idx.rastreo.get(rastreo, []):
            p = problemas(m)
            if p:
                agregar(90, "conflicto", "La clave de rastreo coincide pero " + " y ".join(p), m)
            else:
                agregar(100, "encontrado", "Clave de rastreo idéntica", m)

    if len(rastreo) >= LARGO_MINIMO_APROXIMADO and c.monto:
        for m in idx.monto.get(c.monto, []):
            otro = normalizar_rastreo(m.clave_rastreo)
            if not otro or abs(len(otro) - len(rastreo)) > DISTANCIA_RASTREO or not _fecha_ok(c, m):
                continue
            d = Levenshtein.distance(rastreo, otro, score_cutoff=DISTANCIA_RASTREO)
            if 0 < d <= DISTANCIA_RASTREO:
                agregar(85, "encontrado", f"Clave de rastreo casi idéntica ({d} carácter(es) distinto(s))", m)

    claves = {_sin_ceros(v) for v in (c.folio, c.referencia, c.clave_rastreo) if v}
    for k in (k for k in claves if len(k) >= LARGO_MINIMO_REFERENCIA):
        for m in idx.referencia.get(k, []):
            p = problemas(m)
            if not p:
                agregar(80, "encontrado", "El folio/referencia es la referencia del movimiento", m)
            elif len(p) == 1:
                agregar(72, "conflicto", "El folio/referencia coincide pero " + p[0], m)
        # La referencia numérica suele ser fija por ordenante (se repite en muchos movimientos):
        # solo vale si identifica un único movimiento con ese monto y fecha.
        numericas = [
            m for m in idx.ref_numerica.get(k, [])
            if c.monto == m.monto and _dias(c, m) is not None and _fecha_ok(c, m)
        ]
        if len(numericas) == 1:
            agregar(75, "encontrado", "Referencia numérica, monto y fecha coinciden", numericas[0])

    return sorted(cands.values(), key=lambda x: (-x.puntaje, x.dias, x.mov.id))


def conciliar(
    comprobantes: Sequence[DatosComprobante],
    movimientos: Sequence[DatosMovimiento],
    periodos: Sequence[Tuple[str, str]] = (),
) -> Dict[int, Resultado]:
    if not movimientos:
        return {c.id: Resultado("") for c in comprobantes}
    idx = _Indices(movimientos)
    resultados: Dict[int, Resultado] = {}
    dueno: Dict[int, int] = {}  # movimiento -> comprobante

    def asignar(c: DatosComprobante, cand: _Candidato) -> None:
        dueno[cand.mov.id] = c.id
        resultados[c.id] = Resultado(cand.estado, cand.mov.id, cand.criterio, diferencias(c, cand.mov))

    # 1) Coincidencias por clave: gana el mejor puntaje y, a igualdad, el comprobante más antiguo.
    fuertes = {c.id: _candidatos_fuertes(c, idx) for c in comprobantes}
    orden = sorted(
        (c for c in comprobantes if fuertes[c.id]),
        key=lambda c: (-fuertes[c.id][0].puntaje, fuertes[c.id][0].dias, c.id),
    )
    for c in orden:
        libre = next((x for x in fuertes[c.id] if x.mov.id not in dueno), None)
        if libre:
            asignar(c, libre)
            continue
        tomado = fuertes[c.id][0]
        resultados[c.id] = Resultado(
            "usado",
            tomado.mov.id,
            f"{tomado.criterio}. El movimiento ya está conciliado con el comprobante #{dueno[tomado.mov.id]}",
            diferencias(c, tomado.mov),
        )

    # 2) Monto + fecha (+ banco) entre los movimientos que siguen libres.
    for c in comprobantes:
        if c.id in resultados:
            continue
        if not (c.monto and c.fecha):
            faltan = " y ".join(n for n, v in (("el monto", c.monto), ("la fecha", c.fecha)) if not v)
            previo = "La clave/folio no aparece en el estado de cuenta; " if (c.clave_rastreo or c.folio or c.referencia) else ""
            resultados[c.id] = Resultado("no_encontrado", criterio=f"{previo}falta {faltan} para buscar por monto y fecha")
            continue
        mismos = [m for m in idx.monto.get(c.monto, []) if m.id not in dueno and _fecha_ok(c, m)]
        con_banco = [m for m in mismos if _banco_ok(c, m)]
        if len(con_banco) == 1:
            asignar(c, _Candidato(60, "probable", "Monto, fecha y banco coinciden", con_banco[0], 0))
        elif not con_banco and len(mismos) == 1:
            asignar(c, _Candidato(40, "posible", "Monto y fecha coinciden (único movimiento)", mismos[0], 0))
        else:
            ambiguos = con_banco or mismos
            resultados[c.id] = _no_encontrado(c, ambiguos, periodos)
    return resultados


def _no_encontrado(c: DatosComprobante, ambiguos: List[DatosMovimiento], periodos: Sequence[Tuple[str, str]]) -> Resultado:
    if ambiguos:
        return Resultado(
            "no_encontrado",
            criterio=f"{len(ambiguos)} movimientos con el mismo monto y fecha; elige el correcto",
            candidatos=[m.id for m in ambiguos[:20]],
        )
    if c.fecha and periodos and not any(ini <= c.fecha <= fin for ini, fin in periodos):
        return Resultado("sin_estado", criterio="No hay estado de cuenta cargado que cubra esa fecha")
    return Resultado("no_encontrado", criterio="Ningún movimiento coincide con la clave, folio, monto o fecha")


# ---------------------------------------------------------------- Base de datos


def claves_banco(m: Movimiento, cat: Catalogo) -> Set[str]:
    """Claves del catálogo que corresponden al banco de la contraparte del movimiento."""
    codigos = set()
    if m.referencia_sufijo:
        codigos.add(m.referencia_sufijo)
    if m.cuenta_contraparte and len(m.cuenta_contraparte) == 18:
        codigos.add(m.cuenta_contraparte[:3])
    if m.tipo == "pago_tercero":
        codigos.add("012")
    claves = {b.clave for b in cat.bancos if b.clave[-3:] in codigos}
    if not claves and m.banco_texto:
        texto = normalizar(m.banco_texto).strip()
        for b in cat.bancos:
            if any(normalizar(t).strip() == texto for t in [b.nombre, *b.alias] if t.strip()):
                claves.add(b.clave)
    return claves


PALABRAS_GENERICAS_TITULAR = {"CUENTA", "PRINCIPAL", "TARJETA", "CLABE", "CELULAR", "DE", "LA", "EL", "MI", "DEMO"}


def banco_estado(e: Optional[EstadoCuenta], cat: Catalogo) -> Optional[str]:
    """Clave del banco al que pertenece el estado de cuenta (p. ej. 40012 para BBVA)."""
    if e and len(e.clabe) == 18:
        clave = cat.banco_por_clabe(e.clabe)
        if clave:
            return clave
    codigo = "012" if not e or e.banco.upper() == "BBVA" else ""
    if codigo:
        cands = [b.clave for b in cat.bancos if b.clave[-3:] == codigo]
        if len(cands) == 1:
            return cands[0]
    if e and e.banco:
        nombre = normalizar(e.banco).strip()
        for b in cat.bancos:
            if any(normalizar(t).strip() == nombre for t in [b.nombre, *b.alias] if t.strip()):
                return b.clave
    return None


def cuenta_estado(
    e: Optional[EstadoCuenta],
    banco_clave: Optional[str],
    cat: Catalogo,
    texto_referencia: str = "",
) -> Optional[str]:
    """Cuenta beneficiaria del catálogo asociada al estado de cuenta."""
    if not banco_clave:
        return None
    del_banco = [c for c in cat.cuentas if c.banco_clave == banco_clave]
    if not del_banco:
        return None
    if len(del_banco) == 1:
        return del_banco[0].numero

    if e:
        for ref in (e.clabe, e.numero_cuenta):
            if not ref:
                continue
            exactas = [c for c in del_banco if c.numero == ref or c.numero.endswith(ref) or ref.endswith(c.numero)]
            if len(exactas) == 1:
                return exactas[0].numero

    ignorar = set(PALABRAS_GENERICAS_TITULAR)
    for b in cat.bancos:
        if b.clave == banco_clave:
            for t in [b.nombre, *b.alias]:
                ignorar.update(re.findall(r"[A-Z0-9]{2,}", normalizar(t)))

    texto = normalizar(texto_referencia)
    if texto:
        mejor_cuenta = None
        mejor_puntaje = 0
        for c in del_banco:
            palabras = [p for p in re.findall(r"[A-Z]{3,}", normalizar(c.titular)) if p not in ignorar]
            puntaje = sum(texto.count(p) for p in palabras)
            if puntaje > mejor_puntaje:
                mejor_puntaje = puntaje
                mejor_cuenta = c.numero
        if mejor_cuenta:
            return mejor_cuenta

    con_titular = [
        c for c in del_banco if [p for p in re.findall(r"[A-Z]{3,}", normalizar(c.titular)) if p not in ignorar]
    ]
    return (con_titular[0] if con_titular else del_banco[0]).numero


def datos_movimiento(
    m: Movimiento,
    cat: Catalogo,
    banco_propio: Optional[str] = None,
    cuenta_propia: Optional[str] = None,
) -> DatosMovimiento:
    return DatosMovimiento(
        id=m.id,
        fecha_operacion=m.fecha_operacion,
        fecha_liquidacion=m.fecha_liquidacion,
        tipo=m.tipo,
        monto=m.monto,
        clave_rastreo=m.clave_rastreo,
        referencia=m.referencia,
        referencia_numerica=m.referencia_numerica,
        claves_banco=claves_banco(m, cat),
        banco_propio=banco_propio,
        cuenta_propia=cuenta_propia,
    )


def datos_comprobante(c: Comprobante) -> DatosComprobante:
    return DatosComprobante(
        id=c.id,
        fecha=c.fecha,
        clave_rastreo=c.clave_rastreo,
        monto=c.monto,
        emisor_clave=c.emisor_clave,
        receptor_clave=c.receptor_clave,
        cuenta=c.cuenta,
        folio=c.folio,
        referencia=c.referencia,
    )


def conciliar_todo(session: Session) -> Dict[str, int]:
    """Recalcula la conciliación de todos los comprobantes. Devuelve el conteo por estado."""
    from .services import cargar_catalogo

    with _lock:
        cat = cargar_catalogo(session)
        estados = {e.id: e for e in session.exec(select(EstadoCuenta)).all()}
        filas_mov = session.exec(select(Movimiento)).all()
        texto_por_estado: Dict[int, List[str]] = {}
        for m in filas_mov:
            if m.concepto or m.nombre_contraparte:
                texto_por_estado.setdefault(m.estado_cuenta_id, []).append(f"{m.concepto} {m.nombre_contraparte}")
        info_estado: Dict[int, Tuple[Optional[str], Optional[str]]] = {}
        for eid, e in estados.items():
            b_propio = banco_estado(e, cat)
            c_propia = cuenta_estado(e, b_propio, cat, " ".join(texto_por_estado.get(eid, [])))
            info_estado[eid] = (b_propio, c_propia)

        movimientos = [
            datos_movimiento(m, cat, *info_estado.get(m.estado_cuenta_id, (None, None))) for m in filas_mov
        ]
        periodos = [(e.periodo_inicio, e.periodo_fin) for e in estados.values()]
        comprobantes = list(session.exec(select(Comprobante).where(Comprobante.estado != "procesando")).all())
        resultados = conciliar([datos_comprobante(c) for c in comprobantes], movimientos, periodos)
        conteo: Dict[str, int] = {}
        for c in comprobantes:
            r = resultados[c.id]
            detalle = json.dumps(
                {"criterio": r.criterio, "diferencias": r.diferencias, "candidatos": r.candidatos}, ensure_ascii=False
            )
            if (c.conciliacion, c.movimiento_id, c.conciliacion_detalle) != (r.estado, r.movimiento_id, detalle):
                c.conciliacion, c.movimiento_id, c.conciliacion_detalle = r.estado, r.movimiento_id, detalle
                session.add(c)
            conteo[r.estado] = conteo.get(r.estado, 0) + 1
        session.commit()
        return conteo
