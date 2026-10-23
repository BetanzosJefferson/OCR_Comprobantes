export type Campo = 'fecha' | 'clave_rastreo' | 'emisor_clave' | 'receptor_clave' | 'cuenta' | 'monto'

export const CAMPOS: { campo: Campo; titulo: string }[] = [
  { campo: 'fecha', titulo: 'Fecha' },
  { campo: 'clave_rastreo', titulo: 'Clave de rastreo' },
  { campo: 'emisor_clave', titulo: 'Emisor' },
  { campo: 'receptor_clave', titulo: 'Receptor' },
  { campo: 'cuenta', titulo: 'Cuenta beneficiaria' },
  { campo: 'monto', titulo: 'Monto' },
]

export const CONFIANZA_MINIMA = 0.6

export type Estado = 'procesando' | 'completo' | 'incompleto' | 'error_ocr' | 'revisado' | 'incidencia'

export const ETIQUETA_ESTADO: Record<Estado, string> = {
  procesando: 'Procesando',
  completo: 'Completo',
  incompleto: 'Requiere revisión',
  error_ocr: 'Error OCR',
  revisado: 'Revisado',
  incidencia: 'Incidencia',
}

export interface Banco {
  id: number
  nombre: string
  clave: string
  alias: string[]
}

export interface Cuenta {
  id: number
  numero: string
  tipo: string
  banco_receptor_id: number
  banco_receptor_clave: string | null
  banco_receptor_nombre: string | null
  titular: string
  activa: boolean
}

export interface Lote {
  id: number
  nombre: string
  creado: string
  total: number
  por_estado: Partial<Record<Estado, number>>
}

export interface Comprobante {
  id: number
  lote_id: number
  archivo: string
  nombre_original: string
  imagen_url: string
  estado: Estado
  fecha: string | null
  clave_rastreo: string | null
  emisor_clave: string | null
  receptor_clave: string | null
  cuenta: string | null
  monto: string | null
  folio: string | null
  referencia: string | null
  confianza: Partial<Record<Campo, number>>
  fuente: Partial<Record<Campo, 'ocr' | 'manual' | 'estado_cuenta'>>
  errores: Partial<Record<Campo, string>>
  texto_ocr: string
  comentario: string
  error: string
  exportable: boolean
  conciliacion: Conciliacion
  conciliacion_criterio: string
  conciliacion_diferencias: Partial<Record<Campo, string>>
  candidatos: number[]
  movimiento: Movimiento | null
}

export type Conciliacion =
  | ''
  | 'encontrado'
  | 'probable'
  | 'posible'
  | 'conflicto'
  | 'usado'
  | 'no_encontrado'
  | 'sin_estado'

export const ETIQUETA_CONCILIACION: Record<Conciliacion, string> = {
  '': 'Sin estados de cuenta',
  encontrado: 'Encontrado',
  probable: 'Probable',
  posible: 'Posible',
  conflicto: 'Conflicto',
  usado: 'Movimiento ya usado',
  no_encontrado: 'No encontrado',
  sin_estado: 'Sin estado del periodo',
}

export type TipoMovimiento = 'spei_recibido' | 'spei_enviado' | 'spei_devuelto' | 'pago_tercero' | 'otro'

export const ETIQUETA_TIPO: Record<TipoMovimiento, string> = {
  spei_recibido: 'SPEI recibido',
  spei_enviado: 'SPEI enviado',
  spei_devuelto: 'SPEI devuelto',
  pago_tercero: 'Pago a/de tercero BBVA',
  otro: 'Otro',
}

export interface Movimiento {
  id: number
  estado_cuenta_id: number
  pagina: number
  fecha_operacion: string
  fecha_liquidacion: string
  tipo: TipoMovimiento
  descripcion: string
  banco_texto: string
  banco_clave: string | null
  referencia: string | null
  referencia_sufijo: string | null
  referencia_numerica: string | null
  concepto: string
  cuenta_contraparte: string | null
  clave_rastreo: string | null
  nombre_contraparte: string
  cargo: string | null
  abono: string | null
  texto_crudo: string
  comprobante_id: number | null
  comprobante_nombre: string | null
}

export interface EstadoCuenta {
  id: number
  nombre_original: string
  banco: string
  producto: string
  numero_cuenta: string
  clabe: string
  periodo_inicio: string
  periodo_fin: string
  paginas: number
  total_cargos: string | null
  total_abonos: string | null
  advertencias: string[]
  cargado: string
  movimientos: number
  conciliados: number
}

export interface ResultadoCarga {
  archivo: string
  error: string | null
  estado: EstadoCuenta | null
  nuevos: number
  repetidos: number
}

export interface FiltroMovimientos {
  estado_cuenta?: number
  tipo?: string
  conciliado?: boolean
  q?: string
  ids?: number[]
  limite?: number
  desde?: number
}

export interface LoteDetalle {
  lote: Lote
  comprobantes: Comprobante[]
}

export interface ResultadoImportacion {
  creados: number
  actualizados: number
  errores: string[]
}

export type ComprobantePatch = Partial<Record<Campo | 'folio' | 'referencia' | 'comentario', string>> & {
  estado?: 'revisado' | 'incidencia' | 'auto'
}

async function pedir<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) {
    let mensaje = `${r.status} ${r.statusText}`
    try {
      const cuerpo = await r.json()
      if (typeof cuerpo.detail === 'string') mensaje = cuerpo.detail
      else if (Array.isArray(cuerpo.detail))
        mensaje = cuerpo.detail.map((d: { loc: string[]; msg: string }) => `${d.loc.at(-1)}: ${d.msg}`).join('; ')
    } catch {
      /* respuesta sin JSON */
    }
    throw new Error(mensaje)
  }
  return r.status === 204 ? (undefined as T) : r.json()
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

