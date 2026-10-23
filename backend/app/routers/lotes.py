import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps
from sqlmodel import Session, select

from ..conciliacion import conciliar_todo
from ..config import ALLOWED_EXTENSIONS, UPLOAD_DIR
from ..db import get_session
from ..models import CAMPOS, CAMPOS_AUXILIARES, Comprobante, Lote, Movimiento
from ..ocr import preprocess  # noqa: F401  (registra el lector HEIC en Pillow)
from ..routers.catalogos import _csv_response
from ..schemas import ComprobanteOut, ComprobantePatch, LoteDetalle, LoteOut, MovimientoOut
from ..services import (
    ContextoValidacion,
    es_exportable,
    filas_incidencias,
    generar_json,
    generar_txt,
    normalizar_campo,
    procesar_comprobantes,
    recalcular_estado,
    reextraer,
    sello_fecha,
    validar,
)

router = APIRouter(prefix="/api", tags=["lotes"])

ENCABEZADO_INCIDENCIAS = [
    "archivo", "estado", "problemas", "comentario",
    "fecha", "clave_rastreo", "emisor", "receptor", "cuenta", "monto", "folio", "referencia",
    "estado_de_cuenta", "detalle_estado_de_cuenta",
]


def _lote_out(lote: Lote, comprobantes: List[Comprobante]) -> LoteOut:
    return LoteOut(
        id=lote.id,
        nombre=lote.nombre,
        creado=lote.creado.isoformat(timespec="seconds"),
        total=len(comprobantes),
        por_estado=dict(Counter(c.estado for c in comprobantes)),
    )


def movimiento_out(m: Movimiento, comprobante: Optional[Comprobante] = None) -> MovimientoOut:
    return MovimientoOut(
        **m.model_dump(),
        comprobante_id=comprobante.id if comprobante else None,
        comprobante_nombre=comprobante.nombre_original if comprobante else None,
    )


def _movimientos_de(session: Session, comprobantes: List[Comprobante]) -> Dict[int, Movimiento]:
    ids = {c.movimiento_id for c in comprobantes if c.movimiento_id}
    if not ids:
        return {}
    return {m.id: m for m in session.exec(select(Movimiento).where(Movimiento.id.in_(ids))).all()}


def comprobante_out(session: Session, c: Comprobante, ctx: ContextoValidacion) -> ComprobanteOut:
    return _comprobante_out(c, ctx, _movimientos_de(session, [c]))


def _comprobante_out(c: Comprobante, ctx: ContextoValidacion, movimientos: Dict[int, Movimiento]) -> ComprobanteOut:
    errores = {} if c.estado == "procesando" else validar(c, ctx)
    detalle = c.detalle_conciliacion
    mov = movimientos.get(c.movimiento_id) if c.movimiento_id else None
    return ComprobanteOut(
        id=c.id,
        lote_id=c.lote_id,
        archivo=c.archivo,
        nombre_original=c.nombre_original,
        imagen_url=f"/api/imagenes/{c.archivo}",
        estado=c.estado,
        fecha=c.fecha,
        clave_rastreo=c.clave_rastreo,
        emisor_clave=c.emisor_clave,
        receptor_clave=c.receptor_clave,
        cuenta=c.cuenta,
        monto=c.monto,
        folio=c.folio,
        referencia=c.referencia,
        confianza=c.confianza,
        fuente=c.fuente,
        errores=errores,
        texto_ocr=c.texto_ocr,
        comentario=c.comentario,
        error=c.error,
        exportable=es_exportable(c, errores),
        conciliacion=c.conciliacion or "",
        conciliacion_criterio=detalle.get("criterio", ""),
        conciliacion_diferencias=detalle.get("diferencias", {}),
        candidatos=detalle.get("candidatos", []),
        movimiento=movimiento_out(mov) if mov else None,
    )


def _comprobantes(session: Session, lote_id: int) -> List[Comprobante]:
    return list(
        session.exec(select(Comprobante).where(Comprobante.lote_id == lote_id).order_by(Comprobante.id)).all()
    )


def _lote_o_404(session: Session, lote_id: int) -> Lote:
    lote = session.get(Lote, lote_id)
    if not lote:
        raise HTTPException(404, "Lote no encontrado")
    return lote


