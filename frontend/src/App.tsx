import { useEffect, useState } from 'react'
import { PatientAnalysis } from './pages/PatientAnalysis'
import { getPatients } from './services/api'

type Patient = {
  id: string
  name: string
  age: number
  sex: string
  scan_date: string
  slice_count: number
}

export default function App() {
  const [patients, setPatients] = useState<Patient[]>([])
  const [backendStatus, setBackendStatus] = useState<'connecting' | 'ok' | 'error'>('connecting')

  useEffect(() => {
    getPatients()
      .then(data => {
        setPatients(data)
        setBackendStatus('ok')
      })
      .catch(() => setBackendStatus('error'))
  }, [])

  return (
    <div className="min-h-screen bg-gray-950">
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center gap-4">
        <span className="text-white font-bold text-4xl">DeepBridge</span>
        <span className="text-gray-400 text-xl">Aide à la décision — sténose carotidienne</span>

        <div className="ml-auto flex items-center gap-3">
          {/* Statut backend */}
          <span className={`text-sm px-3 py-1 rounded-full border ${
            backendStatus === 'ok'
              ? 'text-green-400 border-green-800 bg-green-950/40'
              : backendStatus === 'error'
              ? 'text-red-400 border-red-800 bg-red-950/40'
              : 'text-gray-400 border-gray-700'
          }`}>
            {backendStatus === 'ok' ? '● Backend connecté' : backendStatus === 'error' ? '● Backend hors ligne' : '● Connexion…'}
          </span>

          {/* Patients mockés */}
          {patients.length > 0 && (
            <span className="text-sm text-gray-400 border border-gray-700 px-3 py-1 rounded-full">
              {patients.length} patients disponibles
            </span>
          )}
        </div>
      </nav>

      <PatientAnalysis />
    </div>
  )
}