function archivosForm(archivos: File[], extra: Record<string, string> = {}): FormData {
  const fd = new FormData()
  archivos.forEach((a) => fd.append('archivos', a))
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v))
  return fd
}

export const api = {
  estado: () => pedir<{ tesseract: boolean; idioma: string }>('/api/estado'),

  bancos: () => pedir<Banco[]>('/api/bancos'),
  crearBanco: (b: Omit<Banco, 'id'>) => pedir<Banco>('/api/bancos', json('POST', b)),
  actualizarBanco: (id: number, b: Omit<Banco, 'id'>) => pedir<Banco>(`/api/bancos/${id}`, json('PUT', b)),
  eliminarBanco: (id: number) => pedir<void>(`/api/bancos/${id}`, { method: 'DELETE' }),
  importarBancos: (f: File) => {
    const fd = new FormData()
    fd.append('archivo', f)
    return pedir<ResultadoImportacion>('/api/bancos/import', { method: 'POST', body: fd })
  },

  cuentas: () => pedir<Cuenta[]>('/api/cuentas'),
  crearCuenta: (c: CuentaInput) => pedir<Cuenta>('/api/cuentas', json('POST', c)),
  actualizarCuenta: (id: number, c: CuentaInput) => pedir<Cuenta>(`/api/cuentas/${id}`, json('PUT', c)),
  eliminarCuenta: (id: number) => pedir<void>(`/api/cuentas/${id}`, { method: 'DELETE' }),
  importarCuentas: (f: File) => {
    const fd = new FormData()
    fd.append('archivo', f)
    return pedir<ResultadoImportacion>('/api/cuentas/import', { method: 'POST', body: fd })
  },

  lotes: () => pedir<Lote[]>('/api/lotes'),
  lote: (id: number) => pedir<LoteDetalle>(`/api/lotes/${id}`),
  crearLote: (archivos: File[], nombre: string) =>
    pedir<Lote>('/api/lotes', { method: 'POST', body: archivosForm(archivos, nombre ? { nombre } : {}) }),
  agregarALote: (id: number, archivos: File[]) =>
    pedir<Lote>(`/api/lotes/${id}/comprobantes`, { method: 'POST', body: archivosForm(archivos) }),
  eliminarLote: (id: number) => pedir<void>(`/api/lotes/${id}`, { method: 'DELETE' }),
  reextraerLote: (id: number) => pedir<{ reextraidos: number }>(`/api/lotes/${id}/reextraer`, { method: 'POST' }),

  editarComprobante: (id: number, cambios: ComprobantePatch) =>
    pedir<Comprobante>(`/api/comprobantes/${id}`, json('PATCH', cambios)),
  reprocesar: (id: number) => pedir<Comprobante>(`/api/comprobantes/${id}/reprocesar`, { method: 'POST' }),
  eliminarComprobante: (id: number) => pedir<void>(`/api/comprobantes/${id}`, { method: 'DELETE' }),
  candidatos: (id: number) => pedir<Movimiento[]>(`/api/comprobantes/${id}/candidatos`),
  aplicarMovimiento: (id: number, movimientoId?: number) =>
    pedir<Comprobante>(`/api/comprobantes/${id}/aplicar-movimiento`, json('POST', { movimiento_id: movimientoId ?? null })),
  desvincularMovimiento: (id: number) =>
    pedir<Comprobante>(`/api/comprobantes/${id}/desvincular-movimiento`, { method: 'POST' }),

  estadosCuenta: () => pedir<EstadoCuenta[]>('/api/estados-cuenta'),
  subirEstadosCuenta: (archivos: File[]) =>
    pedir<ResultadoCarga[]>('/api/estados-cuenta', { method: 'POST', body: archivosForm(archivos) }),
  eliminarEstadoCuenta: (id: number) => pedir<void>(`/api/estados-cuenta/${id}`, { method: 'DELETE' }),
  movimientos: (f: FiltroMovimientos) => {
    const p = new URLSearchParams()
    Object.entries(f).forEach(([k, v]) => {
      if (v === undefined || v === '' || (Array.isArray(v) && !v.length)) return
      p.set(k, Array.isArray(v) ? v.join(',') : String(v))
    })
    return pedir<{ total: number; items: Movimiento[] }>(`/api/movimientos?${p}`)
  },
  conciliar: () => pedir<Partial<Record<Conciliacion, number>>>('/api/conciliar', { method: 'POST' }),
}

export type CuentaInput = Omit<Cuenta, 'id' | 'banco_receptor_clave' | 'banco_receptor_nombre'>

export async function descargar(url: string): Promise<{ exportados: number; omitidos: number }> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`No se pudo descargar (${r.status})`)
  const disposicion = r.headers.get('Content-Disposition') ?? ''
  const nombre = /filename="([^"]+)"/.exec(disposicion)?.[1] ?? 'descarga'
  const blob = await r.blob()
  const enlace = document.createElement('a')
  enlace.href = URL.createObjectURL(blob)
  enlace.download = nombre
  enlace.click()
  URL.revokeObjectURL(enlace.href)
  return {
    exportados: Number(r.headers.get('X-Exportados') ?? 0),
    omitidos: Number(r.headers.get('X-Omitidos') ?? 0),
  }
}
