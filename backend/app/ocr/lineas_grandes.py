"""Relectura de líneas con texto muy grande (típicamente el monto).

Tesseract funciona mejor con letras de ~30-60 px de alto. Los comprobantes de apps móviles muestran
el monto enorme y con el "$" y los centavos en superíndice ("$200⁰⁰"); al leer la página completa
esa línea se pierde o sale como "5200.%". Aquí se localizan esas líneas por tamaño de los
componentes conectados, se separan los superíndices y cada parte se lee por separado.
"""
import re
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np
import pytesseract

from ..config import TESSERACT_LANG

ALTO_LECTURA = 60
MAX_LINEAS = 6
DIGITOS = "0123456789"


@dataclass
class LineaGrande:
    top: int
    bottom: int
    texto: str


def _leer(img: np.ndarray, lista_blanca: Optional[str] = None) -> str:
    alto = img.shape[0]
    if alto < 4 or img.shape[1] < 4:
        return ""
    escala = ALTO_LECTURA / alto
    interp = cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC
    img = cv2.resize(img, None, fx=escala, fy=escala, interpolation=interp)
    img = cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    config = "--oem 1 --psm 7"
    if lista_blanca:
        config += f" -c tessedit_char_whitelist={lista_blanca}"
    return pytesseract.image_to_string(img, lang=TESSERACT_LANG, config=config).strip()


def _recorte(gris: np.ndarray, x0: int, y0: int, x1: int, y1: int, margen: int) -> np.ndarray:
    alto, ancho = gris.shape[:2]
    return gris[max(0, y0 - margen):min(alto, y1 + margen), max(0, x0 - margen):min(ancho, x1 + margen)]


def _leer_con_superindices(gris: np.ndarray, binaria: np.ndarray, x: int, y: int, w: int, h: int) -> str:
    n, _, stats, _ = cv2.connectedComponentsWithStats(binaria[y:y + h, x:x + w], 8)
    comps = [tuple(int(v) for v in stats[i][:4]) for i in range(1, n) if stats[i][4] > 15]
    if not comps:
        return ""
    alto_max = max(c[3] for c in comps)
    principales = [c for c in comps if c[3] >= 0.75 * alto_max]
    tope = min(c[1] for c in principales)
    inicio = min(c[0] for c in principales)
    fin = max(c[0] + c[2] for c in principales)

    # Superíndice: más bajo que los dígitos y sin llegar a la línea base.
    superindices = [c for c in comps if c[3] < 0.75 * alto_max and c[1] + c[3] < tope + 0.75 * alto_max]
    izquierda = [c for c in superindices if c[0] + c[2] <= inicio]
    derecha = [c for c in superindices if c[0] >= fin]

    general = _leer(_recorte(gris, x, y, x + w, y + h, h // 6))
    if not derecha:
        return general

    # Dígitos principales incluyendo el punto decimal (componente pequeño en la línea base).
    fin_principal = max([fin] + [c[0] + c[2] for c in comps if c not in superindices and c[0] < min(d[0] for d in derecha)])
    margen = max(4, alto_max // 10)
    principal = _leer(_recorte(gris, x + inicio, y, x + fin_principal, y + h, margen), DIGITOS + ".,")
    dx0 = min(c[0] for c in derecha)
    dx1 = max(c[0] + c[2] for c in derecha)
    dy0 = min(c[1] for c in derecha)
    dy1 = max(c[1] + c[3] for c in derecha)
    centavos = _leer(_recorte(gris, x + dx0, y + dy0, x + dx1, y + dy1, margen), DIGITOS)

    if not re.fullmatch(r"\d[\d,]*[.,]?", principal) or not re.fullmatch(r"\d{2}", centavos):
        return general
    moneda = "$" if izquierda else ""
    return f"{moneda}{principal.rstrip('.,')}.{centavos}"


def leer_lineas_grandes(gris: np.ndarray) -> List[LineaGrande]:
    binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    n, etiquetas, stats, _ = cv2.connectedComponentsWithStats(binaria, 8)
    if n < 10:
        return []
    alturas = stats[1:, cv2.CC_STAT_HEIGHT]
    anchos = stats[1:, cv2.CC_STAT_WIDTH]
    texto = alturas[(alturas > 8) & (alturas < gris.shape[0] // 10) & (anchos < gris.shape[1] // 4)]
    if len(texto) < 10:
        return []
    mediana = float(np.median(texto))

    grandes = [
        i + 1
        for i in range(n - 1)
        if 2.2 * mediana <= alturas[i] < gris.shape[0] // 8 and anchos[i] < 3 * alturas[i]
    ]
    if not grandes:
        return []
    mascara = np.isin(etiquetas, grandes).astype(np.uint8) * 255
    alto_tipico = int(np.median(alturas[np.array(grandes) - 1]))
    nucleo = cv2.getStructuringElement(cv2.MORPH_RECT, (alto_tipico, max(3, alto_tipico // 4)))
    contornos, _ = cv2.findContours(cv2.dilate(mascara, nucleo), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    cajas = sorted((cv2.boundingRect(c) for c in contornos), key=lambda b: b[2] * b[3], reverse=True)
    lineas: List[LineaGrande] = []
    for x, y, w, h in cajas[:MAX_LINEAS]:
        # Ampliar horizontalmente para incluir superíndices ("$" y centavos) junto a los dígitos.
        x0, x1 = max(0, x - h // 2), min(gris.shape[1], x + w + h // 2)
        y0, y1 = max(0, y - h // 6), min(gris.shape[0], y + h + h // 6)
        texto_linea = _leer_con_superindices(gris, binaria, x0, y0, x1 - x0, y1 - y0)
        # Solo interesan líneas con cifras (montos); los iconos y logotipos producen texto basura.
        if re.search(r"\d{2,}", texto_linea):
            lineas.append(LineaGrande(y, y + h, texto_linea))
    return lineas
