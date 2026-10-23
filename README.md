# OCR de Comprobantes

Webapp local para extraer de fotos de comprobantes de transferencia la fecha, clave de rastreo,
bancos emisor y receptor, cuenta beneficiaria y monto, revisarlos en una tabla editable y exportarlos
a un TXT con el formato:

```
2018-09-06,11FEF28A36F,40058,40102,5533302929,1200.50
```

(fecha AAAA-MM-DD, clave de rastreo, clave institución emisora, clave institución receptora,
cuenta beneficiaria, monto con 2 decimales).

## Requisitos

- macOS con Homebrew: `brew install tesseract tesseract-lang` (incluye el idioma español `spa`)
- Python 3.9+ y Node 20+

## Uso rápido

```bash
./iniciar.sh
```

Abre <http://127.0.0.1:8000>. La primera vez crea el entorno de Python, instala dependencias y compila el frontend.

### Desarrollo (recarga en caliente)

```bash
# terminal 1
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
# terminal 2
cd frontend && npm run dev   # http://localhost:5173 (redirige /api al backend)
```

Pruebas del backend: `cd backend && .venv/bin/python -m pytest`

## Flujo de trabajo

1. **Bancos**: registra cada institución con su clave y los alias con los que aparece en los
   comprobantes (p. ej. `BBVA, BANCOMER`). Puedes importar un CSV (`clave,nombre,alias` con alias
   separados por `|`); en `ejemplos/bancos_ejemplo.csv` hay una plantilla. **Verifica las claves
   contra el catálogo oficial de Banxico antes de usarlas.**
2. **Cuentas beneficiarias**: registra las cuentas (CLABE, tarjeta, celular) y su banco receptor.
   Solo se reconocen cuentas registradas; si el comprobante la muestra enmascarada (`****2929`) se
   compara por los últimos dígitos. Las cuentas inactivas se ignoran.
3. **Procesar**: arrastra varias fotos (JPG, PNG, HEIC…). Se procesan en segundo plano y la tabla se
   actualiza sola.
4. Revisa la tabla:
   - Rojo: falta el dato o es inválido (no está en catálogos, fecha futura, duplicado…).
   - Amarillo: dato leído con baja confianza; confírmalo.
   - Azul: dato capturado manualmente (no se sobrescribe al re-analizar).
   - Haz clic en la miniatura para ver la imagen con zoom, el texto OCR y capturar datos
     (flechas ← → para navegar).
   - **Revisado** confirma una fila; **Incidencia** la excluye del TXT con un comentario.
5. **Exportar TXT** incluye solo filas *Completas* o *Revisadas* sin errores.
   **Reporte de incidencias** genera un CSV con las filas no exportadas y el motivo.

Si cambias los catálogos después de procesar, usa **Re-analizar con catálogos** para volver a
aplicar las reglas sobre el texto ya leído (sin repetir el OCR).

## Conciliación con estados de cuenta BBVA

En **Estados de cuenta** sube los PDF originales de BBVA (no escaneados; puedes subir varios meses a
la vez). Cada movimiento se guarda con fecha, tipo, importe (cargo o abono), referencia, referencia
numérica, cuenta y banco de la contraparte, clave de rastreo y nombre. Al cargar se comparan los
totales de cargos y abonos con los que indica el propio estado de cuenta; si no cuadran verás un
aviso. Un mismo periodo no se carga dos veces.

Cada comprobante se busca automáticamente (al subir un estado de cuenta, al terminar el OCR y al
editarlo) con estos criterios, del más fuerte al más débil:

| Resultado | Criterio |
| --- | --- |
| Encontrado | Clave de rastreo idéntica (tolera O/0 e I/1/L), o con 1-2 caracteres distintos y mismo monto |
| Encontrado | Folio o referencia del comprobante = referencia del movimiento (sin ceros a la izquierda) |
| Encontrado | Referencia numérica + monto + fecha, si identifica un único movimiento |
| Probable | Monto + fecha (±1 día) + banco emisor, con un único candidato |
| Posible | Monto + fecha, con un único candidato |
| Conflicto | La clave o el folio coinciden pero el monto o la fecha no (posible comprobante alterado) |
| Movimiento ya usado | El movimiento ya está ligado a otro comprobante (reenviado o duplicado) |
| No encontrado | Ningún movimiento coincide (pendiente o falso: repórtalo como incidencia) |
| Sin estado del periodo | No hay estado de cuenta cargado que cubra la fecha del comprobante |

En el visor del comprobante verás el movimiento conciliado y lo que difiere; **Completar con estado
de cuenta** copia la clave de rastreo, fecha, monto y banco del movimiento. Si hay varios candidatos
puedes elegir el correcto con **Usar este**. El filtro **No encontrados en estado de cuenta** reúne
los no encontrados, conflictos y movimientos ya usados, que también salen en el reporte de
incidencias.

## Estructura

- `backend/app/ocr/preprocess.py`: escala de grises, inversión de modo oscuro, escalado,
  corrección de inclinación y umbral adaptativo.
- `backend/app/ocr/engine.py`: Tesseract (`spa`) sobre 2 variantes de imagen × 2 modos de segmentación.
- `backend/app/ocr/extractors.py`: reglas por campo con puntaje de confianza; se combinan las
  lecturas quedándose con el mejor valor de cada campo.
- `backend/app/services.py`: validaciones, estados, duplicados (clave + monto + fecha) y exportación.
- `backend/app/estados_cuenta/bbva.py`: lectura del PDF de BBVA con pdfplumber (columnas por
  posición, bloques de varios renglones, bloques partidos entre páginas).
- `backend/app/conciliacion.py`: criterios y asignación uno a uno de comprobantes y movimientos.
- `frontend/src`: React (Procesar, Bancos, Cuentas, Estados de cuenta).

Los datos (SQLite, imágenes y PDF de estados de cuenta) se guardan en `backend/data/`.

## Ajustar el reconocimiento

Cada banco usa un diseño distinto. Si un formato no se reconoce bien, abre el texto OCR en el visor
y agrega las etiquetas que usa ese banco a las expresiones de `extractors.py` (`ETIQUETAS_RASTREO`,
`R_ETQ_MONTO`, `R_ETQ_FECHA`, etc.), junto con una prueba en `backend/tests/test_extractors.py`
usando ese texto.
