import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from .config import FRONTEND_DIST, TESSERACT_LANG, UPLOAD_DIR
from .db import engine, init_db
from .models import Comprobante
from .ocr.engine import tesseract_disponible
from .routers import catalogos, estados_cuenta, lotes

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Comprobantes que quedaron "procesando" si el servidor se detuvo a mitad de un lote.
    with Session(engine) as session:
        for c in session.exec(select(Comprobante).where(Comprobante.estado == "procesando")).all():
            c.estado, c.error = "error_ocr", "El procesamiento se interrumpió; usa Reprocesar"
            session.add(c)
        session.commit()
    yield


app = FastAPI(title="OCR de Comprobantes", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Exportados", "X-Omitidos"],
)


@app.get("/api/estado")
def estado():
    return {"tesseract": tesseract_disponible(), "idioma": TESSERACT_LANG}


app.include_router(catalogos.router)
app.include_router(lotes.router)
app.include_router(estados_cuenta.router)
app.mount("/api/imagenes", StaticFiles(directory=UPLOAD_DIR), name="imagenes")

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{ruta:path}", include_in_schema=False)
    def spa(ruta: str):
        archivo = FRONTEND_DIST / ruta
        if ruta and archivo.is_file():
            return FileResponse(archivo)
        return FileResponse(FRONTEND_DIST / "index.html")
