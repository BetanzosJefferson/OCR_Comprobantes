import { useEffect, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api'
import Bancos from './pages/Bancos'
import Cuentas from './pages/Cuentas'
import EstadosCuenta from './pages/EstadosCuenta'
import Procesar from './pages/Procesar'

export default function App() {
  const [tesseract, setTesseract] = useState<boolean | null>(null)

  useEffect(() => {
    api
      .estado()
      .then((e) => setTesseract(e.tesseract))
      .catch(() => setTesseract(null))
  }, [])

  return (
    <BrowserRouter>
      <header className="barra">
        <h1>OCR de Comprobantes</h1>
        <nav>
          <NavLink to="/" end>
            Procesar
          </NavLink>
          <NavLink to="/bancos">Bancos</NavLink>
          <NavLink to="/cuentas">Cuentas beneficiarias</NavLink>
          <NavLink to="/estados-cuenta">Estados de cuenta</NavLink>
        </nav>
      </header>
      {tesseract === false && (
        <div className="aviso error">
          Tesseract no está instalado en el servidor. Ejecuta <code>brew install tesseract tesseract-lang</code> y
          reinicia el backend.
        </div>
      )}
      <main>
        <Routes>
          <Route path="/" element={<Procesar />} />
          <Route path="/bancos" element={<Bancos />} />
          <Route path="/cuentas" element={<Cuentas />} />
          <Route path="/estados-cuenta" element={<EstadosCuenta />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
