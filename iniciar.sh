#!/usr/bin/env bash
# Instala dependencias (la primera vez), compila el frontend y levanta la app en http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v tesseract >/dev/null; then
  echo "Falta Tesseract. Instálalo con: brew install tesseract tesseract-lang" >&2
  exit 1
fi

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi

if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi
(cd frontend && npm run build >/dev/null)

echo "Abriendo http://127.0.0.1:8000"
cd backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
