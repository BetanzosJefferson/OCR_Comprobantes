from pathlib import Path
from typing import Dict

import cv2
import numpy as np
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

ANCHO_OBJETIVO = 1800


def cargar_imagen(ruta: Path) -> np.ndarray:
    """Carga cualquier formato soportado por Pillow (incluido HEIC) respetando la orientación EXIF."""
    with Image.open(ruta) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def a_gris(img: np.ndarray) -> np.ndarray:
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    # Capturas en modo oscuro: Tesseract funciona mejor con texto oscuro sobre fondo claro.
    if float(np.mean(gris)) < 110:
        gris = cv2.bitwise_not(gris)
    return gris


def redimensionar(gris: np.ndarray) -> np.ndarray:
    alto, ancho = gris.shape[:2]
    if ancho >= ANCHO_OBJETIVO:
        return gris
    escala = min(ANCHO_OBJETIVO / ancho, 3.0)
    return cv2.resize(gris, (int(ancho * escala), int(alto * escala)), interpolation=cv2.INTER_CUBIC)


def corregir_inclinacion(gris: np.ndarray) -> np.ndarray:
    binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(binaria > 0))
    if len(coords) < 100:
        return gris
    angulo = cv2.minAreaRect(coords.astype(np.float32))[-1]
    if angulo > 45:
        angulo -= 90
    elif angulo < -45:
        angulo += 90
    # Ángulos grandes suelen ser falsos positivos (fondos, logos); solo corregimos inclinaciones leves.
    if abs(angulo) < 0.3 or abs(angulo) > 15:
        return gris
    alto, ancho = gris.shape[:2]
    m = cv2.getRotationMatrix2D((ancho / 2, alto / 2), angulo, 1.0)
    return cv2.warpAffine(gris, m, (ancho, alto), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def variantes(img: np.ndarray) -> Dict[str, np.ndarray]:
    """Genera versiones preprocesadas de la imagen; cada una se pasa por Tesseract."""
    gris = corregir_inclinacion(redimensionar(a_gris(img)))
    suavizada = cv2.bilateralFilter(gris, 7, 50, 50)
    umbral = cv2.adaptiveThreshold(
        suavizada, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    return {"gris": gris, "umbral": umbral}
