import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("OCR_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "comprobantes.db"
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

TESSERACT_LANG = os.environ.get("OCR_TESSERACT_LANG", "spa")
TESSERACT_CMD = os.environ.get("TESSERACT_CMD")

# Por debajo de este valor un campo extraído se marca como "baja confianza" en la UI.
CONFIANZA_MINIMA = 0.6

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}

ESTADOS_DIR = DATA_DIR / "estados_cuenta"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ESTADOS_DIR.mkdir(parents=True, exist_ok=True)
