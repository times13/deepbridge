import { PatientAnalysis } from './pages/PatientAnalysis'

export default function App() {
  return (
    <div className="min-h-screen bg-gray-950">
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center gap-4">
        <span className="text-white font-bold text-4xl">DeepBridge</span>
        <span className="text-gray-400 text-xl">Aide à la décision — sténose carotidienne</span>
      </nav>
      <PatientAnalysis />
    </div>
  )
}