def _guardar_imagen(archivo: UploadFile) -> str:
    ext = Path(archivo.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(422, f"Formato no soportado: {archivo.filename}")
    nombre = uuid.uuid4().hex
    if ext in {".heic", ".heif"}:
        # Los navegadores no muestran HEIC: se guarda como JPEG para poder previsualizarlo.
        with Image.open(archivo.file) as img:
            ImageOps.exif_transpose(img).convert("RGB").save(UPLOAD_DIR / f"{nombre}.jpg", quality=95)
        return f"{nombre}.jpg"
    destino = UPLOAD_DIR / f"{nombre}{ext}"
    with destino.open("wb") as f:
        while chunk := archivo.file.read(1024 * 1024):
            f.write(chunk)
    return destino.name


def _agregar_archivos(session: Session, lote: Lote, archivos: List[UploadFile]) -> List[int]:
    if not archivos:
        raise HTTPException(422, "No se enviaron imágenes")
    for a in archivos:
        if Path(a.filename or "").suffix.lower() not in ALLOWED_EXTENSIONS:
            raise HTTPException(422, f"Formato no soportado: {a.filename}")
    ids = []
    for a in archivos:
        c = Comprobante(lote_id=lote.id, archivo=_guardar_imagen(a), nombre_original=a.filename or "")
        session.add(c)
        session.flush()
        ids.append(c.id)
    session.commit()
    return ids


# ---------------------------------------------------------------- Lotes


@router.get("/lotes", response_model=List[LoteOut])
def listar_lotes(session: Session = Depends(get_session)):
    lotes = session.exec(select(Lote).order_by(Lote.id.desc())).all()
    return [_lote_out(l, _comprobantes(session, l.id)) for l in lotes]


@router.post("/lotes", response_model=LoteOut, status_code=201)
def crear_lote(
    background: BackgroundTasks,
    archivos: List[UploadFile] = File(...),
    nombre: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    lote = Lote(nombre=(nombre or "").strip() or f"Lote {sello_fecha()}")
    session.add(lote)
    session.flush()
    ids = _agregar_archivos(session, lote, archivos)
    background.add_task(procesar_comprobantes, ids)
    return _lote_out(lote, _comprobantes(session, lote.id))


@router.post("/lotes/{lote_id}/comprobantes", response_model=LoteOut)
def agregar_a_lote(
    lote_id: int,
    background: BackgroundTasks,
    archivos: List[UploadFile] = File(...),
    session: Session = Depends(get_session),
):
    lote = _lote_o_404(session, lote_id)
    ids = _agregar_archivos(session, lote, archivos)
    background.add_task(procesar_comprobantes, ids)
    return _lote_out(lote, _comprobantes(session, lote.id))


@router.get("/lotes/{lote_id}", response_model=LoteDetalle)
def detalle_lote(lote_id: int, session: Session = Depends(get_session)):
    lote = _lote_o_404(session, lote_id)
    comprobantes = _comprobantes(session, lote_id)
    ctx = ContextoValidacion.construir(session)
    movimientos = _movimientos_de(session, comprobantes)
    return LoteDetalle(
        lote=_lote_out(lote, comprobantes),
        comprobantes=[_comprobante_out(c, ctx, movimientos) for c in comprobantes],
    )


@router.delete("/lotes/{lote_id}", status_code=204)
def eliminar_lote(lote_id: int, session: Session = Depends(get_session)):
    lote = _lote_o_404(session, lote_id)
    for c in _comprobantes(session, lote_id):
        (UPLOAD_DIR / c.archivo).unlink(missing_ok=True)
        session.delete(c)
    session.delete(lote)
    session.commit()
    conciliar_todo(session)


@router.post("/lotes/{lote_id}/reextraer")
def reextraer_lote(lote_id: int, session: Session = Depends(get_session)):
    _lote_o_404(session, lote_id)
    n = reextraer(session, _comprobantes(session, lote_id))
    conciliar_todo(session)
    return {"reextraidos": n}


@router.get("/lotes/{lote_id}/export.txt")
def exportar_txt(lote_id: int, session: Session = Depends(get_session)):
    _lote_o_404(session, lote_id)
    contenido, exportados, omitidos = generar_txt(_comprobantes(session, lote_id), ContextoValidacion.construir(session))
    return Response(
        content=contenido.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="comprobantes_lote{lote_id}_{sello_fecha()}.txt"',
            "X-Exportados": str(exportados),
            "X-Omitidos": str(omitidos),
            "Access-Control-Expose-Headers": "X-Exportados, X-Omitidos",
        },
    )


@router.get("/lotes/{lote_id}/export.json")
def exportar_json(lote_id: int, session: Session = Depends(get_session)):
    _lote_o_404(session, lote_id)
    contenido, exportados, omitidos = generar_json(_comprobantes(session, lote_id), ContextoValidacion.construir(session))
    return Response(
        content=contenido.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="comprobantes_lote{lote_id}_{sello_fecha()}.json"',
            "X-Exportados": str(exportados),
            "X-Omitidos": str(omitidos),
            "Access-Control-Expose-Headers": "X-Exportados, X-Omitidos",
        },
    )


