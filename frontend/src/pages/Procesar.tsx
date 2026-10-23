import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  api,
  descargar,
  ETIQUETA_ESTADO,
  type Banco,
  type Campo,
  type Comprobante,
  type ComprobantePatch,
  type Cuenta,
  type Estado,
  type Lote,
  type LoteDetalle,
} from '../api'
import SubirImagenes from '../components/SubirImagenes'
import TablaComprobantes from '../components/TablaComprobantes'
import Visor from '../components/Visor'

type Filtro = 'todos' | 'pendientes' | 'listos' | 'incidencias' | 'no_encontrados'

const NO_ENCONTRADOS = new Set(['no_encontrado', 'conflicto', 'usado'])

const FILTROS: { id: Filtro; texto: string; incluye: (c: Comprobante) => boolean }[] = [
  { id: 'todos', texto: 'Todos', incluye: () => true },
  {
    id: 'pendientes',
    texto: 'Por revisar',
    incluye: (c) => !c.exportable && c.estado !== 'incidencia',
  },
  { id: 'listos', texto: 'Listos para exportar', incluye: (c) => c.exportable },
  { id: 'incidencias', texto: 'Incidencias', incluye: (c) => c.estado === 'incidencia' },
  {
    id: 'no_encontrados',
    texto: 'No encontrados en estado de cuenta',
    incluye: (c) => NO_ENCONTRADOS.has(c.conciliacion),
  },
]

