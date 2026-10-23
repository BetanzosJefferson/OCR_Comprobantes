import { useRef } from 'react'
import type { ResultadoImportacion } from '../api'

interface Props {
  importar: (f: File) => Promise<ResultadoImportacion>
  exportarUrl: string
  ayuda: string
  alTerminar: (mensaje: string, error?: boolean) => void
}

export default function ImportarCsv({ importar, exportarUrl, ayuda, alTerminar }: Props) {
  const input = useRef<HTMLInputElement>(null)

  async function alElegir(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0]
    e.target.value = ''
    if (!archivo) return
    try {
      const r = await importar(archivo)
      const resumen = `Importación: ${r.creados} creados, ${r.actualizados} actualizados.`
      alTerminar(r.errores.length ? `${resumen} Errores:\n${r.errores.join('\n')}` : resumen, r.errores.length > 0)
    } catch (err) {
      alTerminar((err as Error).message, true)
    }
  }

  return (
    <div className="csv">
      <button className="secundario" onClick={() => input.current?.click()} title={ayuda}>
        Importar CSV
      </button>
      <a className="boton secundario" href={exportarUrl}>
        Exportar CSV
      </a>
      <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={alElegir} />
      <small>{ayuda}</small>
    </div>
  )
}