@router.get("/lotes/{lote_id}/incidencias.csv")
def exportar_incidencias(lote_id: int, session: Session = Depends(get_session)):
    _lote_o_404(session, lote_id)
    filas = filas_incidencias(_comprobantes(session, lote_id), ContextoValidacion.construir(session))
    return _csv_response(f"incidencias_{sello_fecha()}.csv", ENCABEZADO_INCIDENCIAS, filas)


# ---------------------------------------------------------------- Comprobantes


def _comprobante_o_404(session: Session, comp_id: int) -> Comprobante:
    c = session.get(Comprobante, comp_id)
    if not c:
        raise HTTPException(404, "Comprobante no encontrado")
    return c


@router.patch("/comprobantes/{comp_id}", response_model=ComprobanteOut)
def editar_comprobante(comp_id: int, data: ComprobantePatch, session: Session = Depends(get_session)):
    c = _comprobante_o_404(session, comp_id)
    if c.estado == "procesando":
        raise HTTPException(409, "El comprobante aún se está procesando")

    cambios = data.model_dump(exclude_unset=True)
    conf, fuente = c.confianza, c.fuente
    for campo in CAMPOS + CAMPOS_AUXILIARES:
        if campo in cambios:
            nuevo = normalizar_campo(campo, cambios[campo])
            if nuevo != getattr(c, campo):
                setattr(c, campo, nuevo)
                conf[campo] = 1.0 if nuevo else 0.0
                fuente[campo] = "manual"
    c.confianza_json, c.fuente_json = json.dumps(conf), json.dumps(fuente)
    if "comentario" in cambios:
        c.comentario = (cambios["comentario"] or "").strip()

    session.add(c)
    session.flush()
    ctx = ContextoValidacion.construir(session)
    errores = validar(c, ctx)

    estado = cambios.get("estado")
    if estado == "incidencia":
        c.estado = "incidencia"
    elif estado == "revisado":
        if errores:
            session.rollback()
            detalle = "; ".join(errores.values())
            raise HTTPException(422, f"No se puede marcar como revisado: {detalle}")
        c.estado = "revisado"
    elif estado == "auto":
        c.estado = "error_ocr" if c.error and not any(getattr(c, k) for k in CAMPOS) else "incompleto"
        recalcular_estado(c, errores)
    elif estado is not None:
        raise HTTPException(422, "Estado inválido (revisado, incidencia o auto)")
    else:
        recalcular_estado(c, errores)

    session.add(c)
    session.commit()
    conciliar_todo(session)
    session.refresh(c)
    return comprobante_out(session, c, ContextoValidacion.construir(session))


@router.post("/comprobantes/{comp_id}/reprocesar", response_model=ComprobanteOut)
def reprocesar_comprobante(comp_id: int, background: BackgroundTasks, session: Session = Depends(get_session)):
    c = _comprobante_o_404(session, comp_id)
    c.estado = "procesando"
    session.add(c)
    session.commit()
    session.refresh(c)
    background.add_task(procesar_comprobantes, [c.id])
    return comprobante_out(session, c, ContextoValidacion.construir(session))


@router.delete("/comprobantes/{comp_id}", status_code=204)
def eliminar_comprobante(comp_id: int, session: Session = Depends(get_session)):
    c = _comprobante_o_404(session, comp_id)
    (UPLOAD_DIR / c.archivo).unlink(missing_ok=True)
    session.delete(c)
    session.commit()
    conciliar_todo(session)
