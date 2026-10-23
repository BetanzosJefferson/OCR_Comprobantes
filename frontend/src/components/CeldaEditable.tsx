import { useState } from 'react'
import type { Banco, Campo, Comprobante, Cuenta } from '../api'
import { claseCampo, descripcionCampo } from '../campos'

interface Props {
  comprobante: Comprobante
  campo: Campo
  bancos: Banco[]
  cuentas: Cuenta[]
  guardar: (campo: Campo, valor: string) => void
  deshabilitada?: boolean
}

export default function CeldaEditable({ comprobante, campo, bancos, cuentas, guardar, deshabilitada }: Props) {
  const actual = comprobante[campo] ?? ''
  const [valor, setValor] = useState(actual)
  const [previo, setPrevio] = useState(actual)
  if (previo !== actual) {
    setPrevio(actual)
    setValor(actual)
  }

  const confirmar = (v: string) => {
    if (v.trim() !== actual) guardar(campo, v)
  }

  const comunes = {
    className: claseCampo(comprobante, campo),
    title: descripcionCampo(comprobante, campo),
    disabled: deshabilitada,
  }

  if (campo === 'emisor_clave' || campo === 'receptor_clave') {
    const existe = !actual || bancos.some((b) => b.clave === actual)
    return (
      <select {...comunes} value={actual} onChange={(e) => confirmar(e.target.value)}>
        <option value="">—</option>
        {!existe && <option value={actual}>{actual} (no configurado)</option>}
        {bancos.map((b) => (
          <option key={b.id} value={b.clave}>
            {b.clave} · {b.nombre}
          </option>
        ))}
      </select>
    )
  }

  if (campo === 'cuenta') {
    const activas = cuentas.filter((c) => c.activa)
    const existe = !actual || activas.some((c) => c.numero === actual)
    return (
      <select {...comunes} value={actual} onChange={(e) => confirmar(e.target.value)}>
        <option value="">—</option>
        {!existe && <option value={actual}>{actual} (no registrada)</option>}
        {activas.map((c) => (
          <option key={c.id} value={c.numero}>
            {c.numero}
            {c.titular ? ` · ${c.titular}` : ''}
          </option>
        ))}
      </select>
    )
  }

  return (
    <input
      {...comunes}
      type={campo === 'fecha' ? 'date' : 'text'}
      inputMode={campo === 'monto' ? 'decimal' : undefined}
      placeholder={campo === 'monto' ? '0.00' : ''}
      value={valor}
      onChange={(e) => setValor(e.target.value)}
      onBlur={(e) => confirmar(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
        if (e.key === 'Escape') setValor(actual)
      }}
    />
  )
}
