import { useEffect, useState } from 'react'
import { api, type Banco, type Cuenta, type CuentaInput } from '../api'
import ImportarCsv from '../components/ImportarCsv'

const TIPOS = [
  { valor: 'clabe', texto: 'CLABE' },
  { valor: 'tarjeta', texto: 'Tarjeta de débito' },
  { valor: 'celular', texto: 'Número celular' },
  { valor: 'cuenta', texto: 'Número de cuenta' },
]

const VACIO: CuentaInput = { numero: '', tipo: 'clabe', banco_receptor_id: 0, titular: '', activa: true }

export default function Cuentas() {
  const [cuentas, setCuentas] = useState<Cuenta[]>([])
  const [bancos, setBancos] = useState<Banco[]>([])
  const [form, setForm] = useState<CuentaInput>(VACIO)
  const [editando, setEditando] = useState<number | null>(null)
  const [mensaje, setMensaje] = useState<{ texto: string; error: boolean } | null>(null)

  const cargar = () => api.cuentas().then(setCuentas)
  useEffect(() => {
    cargar()
    api.bancos().then(setBancos)
  }, [])

  const avisar = (texto: string, error = false) => setMensaje({ texto, error })

  async function guardar(e: React.FormEvent) {
    e.preventDefault()
    try {
      if (editando) await api.actualizarCuenta(editando, form)
      else await api.crearCuenta(form)
      avisar(editando ? 'Cuenta actualizada' : 'Cuenta agregada')
      setForm(VACIO)
      setEditando(null)
      cargar()
    } catch (err) {
      avisar((err as Error).message, true)
    }
  }

  async function eliminar(c: Cuenta) {
    if (!confirm(`¿Eliminar la cuenta ${c.numero}?`)) return
    await api.eliminarCuenta(c.id)
    cargar()
  }

  async function alternarActiva(c: Cuenta) {
    await api.actualizarCuenta(c.id, {
      numero: c.numero,
      tipo: c.tipo,
      banco_receptor_id: c.banco_receptor_id,
      titular: c.titular,
      activa: !c.activa,
    })
    cargar()
  }

  return (
    <section>
      <h2>Cuentas beneficiarias</h2>
      <p className="ayuda">
        Solo se reconocen las cuentas registradas aquí. Si el comprobante muestra la cuenta enmascarada (por ejemplo{' '}
        <em>****2929</em>) se compara por los últimos dígitos. El banco receptor del comprobante se toma de la cuenta.
      </p>

      {bancos.length === 0 && (
        <div className="aviso error">Primero registra al menos un banco en la sección Bancos.</div>
      )}

      <form className="formulario" onSubmit={guardar}>
        <label>
          Número
          <input
            value={form.numero}
            onChange={(e) => setForm({ ...form, numero: e.target.value })}
            placeholder="CLABE, tarjeta o celular"
            inputMode="numeric"
            required
          />
        </label>
        <label>
          Tipo
          <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
            {TIPOS.map((t) => (
              <option key={t.valor} value={t.valor}>
                {t.texto}
              </option>
            ))}
          </select>
        </label>
        <label>
          Banco receptor
          <select
            value={form.banco_receptor_id || ''}
            onChange={(e) => setForm({ ...form, banco_receptor_id: Number(e.target.value) })}
            required
          >
            <option value="">Selecciona…</option>
            {bancos.map((b) => (
              <option key={b.id} value={b.id}>
                {b.clave} · {b.nombre}
              </option>
            ))}
          </select>
        </label>
        <label>
          Titular / alias
          <input value={form.titular} onChange={(e) => setForm({ ...form, titular: e.target.value })} />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={form.activa}
            onChange={(e) => setForm({ ...form, activa: e.target.checked })}
          />
          Activa
        </label>
        <div className="acciones">
          <button type="submit">{editando ? 'Guardar cambios' : 'Agregar cuenta'}</button>
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
        importar={api.importarCuentas}
        exportarUrl="/api/cuentas/export.csv"
        ayuda="Columnas: numero,tipo,banco_clave,titular,activa"
        alTerminar={(t, e) => {
          avisar(t, e)
          cargar()
        }}
      />

      <table className="tabla">
        <thead>
          <tr>
            <th>Número</th>
            <th>Tipo</th>
            <th>Banco receptor</th>
            <th>Titular</th>
            <th>Activa</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {cuentas.map((c) => (
            <tr key={c.id} className={c.activa ? '' : 'inactiva'}>
              <td className="mono">{c.numero}</td>
              <td>{TIPOS.find((t) => t.valor === c.tipo)?.texto ?? c.tipo}</td>
              <td>
                <span className="mono">{c.banco_receptor_clave}</span> {c.banco_receptor_nombre}
              </td>
              <td>{c.titular}</td>
              <td>
                <input type="checkbox" checked={c.activa} onChange={() => alternarActiva(c)} />
              </td>
              <td className="acciones-fila">
                <button
                  className="secundario"
                  onClick={() => {
                    setEditando(c.id)
                    setForm({
                      numero: c.numero,
                      tipo: c.tipo,
                      banco_receptor_id: c.banco_receptor_id,
                      titular: c.titular,
                      activa: c.activa,
                    })
                  }}
                >
                  Editar
                </button>
                <button className="peligro" onClick={() => eliminar(c)}>
                  Eliminar
                </button>
              </td>
            </tr>
          ))}
          {cuentas.length === 0 && (
            <tr>
              <td colSpan={6} className="vacio">
                Aún no hay cuentas configuradas.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
