from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ocr.engine import tesseract_disponible
from app.ocr.lineas_grandes import leer_lineas_grandes

FUENTE = "/System/Library/Fonts/Supplemental/Arial.ttf"

pytestmark = pytest.mark.skipif(
    not tesseract_disponible() or not Path(FUENTE).exists(), reason="Requiere Tesseract y la fuente Arial"
)


def _comprobante_superindice() -> np.ndarray:
    """Imagita al estilo de apps móviles: monto enorme con "$" y centavos en superíndice."""
    chica, grande, sup = (ImageFont.truetype(FUENTE, s) for s in (30, 150, 75))
    img = Image.new("L", (1000, 900), 255)
    d = ImageDraw.Draw(img)
    d.text((60, 40), "Enviaste a una cuenta", font=chica, fill=20)
    d.text((60, 130), "$", font=sup, fill=20)
    d.text((110, 120), "200.", font=grande, fill=20)
    d.text((110 + d.textlength("200.", font=grande), 125), "00", font=sup, fill=20)
    for i, linea in enumerate(["19/Oct/2026 13:27:43", "Cuenta destino", "Bbva Bancomer ***602",
                               "Referencia", "8146602", "Clave de rastreo", "2610190113911497121"]):
        d.text((60, 340 + 70 * i), linea, font=chica, fill=20)
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)


def test_lee_monto_con_superindices():
    lineas = leer_lineas_grandes(_comprobante_superindice())
    assert [l.texto for l in lineas] == ["$200.00"]
