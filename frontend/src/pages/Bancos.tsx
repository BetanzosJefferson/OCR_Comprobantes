import { useEffect, useState } from 'react'
import { api, type Banco } from '../api'
import ImportarCsv from '../components/ImportarCsv'

const VACIO = { nombre: '', clave: '', alias: '' }

export default function Bancos() {
  const [bancos, setBancos] = useState<Banco[]>([])
  const [form, setForm] = useState(VACIO)
  const [editando, setEditando] = useState<number | null>(null)
  const [mensaje, setMensaje] = useState<{ texto: string; error: boolean } | null>(null)

  const cargar = () => api.bancos().then(setBancos)
  useEffect(() => {
    cargar()
  }, [])

  const avisar = (texto: string, error = false) => setMensaje({ texto, error })

  async function guardar(e: React.FormEvent) {
    e.preventDefault()
    const datos = {
      nombre: form.nombre.trim(),
      clave: form.clave.trim(),
      alias: form.alias
        .split(/[|,\n]/)
        .map((a) => a.trim())
        .filter(Boolean),
    }
    try {
      if (editando) await api.actualizarBanco(editando, datos)
      else await api.crearBanco(datos)
      avisar(editando ? 'Banco actualizado' : 'Banco agregado')
      setForm(VACIO)
      setEditando(null)
      cargar()
    } catch (err) {
      avisar((err as Error).message, true)
    }
  }

  async function eliminar(b: Banco) {
    if (!confirm(`¿Eliminar ${b.nombre}?`)) return
    try {
      await api.eliminarBanco(b.id)
      cargar()
    } catch (err) {
      avisar((err as Error).message, true)
    }
  }

  return (
    <section>
      <h2>Instituciones financieras</h2>
      <p className="ayuda">
        Registra la clave de cada institución y los textos con los que aparece en los comprobantes (alias). Los alias
        se usan para reconocer al banco emisor; por ejemplo: <em>BBVA, BANCOMER, BBVA MEXICO</em>.
      </p>

      <form className="formulario" onSubmit={guardar}>
        <label>
          Clave
          <input
            value={form.clave}
            onChange={(e) => setForm({ ...form, clave: e.target.value })}
            placeholder="40012"
            inputMode="numeric"
            pattern="\d+"
            required
          />
        </label>
        <label>
          Nombre
          <input
            value={form.nombre}
            onChange={(e) => setForm({ ...form, nombre: e.target.value })}
            placeholder="BBVA MEXICO"
            required
          />
        </label>
        <label className="ancho">
          Alias (separados por coma)
          <input
            value={form.alias}
            onChange={(e) => setForm({ ...form, alias: e.target.value })}
            placeholder="BBVA, BANCOMER"
          />
        </label>
        <div className="acciones">
          <button type="submit">{editando ? 'Guardar cambios' : 'Agregar banco'}</button>
          {editando && (
            <button
              type="button"
              className="secundario"
              onClick={() => {
                setEditando(null)
                setForm(VACIO)
              }}
            >
              Cancelar
            </button>
          )}
        </div>
      </form>

      {mensaje && <div className={`aviso ${mensaje.error ? 'error' : 'ok'}`}>{mensaje.texto}</div>}

      <ImportarCsv
        importar={api.importarBancos}
        exportarUrl="/api/bancos/export.csv"
        ayuda="Columnas: clave,nombre,alias (alias separados por |)"
        alTerminar={(t, e) => {
          avisar(t, e)
          cargar()
        }}
      />

      <table className="tabla">
        <thead>
          <tr>
            <th>Clave</th>
            <th>Nombre</th>
            <th>Alias</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {bancos.map((b) => (
            <tr key={b.id}>
              <td className="mono">{b.clave}</td>
              <td>{b.nombre}</td>
              <td>{b.alias.join(', ')}</td>
              <td className="acciones-fila">
                <button
                  className="secundario"
                  onClick={() => {
                    setEditando(b.id)
                    setForm({ nombre: b.nombre, clave: b.clave, alias: b.alias.join(', ') })
                  }}
                >
                  Editar
                </button>
                <button className="peligro" onClick={() => eliminar(b)}>
                  Eliminar
                </button>
              </td>
            </tr>
          ))}
          {bancos.length === 0 && (
            <tr>
              <td colSpan={4} className="vacio">
                Aún no hay bancos configurados.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