export default function Procesar() {
  const [params, setParams] = useSearchParams()
  const loteId = params.get('lote') ? Number(params.get('lote')) : null

  const [lotes, setLotes] = useState<Lote[]>([])
  const [detalleCargado, setDetalle] = useState<LoteDetalle | null>(null)
  const detalle = detalleCargado && detalleCargado.lote.id === loteId ? detalleCargado : null
  const [bancos, setBancos] = useState<Banco[] | null>(null)
  const [cuentas, setCuentas] = useState<Cuenta[] | null>(null)
  const [filtro, setFiltro] = useState<Filtro>('todos')
  const [abiertoId, setAbiertoId] = useState<number | null>(null)
  const [mensaje, setMensaje] = useState<{ texto: string; error: boolean } | null>(null)
  const [subiendo, setSubiendo] = useState(false)

  const avisar = (texto: string, error = false) => setMensaje({ texto, error })
  const elegirLote = useCallback((id: number | null) => setParams(id ? { lote: String(id) } : {}), [setParams])

  const cargarLotes = useCallback(() => api.lotes().then(setLotes), [])
  const cargarDetalle = useCallback(() => {
    if (loteId) api.lote(loteId).then(setDetalle).catch((e) => avisar(e.message, true))
  }, [loteId])

  useEffect(() => {
    cargarLotes()
    api.bancos().then(setBancos)
    api.cuentas().then(setCuentas)
  }, [cargarLotes])

  useEffect(() => {
    cargarDetalle()
  }, [cargarDetalle])

  useEffect(() => {
    if (!loteId && lotes.length) elegirLote(lotes[0].id)
  }, [loteId, lotes, elegirLote])

  const procesando = detalle?.comprobantes.some((c) => c.estado === 'procesando') ?? false
  useEffect(() => {
    if (!procesando) return
    const t = setInterval(() => {
      cargarDetalle()
    }, 1500)
    return () => clearInterval(t)
  }, [procesando, cargarDetalle])

  useEffect(() => {
    if (!procesando) cargarLotes()
  }, [procesando, cargarLotes])

  const comprobantes = useMemo(() => detalle?.comprobantes ?? [], [detalle])
  const visibles = useMemo(
    () => comprobantes.filter(FILTROS.find((f) => f.id === filtro)!.incluye),
    [comprobantes, filtro],
  )
  const conteos = useMemo(() => {
    const r = {} as Record<Filtro, number>
    FILTROS.forEach((f) => (r[f.id] = comprobantes.filter(f.incluye).length))
    return r
  }, [comprobantes])

  const reemplazar = (nuevo: Comprobante) =>
    setDetalle((d) => d && { ...d, comprobantes: d.comprobantes.map((c) => (c.id === nuevo.id ? nuevo : c)) })

  async function editar(c: Comprobante, cambios: ComprobantePatch) {
    try {
      const nuevo = await api.editarComprobante(c.id, cambios)
      reemplazar(nuevo)
      // Un cambio puede resolver o crear duplicados y cambiar la conciliación de otras filas.
      if (Object.keys(cambios).some((k) => k !== 'comentario')) cargarDetalle()
    } catch (e) {
      avisar((e as Error).message, true)
    }
  }

  async function aplicarMovimiento(c: Comprobante, movimientoId?: number) {
    try {
      reemplazar(await api.aplicarMovimiento(c.id, movimientoId))
      cargarDetalle()
      avisar('Datos completados con el estado de cuenta. Revisa y marca como revisado.')
    } catch (e) {
      avisar((e as Error).message, true)
    }
  }

  async function desvincularMovimiento(c: Comprobante) {
    try {
      reemplazar(await api.desvincularMovimiento(c.id))
      cargarDetalle()
      avisar('Se quitaron los datos del estado de cuenta y se restauró la lectura OCR.')
    } catch (e) {
      avisar((e as Error).message, true)
    }
  }

  const guardarCampo = (c: Comprobante, campo: Campo, valor: string) => editar(c, { [campo]: valor })

  function reportarIncidencia(c: Comprobante, comentario?: string) {
    const texto = comentario?.trim() || prompt('Describe la incidencia (se incluirá en el reporte):', c.comentario)
    if (texto === null || texto === undefined) return
    editar(c, { estado: 'incidencia', comentario: texto })
  }

  async function reprocesar(c: Comprobante) {
    try {
      reemplazar(await api.reprocesar(c.id))
    } catch (e) {
      avisar((e as Error).message, true)
    }
  }

  async function eliminar(c: Comprobante) {
    if (!confirm(`¿Eliminar ${c.nombre_original}?`)) return
    await api.eliminarComprobante(c.id)
    if (abiertoId === c.id) setAbiertoId(null)
    cargarDetalle()
  }

  async function subir(archivos: File[], nombre: string, nuevoLote: boolean) {
    setSubiendo(true)
    try {
      if (nuevoLote || !loteId) {
        const lote = await api.crearLote(archivos, nombre)
        await cargarLotes()
        elegirLote(lote.id)
      } else {
        await api.agregarALote(loteId, archivos)
        cargarDetalle()
      }
      avisar(`${archivos.length} imagen(es) en proceso`)
    } catch (e) {
      avisar((e as Error).message, true)
    } finally {
      setSubiendo(false)
    }
  }

  function confirmarExportacion(): boolean {
    const pendientes = comprobantes.filter((c) => !c.exportable).length
    if (comprobantes.length - pendientes === 0) {
      avisar('No hay comprobantes completos o revisados para exportar.', true)
      return false
    }
    if (
      pendientes > 0 &&
      !confirm(
        `${pendientes} comprobante(s) no están listos (incompletos, con error o incidencia) y no se incluirán. ¿Exportar de todos modos?`,
      )
    )
      return false
    return true
  }

  async function exportar(formato: 'txt' | 'json') {
    if (!loteId || !confirmarExportacion()) return
    try {
      const r = await descargar(`/api/lotes/${loteId}/export.${formato}`)
      avisar(`${formato.toUpperCase()} generado con ${r.exportados} comprobante(s). Omitidos: ${r.omitidos}.`)
    } catch (e) {
      avisar((e as Error).message, true)
    }
  }

  async function exportarIncidencias() {
    if (!loteId) return
    try {
      await descargar(`/api/lotes/${loteId}/incidencias.csv`)
    } catch (e) {
      avisar((e as Error).message, true)
    }
  }

  async function reextraer() {
    if (!loteId) return
    const r = await api.reextraerLote(loteId)
    avisar(`Se volvieron a analizar ${r.reextraidos} comprobante(s) con los catálogos actuales (los datos manuales se conservan).`)
    cargarDetalle()
  }

  async function eliminarLote() {
    if (!loteId || !detalle) return
    if (!confirm(`¿Eliminar el lote "${detalle.lote.nombre}" y sus ${detalle.lote.total} imágenes?`)) return
    await api.eliminarLote(loteId)
    elegirLote(null)
    setDetalle(null)
    cargarLotes()
  }

  const indiceAbierto = visibles.findIndex((c) => c.id === abiertoId)
  const abierto = comprobantes.find((c) => c.id === abiertoId) ?? null

  return (
    <section>
      <SubirImagenes subiendo={subiendo} hayLote={!!loteId} subir={subir} />

      {mensaje && (
        <div className={`aviso ${mensaje.error ? 'error' : 'ok'}`} onClick={() => setMensaje(null)}>
          {mensaje.texto}
        </div>
      )}

      {(bancos?.length === 0 || cuentas?.length === 0) && (
        <div className="aviso error">
          Configura los bancos y las cuentas beneficiarias para que se reconozcan las instituciones y cuentas.
        </div>
      )}

      <div className="barra-lote">
        <label>
          Lote
          <select value={loteId ?? ''} onChange={(e) => elegirLote(e.target.value ? Number(e.target.value) : null)}>
            {lotes.length === 0 && <option value="">Sin lotes</option>}
            {lotes.map((l) => (
              <option key={l.id} value={l.id}>
                #{l.id} · {l.nombre} · {l.total} imagen(es)
              </option>
            ))}
          </select>
        </label>
        {detalle && (
          <div className="resumen">
            {(Object.keys(detalle.lote.por_estado) as Estado[]).map((e) => (
              <span key={e} className={`estado estado-${e}`}>
                {ETIQUETA_ESTADO[e]}: {detalle.lote.por_estado[e]}
              </span>
            ))}
          </div>
        )}
        <div className="acciones">
          <button onClick={() => exportar('txt')} disabled={!detalle || procesando}>
            Exportar TXT
          </button>
          <button className="secundario" onClick={() => exportar('json')} disabled={!detalle || procesando}>
            Exportar en JSON
          </button>
          <button className="secundario" onClick={exportarIncidencias} disabled={!detalle}>
            Reporte de incidencias
          </button>
          <button className="secundario" onClick={reextraer} disabled={!detalle || procesando}>
            Re-analizar con catálogos
          </button>
          <button className="peligro" onClick={eliminarLote} disabled={!detalle}>
            Eliminar lote
          </button>
        </div>
      </div>

      {detalle && (
        <>
          <div className="filtros">
            {FILTROS.map((f) => (
              <button
                key={f.id}
                className={filtro === f.id ? 'activo' : 'secundario'}
                onClick={() => setFiltro(f.id)}
              >
                {f.texto} ({conteos[f.id]})
              </button>
            ))}
            <span className="leyenda">
              <span className="campo-error">Falta / inválido</span>
              <span className="campo-dudoso">Baja confianza</span>
              <span className="campo-manual">Capturado a mano</span>
              <span className="campo-estado-cuenta">Del estado de cuenta</span>
            </span>
          </div>

          <TablaComprobantes
            comprobantes={visibles}
            bancos={bancos ?? []}
            cuentas={cuentas ?? []}
            guardarCampo={guardarCampo}
            marcarRevisado={(c) => editar(c, { estado: 'revisado' })}
            reportarIncidencia={(c) => reportarIncidencia(c)}
            quitarIncidencia={(c) => editar(c, { estado: 'auto' })}
            abrir={(c) => setAbiertoId(c.id)}
            reprocesar={reprocesar}
            eliminar={eliminar}
          />
        </>
      )}

      {abierto && (
        <Visor
          comprobante={abierto}
          bancos={bancos ?? []}
          cuentas={cuentas ?? []}
          posicion={indiceAbierto >= 0 ? `${indiceAbierto + 1} de ${visibles.length}` : ''}
          cerrar={() => setAbiertoId(null)}
          anterior={indiceAbierto > 0 ? () => setAbiertoId(visibles[indiceAbierto - 1].id) : null}
          siguiente={
            indiceAbierto >= 0 && indiceAbierto < visibles.length - 1
              ? () => setAbiertoId(visibles[indiceAbierto + 1].id)
              : null
          }
          guardarCampo={(campo, valor) => guardarCampo(abierto, campo, valor)}
          marcarRevisado={() => editar(abierto, { estado: 'revisado' })}
          marcarIncidencia={(comentario) => reportarIncidencia(abierto, comentario)}
          quitarIncidencia={() => editar(abierto, { estado: 'auto' })}
          guardarComentario={(comentario) => editar(abierto, { comentario })}
          guardarAuxiliar={(campo, valor) => editar(abierto, { [campo]: valor })}
          aplicarMovimiento={(movimientoId) => aplicarMovimiento(abierto, movimientoId)}
          desvincularMovimiento={() => desvincularMovimiento(abierto)}
          reprocesar={() => reprocesar(abierto)}
        />
      )}
    </section>
  )
}
