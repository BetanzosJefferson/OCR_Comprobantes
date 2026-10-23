import json
import uuid
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, or_
from sqlmodel import Session, select

from ..conciliacion import claves_banco, conciliar_todo
from ..config import ESTADOS_DIR
from ..db import get_session
from ..estados_cuenta.bbva import EstadoCuentaInvalido, parsear_pdf
from ..models import CONCILIADOS, Comprobante, EstadoCuenta, Movimiento
from ..schemas import (
    AplicarMovimiento,
    ComprobanteOut,
    EstadoCuentaOut,
    MovimientoOut,
    MovimientosPagina,
    ResultadoCarga,
)
from ..services import (
    ContextoValidacion,
    aplicar_movimiento,
    cargar_catalogo,
    desaplicar_movimiento,
    recalcular_estado,
    validar,
)
from .lotes import comprobante_out, movimiento_out

router = APIRouter(prefix="/api", tags=["estados de cuenta"])


def _conciliados(session: Session) -> Dict[int, Comprobante]:
    """movimiento_id -> comprobante con el que está conciliado."""
    filas = session.exec(
        select(Comprobante).where(Comprobante.movimiento_id.is_not(None), Comprobante.conciliacion.in_(CONCILIADOS))
    ).all()
    return {c.movimiento_id: c for c in filas}


def _estado_out(session: Session, e: EstadoCuenta, conciliados: Dict[int, Comprobante]) -> EstadoCuentaOut:
    ids = session.exec(select(Movimiento.id).where(Movimiento.estado_cuenta_id == e.id)).all()
    return EstadoCuentaOut(
        id=e.id,
        nombre_original=e.nombre_original,
        banco=e.banco,
        producto=e.producto,
        numero_cuenta=e.numero_cuenta,
        clabe=e.clabe,
        periodo_inicio=e.periodo_inicio,
        periodo_fin=e.periodo_fin,
        paginas=e.paginas,
        total_cargos=e.total_cargos,
        total_abonos=e.total_abonos,
        advertencias=e.advertencias,
        cargado=e.cargado.isoformat(timespec="seconds"),
        movimientos=len(ids),
        conciliados=sum(1 for i in ids if i in conciliados),
    )


def _guardar_estado(session: Session, archivo: UploadFile) -> ResultadoCarga:
    nombre = archivo.filename or "estado.pdf"
    if Path(nombre).suffix.lower() != ".pdf":
        return ResultadoCarga(archivo=nombre, error="Solo se aceptan archivos PDF")
    destino = ESTADOS_DIR / f"{uuid.uuid4().hex}.pdf"
    with destino.open("wb") as f:
        while chunk := archivo.file.read(1024 * 1024):
            f.write(chunk)
    try:
        datos = parsear_pdf(str(destino))
    except EstadoCuentaInvalido as e:
        destino.unlink(missing_ok=True)
        return ResultadoCarga(archivo=nombre, error=str(e))

    repetido = session.exec(
        select(EstadoCuenta).where(
            EstadoCuenta.numero_cuenta == datos.numero_cuenta,
            EstadoCuenta.periodo_inicio == datos.periodo_inicio,
            EstadoCuenta.periodo_fin == datos.periodo_fin,
        )
    ).first()
    if repetido:
        destino.unlink(missing_ok=True)
        return ResultadoCarga(
            archivo=nombre,
            error=f"Ya está cargado el estado de cuenta {datos.numero_cuenta} del periodo "
            f"{datos.periodo_inicio} al {datos.periodo_fin} ({repetido.nombre_original})",
        )

    estado = EstadoCuenta(
        archivo=destino.name,
        nombre_original=nombre,
        producto=datos.producto,
        numero_cuenta=datos.numero_cuenta,
        clabe=datos.clabe,
        periodo_inicio=datos.periodo_inicio,
        periodo_fin=datos.periodo_fin,
        paginas=datos.paginas,
        total_cargos=datos.total_cargos,
        total_abonos=datos.total_abonos,
        advertencias_json=json.dumps(datos.advertencias, ensure_ascii=False),
    )
    session.add(estado)
    session.flush()

    prefijo = f"{datos.numero_cuenta}|"
    existentes = set(session.exec(select(Movimiento.huella).where(Movimiento.huella.startswith(prefijo))).all())
    cat = cargar_catalogo(session)
    vistas: Dict[str, int] = {}
    nuevos = repetidos = 0
    for mov in datos.movimientos:
        base = f"{prefijo}{mov.fecha_operacion}|{mov.referencia or ''}|{mov.monto or ''}|{mov.clave_rastreo or ''}"
        vistas[base] = vistas.get(base, 0) + 1
        huella = f"{base}#{vistas[base]}"
        if huella in existentes:
            repetidos += 1
            continue
        m = Movimiento(estado_cuenta_id=estado.id, huella=huella, **mov.__dict__)
        bancos = claves_banco(m, cat)
        m.banco_clave = next(iter(bancos)) if len(bancos) == 1 else None
        session.add(m)
        nuevos += 1
    session.commit()
    return ResultadoCarga(archivo=nombre, estado=_estado_out(session, estado, {}), nuevos=nuevos, repetidos=repetidos)


