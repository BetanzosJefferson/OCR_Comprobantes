import { CONFIANZA_MINIMA, type Campo, type Comprobante } from './api'

export function claseCampo(c: Comprobante, campo: Campo): string {
  if (c.errores[campo]) return 'campo-error'
  if (c.fuente[campo] === 'manual') return 'campo-manual'
  if (c.fuente[campo] === 'estado_cuenta') return 'campo-estado-cuenta'
  if ((c.confianza[campo] ?? 0) < CONFIANZA_MINIMA) return 'campo-dudoso'
  return 'campo-ok'
}

export function descripcionCampo(c: Comprobante, campo: Campo): string {
  const partes: string[] = []
  if (c.errores[campo]) partes.push(c.errores[campo]!)
  if (c.fuente[campo] === 'manual') partes.push('Capturado manualmente')
  else if (c.fuente[campo] === 'estado_cuenta') partes.push('Tomado del estado de cuenta')
  else if (c[campo]) partes.push(`Confianza OCR: ${Math.round((c.confianza[campo] ?? 0) * 100)}%`)
  const estado = c.conciliacion_diferencias[campo]
  if (estado) partes.push(`Estado de cuenta: ${estado}`)
  return partes.join(' · ')
}

export function moneda(valor: string | null): string {
  if (!valor) return ''
  return Number(valor).toLocaleString('es-MX', { style: 'currency', currency: 'MXN' })
}
