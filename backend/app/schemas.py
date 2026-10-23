from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class BancoIn(BaseModel):
    nombre: str = Field(min_length=1)
    clave: str = Field(min_length=1, pattern=r"^\d+$")
    alias: List[str] = []

    @field_validator("nombre", "clave")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class BancoOut(BaseModel):
    id: int
    nombre: str
    clave: str
    alias: List[str]


class CuentaIn(BaseModel):
    numero: str = Field(min_length=4)
    tipo: str = "clabe"
    banco_receptor_id: int
    titular: str = ""
    activa: bool = True

    @field_validator("numero")
    @classmethod
    def _solo_digitos(cls, v: str) -> str:
        digitos = "".join(c for c in v if c.isdigit())
        if len(digitos) < 4:
            raise ValueError("El número de cuenta debe tener al menos 4 dígitos")
        return digitos


class CuentaOut(BaseModel):
    id: int
    numero: str
    tipo: str
    banco_receptor_id: int
    banco_receptor_clave: Optional[str]
    banco_receptor_nombre: Optional[str]
    titular: str
    activa: bool


class LoteOut(BaseModel):
    id: int
    nombre: str
    creado: str
    total: int
    por_estado: Dict[str, int]


class MovimientoOut(BaseModel):
    id: int
    estado_cuenta_id: int
    pagina: int
    fecha_operacion: str
    fecha_liquidacion: str
    tipo: str
    descripcion: str
    banco_texto: str
    banco_clave: Optional[str]
    referencia: Optional[str]
    referencia_sufijo: Optional[str]
    referencia_numerica: Optional[str]
    concepto: str
    cuenta_contraparte: Optional[str]
    clave_rastreo: Optional[str]
    nombre_contraparte: str
    cargo: Optional[str]
    abono: Optional[str]
    texto_crudo: str
    # Comprobante con el que quedó conciliado, si lo hay.
    comprobante_id: Optional[int] = None
    comprobante_nombre: Optional[str] = None


class MovimientosPagina(BaseModel):
    total: int
    items: List[MovimientoOut]


class EstadoCuentaOut(BaseModel):
    id: int
    nombre_original: str
    banco: str
    producto: str
    numero_cuenta: str
    clabe: str
    periodo_inicio: str
    periodo_fin: str
    paginas: int
    total_cargos: Optional[str]
    total_abonos: Optional[str]
    advertencias: List[str]
    cargado: str
    movimientos: int
    conciliados: int


class ResultadoCarga(BaseModel):
    archivo: str
    error: Optional[str] = None
    estado: Optional[EstadoCuentaOut] = None
    nuevos: int = 0
    repetidos: int = 0


class AplicarMovimiento(BaseModel):
    movimiento_id: Optional[int] = None


class ComprobanteOut(BaseModel):
    id: int
    lote_id: int
    archivo: str
    nombre_original: str
    imagen_url: str
    estado: str
    fecha: Optional[str]
    clave_rastreo: Optional[str]
    emisor_clave: Optional[str]
    receptor_clave: Optional[str]
    cuenta: Optional[str]
    monto: Optional[str]
    folio: Optional[str]
    referencia: Optional[str]
    confianza: Dict[str, float]
    fuente: Dict[str, str]
    errores: Dict[str, str]
    texto_ocr: str
    comentario: str
    error: str
    exportable: bool
    conciliacion: str
    conciliacion_criterio: str
    # Valores del estado de cuenta que faltan o difieren en el comprobante.
    conciliacion_diferencias: Dict[str, str]
    candidatos: List[int]
    movimiento: Optional[MovimientoOut]


class LoteDetalle(BaseModel):
    lote: LoteOut
    comprobantes: List[ComprobanteOut]


class ComprobantePatch(BaseModel):
    fecha: Optional[str] = None
    clave_rastreo: Optional[str] = None
    emisor_clave: Optional[str] = None
    receptor_clave: Optional[str] = None
    cuenta: Optional[str] = None
    monto: Optional[str] = None
    folio: Optional[str] = None
    referencia: Optional[str] = None
    comentario: Optional[str] = None
    # "revisado", "incidencia" o "auto" (recalcular estado según validaciones)
    estado: Optional[str] = None