@router.post("/estados-cuenta", response_model=List[ResultadoCarga], status_code=201)
def subir_estados(archivos: List[UploadFile] = File(...), session: Session = Depends(get_session)):
    if not archivos:
        raise HTTPException(422, "No se enviaron archivos")
    resultados = [_guardar_estado(session, a) for a in archivos]
    if any(r.estado for r in resultados):
        conciliar_todo(session)
        conciliados = _conciliados(session)
        for r in resultados:
            if r.estado:
                r.estado = _estado_out(session, session.get(EstadoCuenta, r.estado.id), conciliados)
    return resultados


@router.get("/estados-cuenta", response_model=List[EstadoCuentaOut])
def listar_estados(session: Session = Depends(get_session)):
    conciliados = _conciliados(session)
    estados = session.exec(select(EstadoCuenta).order_by(EstadoCuenta.periodo_inicio.desc())).all()
    return [_estado_out(session, e, conciliados) for e in estados]


@router.delete("/estados-cuenta/{estado_id}", status_code=204)
def eliminar_estado(estado_id: int, session: Session = Depends(get_session)):
    estado = session.get(EstadoCuenta, estado_id)
    if not estado:
        raise HTTPException(404, "Estado de cuenta no encontrado")
    ids = select(Movimiento.id).where(Movimiento.estado_cuenta_id == estado_id)
    for c in session.exec(select(Comprobante).where(Comprobante.movimiento_id.in_(ids))).all():
        c.movimiento_id = None
        session.add(c)
    session.flush()
    session.exec(delete(Movimiento).where(Movimiento.estado_cuenta_id == estado_id))
    session.delete(estado)
    session.commit()
    (ESTADOS_DIR / estado.archivo).unlink(missing_ok=True)
    conciliar_todo(session)


