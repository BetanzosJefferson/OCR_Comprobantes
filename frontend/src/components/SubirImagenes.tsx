import { useRef, useState } from 'react'

const EXTENSIONES = ['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.heif']

interface Props {
  subiendo: boolean
  hayLote: boolean
  subir: (archivos: File[], nombre: string, nuevoLote: boolean) => Promise<void>
}

export default function SubirImagenes({ subiendo, hayLote, subir }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [archivos, setArchivos] = useState<File[]>([])
  const [nombre, setNombre] = useState('')
  const [arrastrando, setArrastrando] = useState(false)
  const [rechazados, setRechazados] = useState<string[]>([])

  function agregar(lista: FileList | null) {
    if (!lista) return
    const nuevos = Array.from(lista)
    const validos = nuevos.filter((f) => EXTENSIONES.some((e) => f.name.toLowerCase().endsWith(e)))
    setRechazados(nuevos.filter((f) => !validos.includes(f)).map((f) => f.name))
    setArchivos((a) => [...a, ...validos])
  }

  async function enviar(nuevoLote: boolean) {
    await subir(archivos, nombre, nuevoLote)
    setArchivos([])
    setNombre('')
  }

  return (
    <div className="subida">
      <div
        className={`zona ${arrastrando ? 'arrastrando' : ''}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setArrastrando(true)
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastrando(false)
          agregar(e.dataTransfer.files)
        }}
      >
        <strong>Arrastra aquí las fotos de los comprobantes</strong>
        <span>o haz clic para seleccionarlas (JPG, PNG, HEIC…)</span>
        <input
          ref={input}
          type="file"
          multiple
          accept={['image/*', ...EXTENSIONES].join(',')}
          hidden
          onChange={(e) => {
            agregar(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {rechazados.length > 0 && (
        <div className="aviso error">Formato no soportado: {rechazados.join(', ')}</div>
      )}

      {archivos.length > 0 && (
        <div className="seleccion">
          <span>
            {archivos.length} imagen(es) seleccionada(s){' '}
            <button className="enlace" onClick={() => setArchivos([])}>
              Limpiar
            </button>
          </span>
          <input placeholder="Nombre del lote (opcional)" value={nombre} onChange={(e) => setNombre(e.target.value)} />
          <button disabled={subiendo} onClick={() => enviar(true)}>
            {subiendo ? 'Subiendo…' : 'Procesar en lote nuevo'}
          </button>
          {hayLote && (
            <button className="secundario" disabled={subiendo} onClick={() => enviar(false)}>
              Agregar al lote actual
            </button>
          )}
        </div>
      )}
    </div>
  )
}
