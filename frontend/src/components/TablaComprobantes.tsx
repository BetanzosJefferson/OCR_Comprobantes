import { CAMPOS, ETIQUETA_ESTADO, type Banco, type Campo, type Comprobante, type Cuenta } from '../api'
import CeldaEditable from './CeldaEditable'
import InsigniaConciliacion from './InsigniaConciliacion'

interface Props {
  comprobantes: Comprobante[]
  bancos: Banco[]
  cuentas: Cuenta[]
  guardarCampo: (c: Comprobante, campo: Campo, valor: string) => void
  marcarRevisado: (c: Comprobante) => void
  reportarIncidencia: (c: Comprobante) => void
  quitarIncidencia: (c: Comprobante) => void
  abrir: (c: Comprobante) => void
  reprocesar: (c: Comprobante) => void
  eliminar: (c: Comprobante) => void
}

export default function TablaComprobantes(props: Props) {
  const { comprobantes, bancos, cuentas } = props

  return (
    <div className="tabla-contenedor">
      <table className="tabla comprobantes">
        <thead>
          <tr>
            <th>Imagen</th>
            <th>Nombre</th>
            <th>Estado</th>
            {CAMPOS.map((c) => (
              <th key={c.campo}>{c.titulo}</th>
            ))}
            <th>Estado de cuenta</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
          {comprobantes.map((c) => {
            const procesando = c.estado === 'procesando'
            const errores = Object.values(c.errores)
            return (
              <tr key={c.id} className={`fila-${c.estado}`}>
                <td>
                  <button className="miniatura" onClick={() => props.abrir(c)} title="Ver imagen y texto OCR">
                    <img src={c.imagen_url} alt={c.nombre_original} loading="lazy" />
                  </button>
                </td>
                <td className="celda-nombre" title={c.nombre_original}>
                  {c.nombre_original}
                </td>
                <td>
                  <span className={`estado estado-${c.estado}`}>{ETIQUETA_ESTADO[c.estado]}</span>
                  {c.error && <div className="detalle-error">{c.error}</div>}
                  {c.estado === 'incidencia' && c.comentario && (
                    <div className="detalle-error" title={c.comentario}>
                      {c.comentario}
                    </div>
                  )}
                  {!procesando && errores.length > 0 && c.estado !== 'incidencia' && (
                    <div className="detalle-error">{errores.length} campo(s) por corregir</div>
                  )}
                </td>
                {CAMPOS.map(({ campo }) => (
                  <td key={campo}>
                    {procesando ? (
                      <span className="cargando" />
                    ) : (
                      <CeldaEditable
                        comprobante={c}
                        campo={campo}
                        bancos={bancos}
                        cuentas={cuentas}
                        guardar={(campo, valor) => props.guardarCampo(c, campo, valor)}
                      />
                    )}
                  </td>
                ))}
                <td>
                  <button className="enlace" onClick={() => props.abrir(c)}>
                    <InsigniaConciliacion comprobante={c} />
                  </button>
                </td>
                <td className="acciones-fila">
                  {!procesando && (
                    <>
                      {c.estado !== 'revisado' && c.estado !== 'incidencia' && (
                        <button
                          onClick={() => props.marcarRevisado(c)}
                          disabled={errores.length > 0}
                          title={errores.length ? 'Corrige los campos marcados en rojo' : 'Confirmar datos'}
                        >
                          Revisado
                        </button>
                      )}
                      {c.estado === 'incidencia' ? (
                        <button className="secundario" onClick={() => props.quitarIncidencia(c)}>
                          Quitar incidencia
                        </button>
                      ) : (
                        <button className="advertencia" onClick={() => props.reportarIncidencia(c)}>
                          Incidencia
                        </button>
                      )}
                      <details className="menu">
                        <summary>⋯</summary>
                        <div>
                          <button className="secundario" onClick={() => props.abrir(c)}>
                            Ver detalle
                          </button>
                          <button className="secundario" onClick={() => props.reprocesar(c)}>
                            Reprocesar OCR
                          </button>
                          <button className="peligro" onClick={() => props.eliminar(c)}>
                            Eliminar
                          </button>
                        </div>
                      </details>
                    </>
                  )}
                </td>
              </tr>
            )
          })}
          {comprobantes.length === 0 && (
            <tr>
              <td colSpan={CAMPOS.length + 5} className="vacio">
                No hay comprobantes en esta vista.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