@router.get("/movimientos", response_model=MovimientosPagina)
def listar_movimientos(
    estado_cuenta: Optional[int] = None,
    tipo: Optional[str] = None,
    conciliado: Optional[bool] = None,
    q: Optional[str] = None,
    ids: Optional[str] = Query(None, description="Lista de ids separada por comas"),
    limite: int = Query(100, ge=1, le=1000),
    desde: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    conciliados = _conciliados(session)
    consulta = select(Movimiento)
    if ids:
        consulta = consulta.where(Movimiento.id.in_([int(i) for i in ids.split(",") if i.strip().isdigit()]))
    if estado_cuenta:
        consulta = consulta.where(Movimiento.estado_cuenta_id == estado_cuenta)
    if tipo == "abonos":
        consulta = consulta.where(Movimiento.abono.is_not(None))
    elif tipo == "cargos":
        consulta = consulta.where(Movimiento.cargo.is_not(None))
    elif tipo:
        consulta = consulta.where(Movimiento.tipo == tipo)
    if conciliado is not None:
        con = Movimiento.id.in_(list(conciliados))
        consulta = consulta.where(con if conciliado else ~con)
    if q and q.strip():
        texto = q.strip()
        patron = f"%{texto}%"
        condiciones = [
            Movimiento.referencia.ilike(patron),
            Movimiento.referencia_numerica.ilike(patron),
            Movimiento.clave_rastreo.ilike(patron),
            Movimiento.nombre_contraparte.ilike(patron),
            Movimiento.concepto.ilike(patron),
            Movimiento.cuenta_contraparte.ilike(patron),
            Movimiento.banco_texto.ilike(patron),
        ]
        monto = texto.replace(",", "").replace("$", "")
        try:
            monto = f"{float(monto):.2f}"
            condiciones += [Movimiento.abono == monto, Movimiento.cargo == monto]
        except ValueError:
            pass
        consulta = consulta.where(or_(*condiciones))
    total = session.exec(select(func.count()).select_from(consulta.subquery())).one()
    filas = session.exec(
        consulta.order_by(Movimiento.fecha_operacion, Movimiento.id).offset(desde).limit(limite)
    ).all()
    return MovimientosPagina(total=total, items=[movimiento_out(m, conciliados.get(m.id)) for m in filas])


@router.post("/conciliar")
def conciliar(session: Session = Depends(get_session)):
    return conciliar_todo(session)


@router.get("/comprobantes/{comp_id}/candidatos", response_model=List[MovimientoOut])
def candidatos(comp_id: int, session: Session = Depends(get_session)):
    """Movimientos sugeridos para un comprobante sin conciliar: los ambiguos o, si no hay, los del mismo monto."""
    c = session.get(Comprobante, comp_id)
    if not c:
        raise HTTPException(404, "Comprobante no encontrado")
    conciliados = _conciliados(session)
    ids = c.detalle_conciliacion.get("candidatos") or []
    if ids:
        movs = session.exec(select(Movimiento).where(Movimiento.id.in_(ids))).all()
    elif c.monto:
        movs = session.exec(
            select(Movimiento)
            .where(or_(Movimiento.abono == c.monto, Movimiento.cargo == c.monto))
            .order_by(Movimiento.fecha_operacion)
        ).all()
        if c.fecha:
            movs = sorted(movs, key=lambda m: _dias(c.fecha, m.fecha_operacion))
        movs = movs[:20]
    else:
        movs = []
    return [movimiento_out(m, conciliados.get(m.id)) for m in movs]


def _dias(a: str, b: str) -> int:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 9999


@router.post("/comprobantes/{comp_id}/aplicar-movimiento", response_model=ComprobanteOut)
def aplicar(comp_id: int, data: AplicarMovimiento, session: Session = Depends(get_session)):
    c = session.get(Comprobante, comp_id)
    if not c:
        raise HTTPException(404, "Comprobante no encontrado")
    if c.estado == "procesando":
        raise HTTPException(409, "El comprobante aún se está procesando")
    mov_id = data.movimiento_id or c.movimiento_id
    m = session.get(Movimiento, mov_id) if mov_id else None
    if not m:
        raise HTTPException(404, "Movimiento no encontrado")
    dueno = _conciliados(session).get(m.id)
    if dueno and dueno.id != c.id:
        raise HTTPException(409, f"El movimiento ya está conciliado con el comprobante #{dueno.id} ({dueno.nombre_original})")
    estado = session.get(EstadoCuenta, m.estado_cuenta_id) if m.estado_cuenta_id else None
    if aplicar_movimiento(c, m, cargar_catalogo(session), estado) and c.estado == "revisado":
        c.estado = "incompleto"
    session.add(c)
    session.flush()
    recalcular_estado(c, validar(c, ContextoValidacion.construir(session)))
    session.add(c)
    session.commit()
    conciliar_todo(session)
    session.refresh(c)
    return comprobante_out(session, c, ContextoValidacion.construir(session))


@router.post("/comprobantes/{comp_id}/desvincular-movimiento", response_model=ComprobanteOut)
def desvincular(comp_id: int, session: Session = Depends(get_session)):
    c = session.get(Comprobante, comp_id)
    if not c:
        raise HTTPException(404, "Comprobante no encontrado")
    if c.estado == "procesando":
        raise HTTPException(409, "El comprobante aún se está procesando")
    if desaplicar_movimiento(c, cargar_catalogo(session)) and c.estado == "revisado":
        c.estado = "incompleto"
    session.add(c)
    session.flush()
    recalcular_estado(c, validar(c, ContextoValidacion.construir(session)))
    session.add(c)
    session.commit()
    conciliar_todo(session)
    session.refresh(c)
    return comprobante_out(session, c, ContextoValidacion.construir(session))

