import os
import tempfile

# Base de datos y carpeta de imágenes aisladas para las pruebas (antes de importar la app).
os.environ.setdefault("OCR_DATA_DIR", tempfile.mkdtemp(prefix="ocr_test_"))
