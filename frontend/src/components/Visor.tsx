import { useEffect, useState } from 'react'
import { CAMPOS, ETIQUETA_ESTADO, type Banco, type Campo, type Comprobante, type Cuenta } from '../api'
import { descripcionCampo } from '../campos'
import CeldaEditable from './CeldaEditable'
import PanelConciliacion from './PanelConciliacion'

interface Props {
  comprobante: Comprobante
  bancos: Banco[]
  cuentas: Cuenta[]
  posicion: string
  cerrar: () => void
  anterior: (() => void) | null
  siguiente: (() => void) | null
  guardarCampo: (campo: Campo, valor: string) => void
  marcarRevisado: () => void
  marcarIncidencia: (comentario: string) => void
  quitarIncidencia: () => void
  guardarComentario: (comentario: string) => void
  guardarAuxiliar: (campo: 'folio' | 'referencia', valor: string) => void
  aplicarMovimiento: (movimientoId?: number) => void
  desvincularMovimiento: () => void
  reprocesar: () => void
}

function CampoAuxiliar(props: {
  titulo: string
  valor: string | null
  ayuda: string
  deshabilitado: boolean
  guardar: (v: string) => void
}) {
  const actual = props.valor ?? ''
  const [valor, setValor] = useState(actual)
  const [previo, setPrevio] = useState(actual)
  if (previo !== actual) {
    setPrevio(actual)
    setValor(actual)
  }
  return (
    <label>
      {props.titulo}
      <input
        value={valor}
        disabled={props.deshabilitado}
        onChange={(e) => setValor(e.target.value)}
        onBlur={() => valor.trim() !== actual && props.guardar(valor)}
        onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
      />
      <small>{props.ayuda}</small>
    </label>
  )
}

export default function Visor(props: Props) {
  const { comprobante: c } = props
  const [zoom, setZoom] = useState(1)
  const [comentario, setComentario] = useState(c.comentario)
  const [previo, setPrevio] = useState({ id: c.id, comentario: c.comentario })
  if (previo.id !== c.id || previo.comentario !== c.comentario) {
    setPrevio({ id: c.id, comentario: c.comentario })
    setComentario(c.comentario)
  }
  const errores = Object.values(c.errores)

  useEffect(() => {
    const teclas = (e: KeyboardEvent) => {
      const enCampo = ['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)
      if (e.key === 'Escape') props.cerrar()
      if (enCampo) return
      if (e.key === 'ArrowLeft' && props.anterior) props.anterior()
      if (e.key === 'ArrowRight' && props.siguiente) props.siguiente()
    }
    window.addEventListener('keydown', teclas)
    return () => window.removeEventListener('keydown', teclas)
  }, [props])

  const procesando = c.estado === 'procesando'

  return (
    <div className="modal-fondo" onClick={props.cerrar}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <strong>{c.nombre_original}</strong>{' '}
            <span className={`estado estado-${c.estado}`}>{ETIQUETA_ESTADO[c.estado]}</span>
            <span className="posicion">{props.posicion}</span>
          </div>
          <div className="acciones">
            <button className="secundario" disabled={!props.anterior} onClick={() => props.anterior?.()}>
              ← Anterior
            </button>
            <button className="secundario" disabled={!props.siguiente} onClick={() => props.siguiente?.()}>
              Siguiente →
            </button>
            <button className="secundario" onClick={props.cerrar}>
              Cerrar
            </button>
          </div>
        </header>

        <div className="modal-cuerpo">
          <div className="visor-imagen">
            <div className="zoom">
              <button className="secundario" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>
                −
              </button>
              <span>{Math.round(zoom * 100)}%</span>
              <button className="secundario" onClick={() => setZoom((z) => Math.min(4, z + 0.25))}>
                +
              </button>
              <button className="secundario" onClick={() => setZoom(1)}>
                Ajustar
              </button>
            </div>
            <div className="lienzo">
              <img src={c.imagen_url} alt={c.nombre_original} style={{ width: `${zoom * 100}%` }} />
            </div>
          </div>

          <div className="visor-datos">
            {c.error && <div className="aviso error">{c.error}</div>}
            <div className="campos">
              {CAMPOS.map(({ campo, titulo }) => (
                <label key={campo}>
                  {titulo}
                  <CeldaEditable
                    comprobante={c}
                    campo={campo}
                    bancos={props.bancos}
                    cuentas={props.cuentas}
                    guardar={props.guardarCampo}
                    deshabilitada={procesando}
                  />
                  <small className={c.errores[campo] ? 'texto-error' : ''}>{descripcionCampo(c, campo)}</small>
                </label>
              ))}
              <CampoAuxiliar
                titulo="Folio"
                valor={c.folio}
                ayuda="No va al TXT; sirve para buscarlo en el estado de cuenta"
                deshabilitado={procesando}
                guardar={(v) => props.guardarAuxiliar('folio', v)}
              />
              <CampoAuxiliar
                titulo="Referencia"
                valor={c.referencia}
                ayuda="No va al TXT; sirve para buscarlo en el estado de cuenta"
                deshabilitado={procesando}
                guardar={(v) => props.guardarAuxiliar('referencia', v)}
              />
            </div>

            {!procesando && (
              <PanelConciliacion
                comprobante={c}
                aplicar={props.aplicarMovimiento}
                desvincular={props.desvincularMovimiento}
              />
            )}

            <label className="comentario">
              Comentario / incidencia
              <textarea
                value={comentario}
                rows={2}
                onChange={(e) => setComentario(e.target.value)}
                onBlur={() => comentario !== c.comentario && props.guardarComentario(comentario)}
                placeholder="Ej.: la foto no muestra la clave de rastreo"
              />
            </label>

            <div className="acciones">
              {c.estado !== 'revisado' && c.estado !== 'incidencia' && (
                <button onClick={props.marcarRevisado} disabled={procesando || errores.length > 0}>
                  Marcar revisado
                </button>
              )}
              {c.estado === 'incidencia' ? (
                <button className="secundario" onClick={props.quitarIncidencia}>
                  Quitar incidencia
                </button>
              ) : (
                <button
                  className="advertencia"
                  disabled={procesando}
                  onClick={() => props.marcarIncidencia(comentario)}
                >
                  Reportar incidencia
                </button>
              )}
              <button className="secundario" onClick={props.reprocesar} disabled={procesando}>
                Reprocesar OCR
              </button>
            </div>

            <details className="texto-ocr" open={!c.fecha && !c.monto}>
              <summary>Texto reconocido (OCR)</summary>
              <pre>{c.texto_ocr || 'Sin texto reconocido.'}</pre>
            </details>
          </div>
        </div>
      </div>
    </div>
  )
}
