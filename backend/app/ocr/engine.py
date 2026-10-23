import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pytesseract

from ..config import TESSERACT_CMD, TESSERACT_LANG
from .lineas_grandes import LineaGrande, leer_lineas_grandes
from .preprocess import cargar_imagen, variantes

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

MODOS_PSM = (6, 4)


class TesseractNoDisponible(RuntimeError):
    pass


@dataclass
class ResultadoOCR:
    texto: str
    confianza_media: float
    variante: str
    psm: int
    # (top, bottom, texto) de cada línea, en coordenadas de la imagen preprocesada.
    lineas: List[Tuple[int, int, str]] = field(default_factory=list)


def tesseract_disponible() -> bool:
    return bool(TESSERACT_CMD or shutil.which("tesseract"))


def _ocr(img: np.ndarray, psm: int) -> ResultadoOCR:
    config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1"
    datos = pytesseract.image_to_data(
        img, lang=TESSERACT_LANG, config=config, output_type=pytesseract.Output.DICT
    )
    lineas: Dict[Tuple[int, int, int], List[int]] = {}
    confs = []
    for i, palabra in enumerate(datos["text"]):
        if not palabra.strip():
            continue
        clave = (datos["block_num"][i], datos["par_num"][i], datos["line_num"][i])
        lineas.setdefault(clave, []).append(i)
        conf = float(datos["conf"][i])
        if conf >= 0:
            confs.append(conf)
    filas = []
    for _, idx in sorted(lineas.items()):
        top = min(datos["top"][i] for i in idx)
        bottom = max(datos["top"][i] + datos["height"][i] for i in idx)
        filas.append((top, bottom, " ".join(datos["text"][i].strip() for i in idx)))
    texto = "\n".join(f[2] for f in filas)
    media = sum(confs) / len(confs) if confs else 0.0
    return ResultadoOCR(texto=texto, confianza_media=media, variante="", psm=psm, lineas=filas)


def _con_lineas_grandes(base: ResultadoOCR, grandes: List[LineaGrande]) -> ResultadoOCR:
    """Sustituye en el texto base las líneas que se solapan con una línea grande releída."""

    def solapa(top: int, bottom: int) -> bool:
        centro = (top + bottom) / 2
        return any(g.top <= centro <= g.bottom for g in grandes)

    filas = [f for f in base.lineas if not solapa(f[0], f[1])]
    filas += [(g.top, g.bottom, g.texto) for g in grandes]
    filas.sort(key=lambda f: f[0])
    return ResultadoOCR(
        texto="\n".join(f[2] for f in filas),
        confianza_media=base.confianza_media,
        variante=f"{base.variante}+lineas_grandes",
        psm=base.psm,
        lineas=filas,
    )


def leer_imagen(ruta: Path) -> List[ResultadoOCR]:
    """Ejecuta Tesseract sobre cada variante preprocesada y modo de segmentación.

    Devuelve los resultados ordenados de mayor a menor confianza media.
    """
    if not tesseract_disponible():
        raise TesseractNoDisponible(
            "Tesseract no está instalado. Instálalo con: brew install tesseract tesseract-lang"
        )
    img = cargar_imagen(ruta)
    imagenes = variantes(img)
    resultados: List[ResultadoOCR] = []
    for nombre, variante in imagenes.items():
        for psm in MODOS_PSM:
            r = _ocr(variante, psm)
            r.variante = nombre
            if r.texto.strip():
                resultados.append(r)
    resultados.sort(key=lambda r: r.confianza_media, reverse=True)

    # Todas las variantes comparten coordenadas, así que las líneas grandes se insertan en la mejor lectura.
    grandes = leer_lineas_grandes(imagenes["gris"])
    if grandes and resultados:
        resultados.append(_con_lineas_grandes(resultados[0], grandes))
    return resultados
