import { ETIQUETA_CONCILIACION, type Comprobante } from '../api'
import { moneda } from '../campos'

export default function InsigniaConciliacion({ comprobante: c }: { comprobante: Comprobante }) {
  if (c.estado === 'procesando') return null
  const m = c.movimiento
  const titulo = [
    c.conciliacion_criterio,
    m && `${m.fecha_operacion} · ${m.descripcion} · ${moneda(m.abono ?? m.cargo)} · Ref. ${m.referencia ?? '—'}`,
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <span className={`conciliacion conciliacion-${c.conciliacion || 'ninguna'}`} title={titulo}>
      {ETIQUETA_CONCILIACION[c.conciliacion]}
    </span>
  )
}
