import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  ETIQUETA_CONCILIACION,
  ETIQUETA_TIPO,
  type EstadoCuenta,
  type FiltroMovimientos,
  type Movimiento,
  type ResultadoCarga,
  type TipoMovimiento,
} from '../api'
import { moneda } from '../campos'

const POR_PAGINA = 100

const TIPOS: { valor: string; texto: string }[] = [
  { valor: '', texto: 'Todos' },
  { valor: 'abonos', texto: 'Solo abonos' },
  { valor: 'cargos', texto: 'Solo cargos' },
  ...(Object.keys(ETIQUETA_TIPO) as TipoMovimiento[]).map((t) => ({ valor: t, texto: ETIQUETA_TIPO[t] })),
]

function SubirPdf({ subir, subiendo }: { subir: (a: File[]) => void; subiendo: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [arrastrando, setArrastrando] = useState(false)
  const elegir = (lista: FileList | null) => {
    const pdfs = Array.from(lista ?? []).filter((f) => f.name.toLowerCase().endsWith('.pdf'))
    if (pdfs.length) subir(pdfs)
  }
  return (
    <div className="subida">
      <div
        className={`zona ${arrastrando ? 'arrastrando' : ''}`}
        onClick={() => !subiendo && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setArrastrando(true)
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastrando(false)
          if (!subiendo) elegir(e.dataTransfer.files)
        }}
      >
        <strong>{subiendo ? 'Leyendo estados de cuenta…' : 'Arrastra aquí tus estados de cuenta BBVA (PDF)'}</strong>
        <span>El PDF original descargado de BBVA, no escaneado. Puedes subir varios meses a la vez.</span>
        <input
          ref={input}
          type="file"
          multiple
          accept=".pdf,application/pdf"
          hidden
          onChange={(e) => {
            elegir(e.target.files)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}

export default function EstadosCuenta() {
  const [estados, setEstados] = useState<EstadoCuenta[] | null>(null)
  const [resultados, setResultados] = useState<ResultadoCarga[]>([])
  const [subiendo, setSubiendo] = useState(false)
  const [mensaje, setMensaje] = useState<{ texto: string; error: boolean } | null>(null)

  const [filtro, setFiltro] = useState<FiltroMovimientos>({ desde: 0, limite: POR_PAGINA })
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState<{ total: number; items: Movimiento[] } | null>(null)
  const [abierto, setAbierto] = useState<number | null>(null)

  const cargarEstados = useCallback(() => api.estadosCuenta().then(setEstados), [])
  const cargarMovimientos = useCallback(
    () =>
      api
        .movimientos(filtro)
        .then(setPagina)
        .catch((e) => setMensaje({ texto: e.message, error: true })),
    [filtro],
  )

  useEffect(() => {
    cargarEstados()
  }, [cargarEstados])

  useEffect(() => {
    cargarMovimientos()
  }, [cargarMovimientos])

  useEffect(() => {
    const t = setTimeout(() => setFiltro((f) => (f.q === busqueda ? f : { ...f, q: busqueda, desde: 0 })), 300)
    return () => clearTimeout(t)
  }, [busqueda])

  const cambiar = (cambios: Partial<FiltroMovimientos>) => setFiltro((f) => ({ ...f, ...cambios, desde: 0 }))

  async function subir(archivos: File[]) {
    setSubiendo(true)
    setMensaje(null)
    try {
      setResultados(await api.subirEstadosCuenta(archivos))
      cargarEstados()
      cargarMovimientos()
    } catch (e) {
      setMensaje({ texto: (e as Error).message, error: true })
    } finally {
      setSubiendo(false)
    }
  }

  async function eliminar(e: EstadoCuenta) {
    if (!confirm(`¿Eliminar el estado de cuenta ${e.periodo_inicio} al ${e.periodo_fin} y sus ${e.movimientos} movimientos?`))
      return
    await api.eliminarEstadoCuenta(e.id)
    if (filtro.estado_cuenta === e.id) cambiar({ estado_cuenta: undefined })
    cargarEstados()
    cargarMovimientos()
  }

  async function conciliar() {
    const r = await api.conciliar()
    const resumen = Object.entries(r)
      .map(([k, v]) => `${ETIQUETA_CONCILIACION[k as keyof typeof ETIQUETA_CONCILIACION] ?? k}: ${v}`)
      .join(' · ')
    setMensaje({ texto: `Conciliación recalculada. ${resumen || 'No hay comprobantes.'}`, error: false })
    cargarEstados()
    cargarMovimientos()
  }

  const desde = filtro.desde ?? 0

  return (
    <section>
      <h2>Estados de cuenta</h2>
      <SubirPdf subir={subir} subiendo={subiendo} />

      {mensaje && (
        <div className={`aviso ${mensaje.error ? 'error' : 'ok'}`} onClick={() => setMensaje(null)}>
          {mensaje.texto}
        </div>
      )}

      {resultados.map((r, i) => (
        <div key={i} className={`aviso ${r.error ? 'error' : r.estado?.advertencias.length ? 'error' : 'ok'}`}>
          <strong>{r.archivo}:</strong>{' '}
          {r.error ??
            `${r.nuevos} movimiento(s) nuevos${r.repetidos ? `, ${r.repetidos} ya existían` : ''} · ${r.estado?.conciliados ?? 0} conciliado(s) con comprobantes`}
          {r.estado?.advertencias.map((a) => (
            <div key={a}>⚠ {a}</div>
          ))}
        </div>
      ))}

      <div className="barra-lote">
        <strong>Estados cargados</strong>
        <div className="acciones">
          <button className="secundario" onClick={conciliar}>
            Recalcular conciliación
          </button>
        </div>
      </div>
      <div className="tabla-contenedor bajo">
        <table className="tabla">
          <thead>
            <tr>
              <th>Cuenta</th>
              <th>Periodo</th>
              <th>Archivo</th>
              <th>Movimientos</th>
              <th>Conciliados</th>
              <th>Cargos / Abonos</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {estados?.map((e) => (
              <tr key={e.id} className={filtro.estado_cuenta === e.id ? 'seleccionada' : ''}>
                <td>
                  <div className="mono">{e.numero_cuenta}</div>
                  <div className="tenue">
                    {e.banco} · {e.producto}
                  </div>
                </td>
                <td>
                  {e.periodo_inicio} al {e.periodo_fin}
                </td>
                <td>
                  <div>{e.nombre_original}</div>
                  <div className="tenue">
                    {e.paginas} páginas · cargado {e.cargado.replace('T', ' ')}
                  </div>
                  {e.advertencias.map((a) => (
                    <div key={a} className="texto-error">
                      ⚠ {a}
                    </div>
                  ))}
                </td>
                <td>{e.movimientos}</td>
                <td>{e.conciliados}</td>
                <td>
                  <div>−{moneda(e.total_cargos)}</div>
                  <div>+{moneda(e.total_abonos)}</div>
                </td>
                <td className="acciones-fila">
                  <button
                    className="secundario"
                    onClick={() => cambiar({ estado_cuenta: filtro.estado_cuenta === e.id ? undefined : e.id })}
                  >
                    {filtro.estado_cuenta === e.id ? 'Ver todos' : 'Ver movimientos'}
                  </button>
                  <button className="peligro" onClick={() => eliminar(e)}>
                    Eliminar
                  </button>
                </td>
              </tr>
            ))}
            {estados?.length === 0 && (
              <tr>
                <td colSpan={7} className="vacio">
                  Aún no has cargado estados de cuenta.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h2>Movimientos</h2>
      <div className="filtros">
        <input
          className="busqueda"
          placeholder="Buscar referencia, clave de rastreo, nombre o monto…"
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
        />
        <select value={filtro.tipo ?? ''} onChange={(e) => cambiar({ tipo: e.target.value || undefined })}>
          {TIPOS.map((t) => (
            <option key={t.valor} value={t.valor}>
              {t.texto}
            </option>
          ))}
        </select>
        <select
          value={filtro.conciliado === undefined ? '' : String(filtro.conciliado)}
          onChange={(e) => cambiar({ conciliado: e.target.value === '' ? undefined : e.target.value === 'true' })}
        >
          <option value="">Conciliados y sin conciliar</option>
          <option value="false">Sin comprobante</option>
          <option value="true">Con comprobante</option>
        </select>
        <span className="tenue">{pagina ? `${pagina.total} movimiento(s)` : 'Cargando…'}</span>
      </div>

      <div className="tabla-contenedor">
        <table className="tabla movimientos">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Descripción</th>
              <th>Referencia</th>
              <th>Clave de rastreo</th>
              <th>Contraparte</th>
              <th className="num">Cargo</th>
              <th className="num">Abono</th>
              <th>Comprobante</th>
            </tr>
          </thead>
          <tbody>
            {pagina?.items.map((m) => (
              <tr key={m.id} onClick={() => setAbierto(abierto === m.id ? null : m.id)} className="clicable">
                <td>
                  {m.fecha_operacion}
                  {m.fecha_liquidacion !== m.fecha_operacion && <div className="tenue">liq. {m.fecha_liquidacion}</div>}
                </td>
                <td>
                  {m.descripcion}
                  <div className="tenue">{m.concepto}</div>
                  {abierto === m.id && <pre className="crudo">{m.texto_crudo}</pre>}
                </td>
                <td className="mono">
                  {m.referencia}
                  {m.referencia_numerica && <div className="tenue">núm. {m.referencia_numerica}</div>}
                </td>
                <td className="mono">{m.clave_rastreo}</td>
                <td>
                  {m.nombre_contraparte}
                  <div className="tenue mono">
                    {[m.banco_clave ?? m.banco_texto, m.cuenta_contraparte].filter(Boolean).join(' · ')}
                  </div>
                </td>
                <td className="num">{moneda(m.cargo)}</td>
                <td className="num">{moneda(m.abono)}</td>
                <td>
                  {m.comprobante_id ? (
                    <span className="conciliacion conciliacion-encontrado" title={m.comprobante_nombre ?? ''}>
                      #{m.comprobante_id}
                    </span>
                  ) : (
                    <span className="tenue">—</span>
                  )}
                </td>
              </tr>
            ))}
            {pagina?.items.length === 0 && (
              <tr>
                <td colSpan={8} className="vacio">
                  No hay movimientos con estos filtros.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pagina && pagina.total > POR_PAGINA && (
        <div className="paginacion">
          <button className="secundario" disabled={desde === 0} onClick={() => setFiltro((f) => ({ ...f, desde: desde - POR_PAGINA }))}>
            ← Anteriores
          </button>
          <span>
            {desde + 1}–{Math.min(desde + POR_PAGINA, pagina.total)} de {pagina.total}
          </span>
          <button
            className="secundario"
            disabled={desde + POR_PAGINA >= pagina.total}
            onClick={() => setFiltro((f) => ({ ...f, desde: desde + POR_PAGINA }))}
          >
            Siguientes →
          </button>
        </div>
      )}
      <p className="ayuda">
        Los comprobantes se concilian automáticamente al subir un estado de cuenta, al terminar el OCR y al editar un
        comprobante. Revisa el resultado en <Link to="/">Procesar</Link>, columna "Estado de cuenta".
      </p>
    </section>
  )
}
