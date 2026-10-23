"""Genera PDFs mínimos con texto en posiciones fijas, imitando la maqueta del estado de cuenta BBVA.

Los datos son ficticios; las coordenadas x de las columnas son las medidas en un estado real.
"""
from typing import List, Optional, Sequence, Tuple

ALTO = 792
X_DESCRIPCION = 105
# Borde derecho de los importes en un estado real (cargos / abonos / saldo operación / liquidación).
X_CARGO, X_ABONO, X_SALDO_OP, X_SALDO_LIQ = 417, 458, 515, 590
TAM = 8
ANCHO_CARACTER = TAM * 0.5  # Courier: todos los caracteres miden 0.6 em; se deja holgura

Texto = Tuple[float, float, str]  # (x, y desde arriba, texto)


def _escapar(t: str) -> str:
    return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(paginas: Sequence[Sequence[Texto]]) -> bytes:
    objetos: List[bytes] = []
    n_paginas = len(paginas)
    # 1 catálogo, 2 páginas, 3 fuente, luego (página, contenido) por cada hoja.
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_paginas))
    objetos.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objetos.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_paginas} >>".encode())
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    for i, textos in enumerate(paginas):
        flujo = "".join(
            f"BT /F1 {TAM} Tf {x:.1f} {ALTO - y:.1f} Td ({_escapar(t)}) Tj ET\n" for x, y, t in textos
        ).encode("latin-1")
        objetos.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 {ALTO}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objetos.append(b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"endstream")

    salida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, obj in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        salida += f"{off:010d} 00000 n \n".encode()
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(salida)


class Hoja:
    """Ayuda a escribir renglones de movimientos de arriba hacia abajo."""

    def __init__(self, y: float = 60):
        self.textos: List[Texto] = []
        self.y = y

    def renglon(self, texto: str, x: float = X_DESCRIPCION, cargo: Optional[str] = None,
                abono: Optional[str] = None, saldo: Optional[str] = None) -> "Hoja":
        self.textos.append((x, self.y, texto))
        for importe, derecha in ((cargo, X_CARGO), (abono, X_ABONO), (saldo, X_SALDO_OP), (saldo, X_SALDO_LIQ)):
            if importe:
                self.textos.append((derecha - len(importe) * TAM * 0.6, self.y, importe))
        self.y += 11
        return self

    def encabezado_pagina(self, pagina: int, total: int, cuenta: str) -> "Hoja":
        for t in ("Estado de Cuenta", "Libreton Basico Cuenta Digital", f"PAGINA {pagina} / {total}",
                  f"No. de Cuenta {cuenta}", "No. de Cliente X0000001"):
            self.renglon(t, x=400)
        return self

    def pie(self) -> "Hoja":
        self.y = 740
        self.renglon("BBVA MEXICO, S.A., INSTITUCION DE BANCA MULTIPLE, GRUPO FINANCIERO BBVA MEXICO", x=30)
        return self

    def columnas(self) -> "Hoja":
        self.textos.append((500, self.y, "SALDO"))
        self.renglon("FECHA", x=21)
        y = self.y
        for x, t in ((21, "OPER"), (70, "LIQ"), (105, "DESCRIPCION"), (321, "REFERENCIA"), (381, "CARGOS"),
                     (427, "ABONOS"), (469, "OPERACION"), (536, "LIQUIDACION")):
            self.textos.append((x, y, t))
        self.y += 11
        return self

    def movimiento(self, fechas: str, descripcion: str, **importes) -> "Hoja":
        return self.renglon(f"{fechas} {descripcion}", x=21, **importes)
