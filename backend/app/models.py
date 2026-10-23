import json
from datetime import datetime
from typing import Dict, List, Optional

from sqlmodel import Field, SQLModel

CAMPOS = ["fecha", "clave_rastreo", "emisor_clave", "receptor_clave", "cuenta", "monto"]
# Datos que ayudan a conciliar contra el estado de cuenta pero no van al TXT.
CAMPOS_AUXILIARES = ["folio", "referencia"]

TIPOS_MOVIMIENTO = ["spei_recibido", "spei_enviado", "spei_devuelto", "pago_tercero", "otro"]
# "" = aún no hay estados de cuenta cargados.
CONCILIACIONES = ["encontrado", "probable", "posible", "conflicto", "usado", "no_encontrado", "sin_estado"]
CONCILIADOS = {"encontrado", "probable", "posible", "conflicto"}

ESTADOS = ["procesando", "completo", "incompleto", "error_ocr", "revisado", "incidencia"]
ESTADOS_EXPORTABLES = {"completo", "revisado"}

TIPOS_CUENTA = ["clabe", "tarjeta", "celular", "cuenta"]


class Banco(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str
    clave: str = Field(index=True, unique=True)
    # Textos con los que aparece el banco en los comprobantes, separados por "|".
    alias: str = ""

    def lista_alias(self) -> List[str]:
        return [a.strip() for a in self.alias.split("|") if a.strip()]


class CuentaBeneficiaria(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    numero: str = Field(index=True, unique=True)
    tipo: str = "clabe"
    banco_receptor_id: int = Field(foreign_key="banco.id")
    titular: str = ""
    activa: bool = True


class Lote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = ""
    creado: datetime = Field(default_factory=datetime.now)


class Comprobante(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lote_id: int = Field(foreign_key="lote.id", index=True)
    archivo: str
    nombre_original: str
    estado: str = "procesando"

    fecha: Optional[str] = None
    clave_rastreo: Optional[str] = None
    emisor_clave: Optional[str] = None
    receptor_clave: Optional[str] = None
    cuenta: Optional[str] = None
    monto: Optional[str] = None

    folio: Optional[str] = None
    referencia: Optional[str] = None

    confianza_json: str = "{}"
    fuente_json: str = "{}"
    texto_ocr: str = ""
    textos_ocr_json: str = "[]"
    comentario: str = ""
    error: str = ""

    movimiento_id: Optional[int] = Field(default=None, foreign_key="movimiento.id", index=True)
    conciliacion: str = ""
    # JSON: {"criterio": str, "diferencias": {campo: valor del estado de cuenta}, "candidatos": [ids]}
    conciliacion_detalle: str = "{}"

    @property
    def detalle_conciliacion(self) -> Dict:
        return json.loads(self.conciliacion_detalle or "{}")

    @property
    def confianza(self) -> Dict[str, float]:
        return json.loads(self.confianza_json or "{}")

    @property
    def fuente(self) -> Dict[str, str]:
        return json.loads(self.fuente_json or "{}")

    @property
    def textos_ocr(self) -> List[str]:
        return json.loads(self.textos_ocr_json or "[]")


class EstadoCuenta(SQLModel, table=True):
    __tablename__ = "estado_cuenta"

    id: Optional[int] = Field(default=None, primary_key=True)
    archivo: str
    nombre_original: str
    banco: str = "BBVA"
    producto: str = ""
    numero_cuenta: str = Field(index=True)
    clabe: str = ""
    periodo_inicio: str  # AAAA-MM-DD
    periodo_fin: str
    paginas: int = 0
    total_cargos: Optional[str] = None
    total_abonos: Optional[str] = None
    advertencias_json: str = "[]"
    cargado: datetime = Field(default_factory=datetime.now)

    @property
    def advertencias(self) -> List[str]:
        return json.loads(self.advertencias_json or "[]")


class Movimiento(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    estado_cuenta_id: int = Field(foreign_key="estado_cuenta.id", index=True)
    # cuenta|fecha|referencia|monto|n-ésima repetición: evita duplicar movimientos entre estados de cuenta.
    huella: str = Field(unique=True)
    pagina: int
    fecha_operacion: str = Field(index=True)
    fecha_liquidacion: str
    tipo: str
    descripcion: str = ""
    banco_texto: str = ""
    banco_clave: Optional[str] = None
    referencia: Optional[str] = Field(default=None, index=True)
    referencia_sufijo: Optional[str] = None
    referencia_numerica: Optional[str] = Field(default=None, index=True)
    concepto: str = ""
    cuenta_contraparte: Optional[str] = None
    clave_rastreo: Optional[str] = Field(default=None, index=True)
    nombre_contraparte: str = ""
    cargo: Optional[str] = None
    abono: Optional[str] = None
    texto_crudo: str = ""

    @property
    def monto(self) -> Optional[str]:
        return self.abono or self.cargo
