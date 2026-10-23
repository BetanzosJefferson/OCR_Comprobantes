import { useEffect, useState } from 'react'
import { api, CAMPOS, ETIQUETA_TIPO, type Comprobante, type Movimiento } from '../api'
import { moneda } from '../campos'
import InsigniaConciliacion from './InsigniaConciliacion'

interface Props {
  comprobante: Comprobante
  aplicar: (movimientoId?: number) => void
  desvincular: () => void
}

const BUSCAR_CANDIDATOS = new Set(['no_encontrado', 'posible', 'probable', 'conflicto'])

function DatosMovimiento({ m, diferencias }: { m: Movimiento; diferencias: Set<string> }) {
  const fila = (titulo: string, valor: string | null | undefined, campo?: string) =>
    valor ? (
      <tr className={campo && diferencias.has(campo) ? 'diferencia' : ''}>
        <th>{titulo}</th>
        <td className="mono">{valor}</td>
      </tr>
    ) : null
  return (
    <table className="movimiento">
      <tbody>
        {fila('Fecha', `${m.fecha_operacion}${m.fecha_liquidacion !== m.fecha_operacion ? ` (liq. ${m.fecha_liquidacion})` : ''}`, 'fecha')}
        {fila('Movimiento', `${m.descripcion} · ${ETIQUETA_TIPO[m.tipo]}`)}
        {fila(m.abono ? 'Abono' : 'Cargo', moneda(m.abono ?? m.cargo), 'monto')}
        {fila('Clave de rastreo', m.clave_rastreo, 'clave_rastreo')}
        {fila('Referencia', [m.referencia, m.referencia_sufijo].filter(Boolean).join(' · '))}
        {fila('Ref. numérica', m.referencia_numerica)}
        {fila('Concepto', m.concepto)}
        {fila('Contraparte', [m.nombre_contraparte, m.cuenta_contraparte].filter(Boolean).join(' · '))}
        {fila('Banco', [m.banco_clave, m.banco_texto].filter(Boolean).join(' · '), 'emisor_clave')}
        {fila('Página', String(m.pagina))}
      </tbody>
    </table>
  )
}

export default function PanelConciliacion({ comprobante: c, aplicar, desvincular }: Props) {
  const [candidatos, setCandidatos] = useState<{ id: number; clave: string; lista: Movimiento[] } | null>(null)
  const [verOpciones, setVerOpciones] = useState(false)
  const [prevId, setPrevId] = useState(c.id)
  if (prevId !== c.id) {
    setPrevId(c.id)
    setVerOpciones(false)
  }

  const clave = `${c.conciliacion}|${c.monto}|${c.fecha}|${c.candidatos.join(',')}`
  const buscar = (!c.movimiento && BUSCAR_CANDIDATOS.has(c.conciliacion)) || verOpciones
  const tieneDatosEstadoCuenta = Object.values(c.fuente).includes('estado_cuenta')

  useEffect(() => {
    if (!buscar) return
    let vigente = true
    api.candidatos(c.id).then((lista) => vigente && setCandidatos({ id: c.id, clave, lista }))
    return () => {
      vigente = false
    }
  }, [buscar, c.id, clave])

  if (c.conciliacion === '') {
    return (
      <div className="panel-conciliacion">
        <strong>Estado de cuenta</strong>
        <p className="ayuda">Carga tus estados de cuenta en la sección "Estados de cuenta" para verificar este comprobante.</p>
      </div>
    )
  }

  const diferencias = new Set(Object.keys(c.conciliacion_diferencias))
  const lista = candidatos && candidatos.id === c.id && candidatos.clave === clave ? candidatos.lista : null
  const titulos = Object.fromEntries(CAMPOS.map((x) => [x.campo, x.titulo]))

  return (
    <div className="panel-conciliacion">
      <div className="encabezado">
        <strong>Estado de cuenta</strong> <InsigniaConciliacion comprobante={c} />
      </div>
      {c.conciliacion_criterio && <p className="ayuda">{c.conciliacion_criterio}</p>}

      {c.movimiento && (
        <>
          <DatosMovimiento m={c.movimiento} diferencias={diferencias} />
          {diferencias.size > 0 && c.conciliacion !== 'usado' && (
            <div className="completar">
              <span>
                Difiere o falta:{' '}
                {Object.entries(c.conciliacion_diferencias)
                  .map(([k, v]) => `${titulos[k] ?? k} → ${v}`)
                  .join(', ')}
              </span>
              <button onClick={() => aplicar()}>Completar con estado de cuenta</button>
            </div>
          )}
          <div className="acciones">
            <button className="secundario" onClick={() => setVerOpciones((v) => !v)}>
              {verOpciones ? 'Ocultar coincidencias' : 'Ver otras coincidencias'}
            </button>
            {tieneDatosEstadoCuenta && (
              <button
                className="secundario"
                onClick={() => {
                  setVerOpciones(false)
                  desvincular()
                }}
              >
                Quitar selección y volver a coincidencias
              </button>
            )}
          </div>
        </>
      )}

      {buscar && (
        <div className="candidatos">
          <strong>Movimientos con el mismo monto</strong>
          {!lista && <p className="ayuda">Buscando…</p>}
          {lista?.length === 0 && <p className="ayuda">No hay movimientos con ese monto.</p>}
          {lista && lista.length > 0 && (
            <table className="tabla compacta">
              <tbody>
                {lista.map((m) => {
                  const esActual = c.movimiento?.id === m.id
                  const usadoPorOtro = m.comprobante_id && m.comprobante_id !== c.id
                  return (
                    <tr key={m.id} className={esActual ? 'seleccionada' : ''}>
                      <td>{m.fecha_operacion}</td>
                      <td>
                        {m.descripcion}
                        <div className="tenue">{m.nombre_contraparte || m.concepto}</div>
                      </td>
                      <td className="mono">{m.clave_rastreo ?? m.referencia}</td>
                      <td>{moneda(m.abono ?? m.cargo)}</td>
                      <td>
                        {esActual ? (
                          <span className="tenue">Seleccionado</span>
                        ) : usadoPorOtro ? (
                          <span className="tenue" title={m.comprobante_nombre ?? ''}>
                            Usado (#{m.comprobante_id})
                          </span>
                        ) : (
                          <button
                            className="secundario"
                            onClick={() => {
                              setVerOpciones(false)
                              aplicar(m.id)
                            }}
                          >
                            Usar este
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
