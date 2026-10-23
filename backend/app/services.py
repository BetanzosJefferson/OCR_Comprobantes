import json
import logging
import os
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Tuple

from sqlmodel import Session, select

from .config import CONFIANZA_MINIMA, UPLOAD_DIR
from .db import engine
from .models import (
    CAMPOS,
    CAMPOS_AUXILIARES,
    ESTADOS_EXPORTABLES,
    Banco,
    Comprobante,
    CuentaBeneficiaria,
    EstadoCuenta,
    Movimiento,
)
from .ocr.engine import TesseractNoDisponible, leer_imagen
from .ocr.extractors import BancoCat, Catalogo, CuentaCat, Extraccion, extraer_mejor

log = logging.getLogger(__name__)

R_RASTREO = re.compile(r"^[A-Za-z0-9]{1,30}$")

NOMBRES_CAMPO = {
    "fecha": "Fecha",
    "clave_rastreo": "Clave de rastreo",
    "emisor_clave": "Banco emisor",
    "receptor_clave": "Banco receptor",
    "cuenta": "Cuenta beneficiaria",
    "monto": "Monto",
}


# ---------------------------------------------------------------- Catálogo


def cargar_catalogo(session: Session) -> Catalogo:
    bancos = session.exec(select(Banco)).all()
    por_id = {b.id: b for b in bancos}
    cuentas = session.exec(select(CuentaBeneficiaria).where(CuentaBeneficiaria.activa == True)).all()  # noqa: E712
    return Catalogo(
        bancos=[BancoCat(b.clave, b.nombre, b.lista_alias()) for b in bancos],
        cuentas=[
            CuentaCat(c.numero, por_id[c.banco_receptor_id].clave, c.tipo, c.titular)
            for c in cuentas
            if c.banco_receptor_id in por_id
        ],
    )


# ---------------------------------------------------------------- Normalización de entradas manuales


def normalizar_fecha(valor: str) -> str:
    v = valor.strip()
    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", v)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return v


def normalizar_monto(valor: str) -> str:
    v = re.sub(r"[\s$,]|MXN", "", valor.strip(), flags=re.I)
    try:
        return str(Decimal(v).quantize(Decimal("0.01")))
    except InvalidOperation:
        return valor.strip()


