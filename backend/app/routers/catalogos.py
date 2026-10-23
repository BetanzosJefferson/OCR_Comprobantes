import csv
import io
from typing import Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlmodel import Session, select

from ..db import get_session
from ..models import TIPOS_CUENTA, Banco, CuentaBeneficiaria
from ..schemas import BancoIn, BancoOut, CuentaIn, CuentaOut

router = APIRouter(prefix="/api", tags=["catalogos"])


def _banco_out(b: Banco) -> BancoOut:
    return BancoOut(id=b.id, nombre=b.nombre, clave=b.clave, alias=b.lista_alias())


def _cuenta_out(c: CuentaBeneficiaria, bancos: Dict[int, Banco]) -> CuentaOut:
    banco = bancos.get(c.banco_receptor_id)
    return CuentaOut(
        id=c.id,
        numero=c.numero,
        tipo=c.tipo,
        banco_receptor_id=c.banco_receptor_id,
        banco_receptor_clave=banco.clave if banco else None,
        banco_receptor_nombre=banco.nombre if banco else None,
        titular=c.titular,
        activa=c.activa,
    )


def _bancos_por_id(session: Session) -> Dict[int, Banco]:
    return {b.id: b for b in session.exec(select(Banco)).all()}


def _leer_csv(archivo: UploadFile) -> List[Dict[str, str]]:
    contenido = archivo.file.read().decode("utf-8-sig")
    return [
        {(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
        for fila in csv.DictReader(io.StringIO(contenido))
    ]


def _csv_response(nombre: str, encabezado: List[str], filas: List[List[str]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(encabezado)
    writer.writerows(filas)
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# ---------------------------------------------------------------- Bancos


@router.get("/bancos", response_model=List[BancoOut])
def listar_bancos(session: Session = Depends(get_session)):
    bancos = session.exec(select(Banco).order_by(Banco.nombre)).all()
    return [_banco_out(b) for b in bancos]


def _guardar_banco(session: Session, banco: Banco, data: BancoIn) -> Banco:
    duplicado = session.exec(select(Banco).where(Banco.clave == data.clave, Banco.id != banco.id)).first()
    if duplicado:
        raise HTTPException(409, f"Ya existe un banco con la clave {data.clave} ({duplicado.nombre})")
    banco.nombre = data.nombre
    banco.clave = data.clave
    banco.alias = "|".join(a.strip() for a in data.alias if a.strip())
    session.add(banco)
    session.commit()
    session.refresh(banco)
    return banco


@router.post("/bancos", response_model=BancoOut, status_code=201)
def crear_banco(data: BancoIn, session: Session = Depends(get_session)):
    return _banco_out(_guardar_banco(session, Banco(nombre=data.nombre, clave=data.clave), data))


@router.put("/bancos/{banco_id}", response_model=BancoOut)
def actualizar_banco(banco_id: int, data: BancoIn, session: Session = Depends(get_session)):
    banco = session.get(Banco, banco_id)
    if not banco:
        raise HTTPException(404, "Banco no encontrado")
    return _banco_out(_guardar_banco(session, banco, data))


@router.delete("/bancos/{banco_id}", status_code=204)
def eliminar_banco(banco_id: int, session: Session = Depends(get_session)):
    banco = session.get(Banco, banco_id)
    if not banco:
        raise HTTPException(404, "Banco no encontrado")
    en_uso = session.exec(
        select(CuentaBeneficiaria).where(CuentaBeneficiaria.banco_receptor_id == banco_id)
    ).first()
    if en_uso:
        raise HTTPException(409, f"El banco está asignado a la cuenta {en_uso.numero}")
    session.delete(banco)
    session.commit()


@router.get("/bancos/export.csv")
def exportar_bancos(session: Session = Depends(get_session)):
    bancos = session.exec(select(Banco).order_by(Banco.nombre)).all()
    return _csv_response("bancos.csv", ["clave", "nombre", "alias"], [[b.clave, b.nombre, b.alias] for b in bancos])


@router.post("/bancos/import")
def importar_bancos(archivo: UploadFile = File(...), session: Session = Depends(get_session)):
    """CSV con columnas clave,nombre,alias (alias separados por "|"). Actualiza por clave."""
    creados = actualizados = 0
    errores: List[str] = []
    for i, fila in enumerate(_leer_csv(archivo), start=2):
        clave, nombre = fila.get("clave", ""), fila.get("nombre", "")
        if not clave.isdigit() or not nombre:
            errores.append(f"Línea {i}: clave numérica y nombre son obligatorios")
            continue
        banco = session.exec(select(Banco).where(Banco.clave == clave)).first()
        if banco:
            actualizados += 1
        else:
            banco = Banco(clave=clave, nombre=nombre)
            creados += 1
        banco.nombre = nombre
        banco.alias = "|".join(a.strip() for a in fila.get("alias", "").split("|") if a.strip())
        session.add(banco)
    session.commit()
    return {"creados": creados, "actualizados": actualizados, "errores": errores}


# ---------------------------------------------------------------- Cuentas


@router.get("/cuentas", response_model=List[CuentaOut])
def listar_cuentas(session: Session = Depends(get_session)):
    bancos = _bancos_por_id(session)
    cuentas = session.exec(select(CuentaBeneficiaria).order_by(CuentaBeneficiaria.titular)).all()
    return [_cuenta_out(c, bancos) for c in cuentas]


def _guardar_cuenta(session: Session, cuenta: CuentaBeneficiaria, data: CuentaIn) -> CuentaOut:
    if data.tipo not in TIPOS_CUENTA:
        raise HTTPException(422, f"Tipo inválido. Opciones: {', '.join(TIPOS_CUENTA)}")
    if not session.get(Banco, data.banco_receptor_id):
        raise HTTPException(422, "El banco receptor no existe")
    duplicada = session.exec(
        select(CuentaBeneficiaria).where(
            CuentaBeneficiaria.numero == data.numero, CuentaBeneficiaria.id != cuenta.id
        )
    ).first()
    if duplicada:
        raise HTTPException(409, f"La cuenta {data.numero} ya está registrada")
    for campo, valor in data.model_dump().items():
        setattr(cuenta, campo, valor)
    session.add(cuenta)
    session.commit()
    session.refresh(cuenta)
    return _cuenta_out(cuenta, _bancos_por_id(session))


@router.post("/cuentas", response_model=CuentaOut, status_code=201)
def crear_cuenta(data: CuentaIn, session: Session = Depends(get_session)):
    return _guardar_cuenta(session, CuentaBeneficiaria(numero=data.numero, banco_receptor_id=data.banco_receptor_id), data)


@router.put("/cuentas/{cuenta_id}", response_model=CuentaOut)
def actualizar_cuenta(cuenta_id: int, data: CuentaIn, session: Session = Depends(get_session)):
    cuenta = session.get(CuentaBeneficiaria, cuenta_id)
    if not cuenta:
        raise HTTPException(404, "Cuenta no encontrada")
    return _guardar_cuenta(session, cuenta, data)


@router.delete("/cuentas/{cuenta_id}", status_code=204)
def eliminar_cuenta(cuenta_id: int, session: Session = Depends(get_session)):
    cuenta = session.get(CuentaBeneficiaria, cuenta_id)
    if not cuenta:
        raise HTTPException(404, "Cuenta no encontrada")
    session.delete(cuenta)
    session.commit()


@router.get("/cuentas/export.csv")
def exportar_cuentas(session: Session = Depends(get_session)):
    bancos = _bancos_por_id(session)
    cuentas = session.exec(select(CuentaBeneficiaria)).all()
    filas = [
        [c.numero, c.tipo, bancos[c.banco_receptor_id].clave if c.banco_receptor_id in bancos else "", c.titular, "1" if c.activa else "0"]
        for c in cuentas
    ]
    return _csv_response("cuentas.csv", ["numero", "tipo", "banco_clave", "titular", "activa"], filas)


@router.post("/cuentas/import")
def importar_cuentas(archivo: UploadFile = File(...), session: Session = Depends(get_session)):
    """CSV con columnas numero,tipo,banco_clave,titular,activa. Actualiza por número."""
    bancos_por_clave = {b.clave: b for b in session.exec(select(Banco)).all()}
    creados = actualizados = 0
    errores: List[str] = []
    for i, fila in enumerate(_leer_csv(archivo), start=2):
        numero = "".join(c for c in fila.get("numero", "") if c.isdigit())
        banco = bancos_por_clave.get(fila.get("banco_clave", ""))
        tipo = (fila.get("tipo") or "clabe").lower()
        if len(numero) < 4:
            errores.append(f"Línea {i}: número de cuenta inválido")
            continue
        if not banco:
            errores.append(f"Línea {i}: banco_clave '{fila.get('banco_clave', '')}' no está configurado")
            continue
        if tipo not in TIPOS_CUENTA:
            errores.append(f"Línea {i}: tipo '{tipo}' inválido")
            continue
        cuenta = session.exec(select(CuentaBeneficiaria).where(CuentaBeneficiaria.numero == numero)).first()
        if cuenta:
            actualizados += 1
        else:
            cuenta = CuentaBeneficiaria(numero=numero, banco_receptor_id=banco.id)
            creados += 1
        cuenta.tipo = tipo
        cuenta.banco_receptor_id = banco.id
        cuenta.titular = fila.get("titular", "")
        cuenta.activa = fila.get("activa", "1").lower() not in {"0", "no", "false", "inactiva"}
        session.add(cuenta)
    session.commit()
    return {"creados": creados, "actualizados": actualizados, "errores": errores}
