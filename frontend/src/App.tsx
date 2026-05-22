import { useEffect, useState } from 'react'
import { PatientAnalysis } from './pages/PatientAnalysis'
import { checkHealth } from './services/api'

export default function App() {
  const [backendStatus, setBackendStatus] = useState<'connecting' | 'ok' | 'error'>('connecting')
  const [modelsLoaded, setModelsLoaded] = useState(false)

  useEffect(() => {
    checkHealth()
      .then(data => {
        setBackendStatus('ok')
        setModelsLoaded(data.models_loaded)
      })
      .catch(() => setBackendStatus('error'))
  }, [])

  return (
    <div className="min-h-screen bg-gray-950">
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center gap-4">
        <span className="text-white font-bold text-4xl">DeepBridge</span>
        <span className="text-gray-400 text-xl">Aide à la décision — sténose carotidienne</span>

        <div className="ml-auto flex items-center gap-3">
          <span className={`text-sm px-3 py-1 rounded-full border ${
            backendStatus === 'ok'
              ? 'text-green-400 border-green-800 bg-green-950/40'
              : backendStatus === 'error'
              ? 'text-red-400 border-red-800 bg-red-950/40'
              : 'text-gray-400 border-gray-700'
          }`}>
            {backendStatus === 'ok' ? '● Backend connecté' : backendStatus === 'error' ? '● Backend hors ligne' : '● Connexion…'}
          </span>

          {backendStatus === 'ok' && (
            <span className={`text-sm px-3 py-1 rounded-full border ${
              modelsLoaded
                ? 'text-green-400 border-green-800 bg-green-950/40'
                : 'text-yellow-400 border-yellow-800 bg-yellow-950/40'
            }`}>
              {modelsLoaded ? '● Modèles chargés' : '● Modèles en attente'}
            </span>
          )}
        </div>
      </nav>

      <PatientAnalysis />
    </div>
  )
}