def normalizar_campo(campo: str, valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        return None
    if campo == "fecha":
        return normalizar_fecha(valor)
    if campo == "monto":
        return normalizar_monto(valor)
    if campo == "cuenta":
        return re.sub(r"\D", "", valor)
    if campo in ("clave_rastreo", "folio", "referencia"):
        return re.sub(r"\s", "", valor)
    return valor


# ---------------------------------------------------------------- Validación


@dataclass
class ContextoValidacion:
    claves_banco: Dict[str, str]
    cuentas: Dict[str, str]  # numero -> clave banco receptor (solo activas)
    primeros: Dict[Tuple[str, str, str], Tuple[int, str]] = field(default_factory=dict)

    @classmethod
    def construir(cls, session: Session) -> "ContextoValidacion":
        cat = cargar_catalogo(session)
        ctx = cls(
            claves_banco={b.clave: b.nombre for b in cat.bancos},
            cuentas={c.numero: c.banco_clave for c in cat.cuentas},
        )
        filas = session.exec(
            select(Comprobante).where(Comprobante.estado != "incidencia").order_by(Comprobante.id)
        ).all()
        for c in filas:
            if c.clave_rastreo and c.monto and c.fecha:
                ctx.primeros.setdefault(_clave_dup(c), (c.id, c.nombre_original))
        return ctx


def _clave_dup(c: Comprobante) -> Tuple[str, str, str]:
    return (c.clave_rastreo.upper(), c.monto, c.fecha)


def validar(c: Comprobante, ctx: ContextoValidacion) -> Dict[str, str]:
    errores: Dict[str, str] = {}

    if not c.fecha:
        errores["fecha"] = "Falta la fecha"
    else:
        try:
            f = date.fromisoformat(c.fecha)
            if f > date.today():
                errores["fecha"] = "La fecha está en el futuro"
        except ValueError:
            errores["fecha"] = "Formato inválido (use AAAA-MM-DD)"

    if not c.clave_rastreo:
        errores["clave_rastreo"] = "Falta la clave de rastreo"
    elif not R_RASTREO.match(c.clave_rastreo):
        errores["clave_rastreo"] = "Solo letras y números, máximo 30 caracteres"

    for campo, nombre in (("emisor_clave", "emisor"), ("receptor_clave", "receptor")):
        valor = getattr(c, campo)
        if not valor:
            errores[campo] = f"Falta el banco {nombre}"
        elif valor not in ctx.claves_banco:
            errores[campo] = f"La clave {valor} no está en el catálogo de bancos"

    if not c.cuenta:
        errores["cuenta"] = "Falta la cuenta beneficiaria"
    elif c.cuenta not in ctx.cuentas:
        errores["cuenta"] = "La cuenta no está registrada o está inactiva"
    elif c.receptor_clave and "receptor_clave" not in errores and ctx.cuentas[c.cuenta] != c.receptor_clave:
        errores["receptor_clave"] = f"La cuenta pertenece al banco {ctx.cuentas[c.cuenta]}"

    if not c.monto:
        errores["monto"] = "Falta el monto"
    else:
        try:
            m = Decimal(c.monto)
            if m <= 0:
                errores["monto"] = "El monto debe ser mayor a 0"
            elif m != m.quantize(Decimal("0.01")):
                errores["monto"] = "Máximo 2 decimales"
        except InvalidOperation:
            errores["monto"] = "Monto inválido"

    if c.clave_rastreo and c.monto and c.fecha and "clave_rastreo" not in errores:
        primero = ctx.primeros.get(_clave_dup(c))
        if primero and primero[0] != c.id and (c.id is None or primero[0] < c.id):
            errores["clave_rastreo"] = f"Duplicado del comprobante #{primero[0]} ({primero[1]})"

    return errores


def campos_baja_confianza(c: Comprobante) -> List[str]:
    conf, fuente = c.confianza, c.fuente
    return [
        campo
        for campo in CAMPOS
        if getattr(c, campo) and fuente.get(campo) != "manual" and conf.get(campo, 0) < CONFIANZA_MINIMA
    ]


def recalcular_estado(c: Comprobante, errores: Dict[str, str]) -> None:
    if c.estado in ("procesando", "incidencia"):
        return
    if errores:
        if c.estado != "error_ocr":
            c.estado = "incompleto"
        return
    if c.estado == "revisado":
        return
    c.estado = "incompleto" if campos_baja_confianza(c) else "completo"


def es_exportable(c: Comprobante, errores: Dict[str, str]) -> bool:
    return c.estado in ESTADOS_EXPORTABLES and not errores


# ---------------------------------------------------------------- Procesamiento OCR


def aplicar_extraccion(c: Comprobante, resultado: Dict[str, Extraccion]) -> None:
    """Asigna los valores extraídos sin sobrescribir lo capturado manualmente."""
    conf, fuente = c.confianza, c.fuente
    for campo in CAMPOS + CAMPOS_AUXILIARES:
        if fuente.get(campo) in ("manual", "estado_cuenta"):
            continue
        ext = resultado.get(campo, Extraccion())
        setattr(c, campo, ext.valor)
        conf[campo] = ext.confianza
        fuente[campo] = "ocr"
    c.confianza_json = json.dumps(conf)
    c.fuente_json = json.dumps(fuente)


def _procesar_uno(comp_id: int) -> None:
    with Session(engine) as session:
        c = session.get(Comprobante, comp_id)
        if not c:
            return
        try:
            resultados = leer_imagen(UPLOAD_DIR / c.archivo)
            if not resultados:
                raise ValueError("No se detectó texto en la imagen")
            textos = [r.texto for r in resultados]
            c.texto_ocr = textos[0]
            c.textos_ocr_json = json.dumps(textos, ensure_ascii=False)
            c.error = ""
            aplicar_extraccion(c, extraer_mejor(textos, cargar_catalogo(session)))
            c.estado = "completo"
        except TesseractNoDisponible as e:
            c.estado, c.error = "error_ocr", str(e)
        except Exception as e:  # noqa: BLE001 - cualquier fallo de una imagen no debe detener el lote
            log.exception("Error procesando comprobante %s", comp_id)
            c.estado, c.error = "error_ocr", f"No se pudo leer la imagen: {e}"
        recalcular_estado(c, validar(c, ContextoValidacion.construir(session)))
        session.add(c)
        session.commit()


def procesar_comprobantes(ids: Iterable[int]) -> None:
    workers = max(1, min(4, (os.cpu_count() or 2) // 2))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_procesar_uno, ids))
    from .conciliacion import conciliar_todo

    with Session(engine) as session:
        conciliar_todo(session)


def _restaurar_desde_ocr(c: Comprobante, cat: Catalogo) -> bool:
    """Revierte los campos que provienen de `estado_cuenta` a lo extraído por OCR."""
    conf, fuente = c.confianza, c.fuente
    campos_ec = [k for k in CAMPOS + CAMPOS_AUXILIARES if fuente.get(k) == "estado_cuenta"]
    if not campos_ec:
        return False
    extraidos = extraer_mejor(c.textos_ocr, cat) if c.textos_ocr else {}
    for campo in campos_ec:
        ext = extraidos.get(campo, Extraccion())
        setattr(c, campo, ext.valor)
        conf[campo] = ext.confianza
        fuente[campo] = "ocr"
    c.confianza_json, c.fuente_json = json.dumps(conf), json.dumps(fuente)
    return True


def aplicar_movimiento(c: Comprobante, m: Movimiento, cat: Catalogo, estado: Optional[EstadoCuenta] = None) -> bool:
    """Completa o corrige el comprobante con los datos del movimiento del estado de cuenta.

    Devuelve si cambió algún dato.
    """
    from .conciliacion import banco_estado, claves_banco, cuenta_estado

    # Si ya tenía datos de un movimiento previo elegido por error, se limpian primero.
    cambio = _restaurar_desde_ocr(c, cat)

    valores: Dict[str, Optional[str]] = {"fecha": m.fecha_operacion, "monto": m.monto}
    if m.clave_rastreo:
        valores["clave_rastreo"] = m.clave_rastreo
    elif m.referencia:
        # Sin clave de rastreo, la referencia es lo que vuelve a ligar el comprobante al movimiento.
        valores["folio"] = m.referencia
        if not c.clave_rastreo or c.clave_rastreo.lstrip("0") == m.referencia.lstrip("0"):
            valores["clave_rastreo"] = m.referencia
    bancos = claves_banco(m, cat)
    b_propio = banco_estado(estado, cat)
    if m.tipo == "spei_enviado":
        if b_propio:
            valores["emisor_clave"] = b_propio
        if len(bancos) == 1:
            valores["receptor_clave"] = next(iter(bancos))
    else:
        if len(bancos) == 1:
            valores["emisor_clave"] = next(iter(bancos))
        if b_propio:
            valores["receptor_clave"] = b_propio
        texto_ref = f"{c.texto_ocr or ''} {m.concepto or ''} {m.nombre_contraparte or ''}"
        c_propia = cuenta_estado(estado, b_propio, cat, texto_ref)
        if not c_propia and b_propio:
            # Si el texto de este movimiento no menciona al titular, busca en los demás del mismo estado.
            sess = Session.object_session(m)
            if sess and m.estado_cuenta_id:
                otros = sess.exec(select(Movimiento).where(Movimiento.estado_cuenta_id == m.estado_cuenta_id)).all()
                c_propia = cuenta_estado(
                    estado, b_propio, cat, " ".join(f"{x.concepto} {x.nombre_contraparte}" for x in otros)
                )
        if c_propia:
            valores["cuenta"] = c_propia
    conf, fuente = c.confianza, c.fuente
    for campo, valor in valores.items():
        if not valor:
            continue
        if getattr(c, campo) != valor:
            setattr(c, campo, valor)
            conf[campo], fuente[campo] = 1.0, "estado_cuenta"
            cambio = True
        elif conf.get(campo, 0.0) < 1.0:
            # El OCR ya había leído el valor correcto pero con baja confianza: se confirma sin cambiar su fuente.
            conf[campo] = 1.0
            cambio = True
    c.confianza_json, c.fuente_json = json.dumps(conf), json.dumps(fuente)
    c.movimiento_id = m.id
    return cambio


def desaplicar_movimiento(c: Comprobante, cat: Catalogo) -> bool:
    """Quita el movimiento aplicado y restaura los campos tomados del estado de cuenta."""
    cambio = _restaurar_desde_ocr(c, cat)
    if c.movimiento_id is not None:
        c.movimiento_id = None
        cambio = True
    return cambio


def reextraer(session: Session, comprobantes: Iterable[Comprobante]) -> int:
    """Vuelve a aplicar los extractores sobre el texto OCR guardado (p. ej. tras cambiar catálogos)."""
    comprobantes = list(comprobantes)
    cat = cargar_catalogo(session)
    n = 0
    for c in comprobantes:
        if not c.textos_ocr or c.estado == "procesando":
            continue
        antes = [getattr(c, campo) for campo in CAMPOS]
        aplicar_extraccion(c, extraer_mejor(c.textos_ocr, cat))
        # Lo revisado ya no vale si cambió algún dato: hay que volver a confirmarlo.
        if c.estado == "revisado" and antes != [getattr(c, campo) for campo in CAMPOS]:
            c.estado = "incompleto"
        session.add(c)
        n += 1
    session.commit()
    ctx = ContextoValidacion.construir(session)
    for c in comprobantes:
        recalcular_estado(c, validar(c, ctx))
        session.add(c)
    session.commit()
    return n


# ---------------------------------------------------------------- Exportación


def linea_txt(c: Comprobante) -> str:
    return ",".join([c.fecha, c.clave_rastreo, c.emisor_clave, c.receptor_clave, c.cuenta, c.monto])


def _exportables(comprobantes: Iterable[Comprobante], ctx: ContextoValidacion) -> Tuple[List[Comprobante], int]:
    listos, omitidos = [], 0
    for c in comprobantes:
        if es_exportable(c, validar(c, ctx)):
            listos.append(c)
        else:
            omitidos += 1
    return listos, omitidos


def generar_txt(comprobantes: Iterable[Comprobante], ctx: ContextoValidacion) -> Tuple[str, int, int]:
    """Devuelve (contenido, exportados, omitidos)."""
    listos, omitidos = _exportables(comprobantes, ctx)
    lineas = [linea_txt(c) for c in listos]
    contenido = "\n".join(lineas) + ("\n" if lineas else "")
    return contenido, len(lineas), omitidos


def generar_json(comprobantes: Iterable[Comprobante], ctx: ContextoValidacion) -> Tuple[str, int, int]:
    """Devuelve (contenido, exportados, omitidos).

    id es el nombre del archivo sin extensión, wallet es la cuenta beneficiaria.
    """
    listos, omitidos = _exportables(comprobantes, ctx)
    filas = [
        {
            "id": Path(c.nombre_original).stem,
            "date": c.fecha,
            "key": c.clave_rastreo,
            "wallet": c.cuenta,
        }
        for c in listos
    ]
    return json.dumps(filas, ensure_ascii=False, indent=2) + "\n", len(filas), omitidos


ETIQUETA_CONCILIACION = {
    "": "Sin estados de cuenta",
    "encontrado": "Encontrado",
    "probable": "Probable",
    "posible": "Posible",
    "conflicto": "Conflicto",
    "usado": "Movimiento ya usado",
    "no_encontrado": "No encontrado",
    "sin_estado": "Sin estado de cuenta del periodo",
}
CONCILIACION_INCIDENCIA = {"conflicto", "usado", "no_encontrado"}


def filas_incidencias(comprobantes: Iterable[Comprobante], ctx: ContextoValidacion) -> List[List[str]]:
    filas = []
    for c in comprobantes:
        errores = validar(c, ctx)
        if es_exportable(c, errores) and c.conciliacion not in CONCILIACION_INCIDENCIA:
            continue
        problemas = [f"{NOMBRES_CAMPO[k]}: {v}" for k, v in errores.items()]
        problemas += [f"{NOMBRES_CAMPO[k]}: baja confianza" for k in campos_baja_confianza(c) if k not in errores]
        if c.error:
            problemas.append(c.error)
        filas.append(
            [
                c.nombre_original,
                c.estado,
                "; ".join(problemas),
                c.comentario,
                c.fecha or "",
                c.clave_rastreo or "",
                c.emisor_clave or "",
                c.receptor_clave or "",
                c.cuenta or "",
                c.monto or "",
                c.folio or "",
                c.referencia or "",
                ETIQUETA_CONCILIACION.get(c.conciliacion or "", c.conciliacion),
                c.detalle_conciliacion.get("criterio", ""),
            ]
        )
    return filas


def sello_fecha() -> str:
    return datetime.now().strftime("%Y-%m-%d")
