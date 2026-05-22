import { useState } from 'react'
import { DicomViewer } from '../components/DicomViewer'

type AnalysisResult = {
  stenosisRight: number
  stenosisLeft: number
  ecstRight: number
  ecstLeft: number
  operativeRisk: number
  recommendation: string
  shouldOperate: boolean
}

const MOCK_RESULT: AnalysisResult = {
  stenosisRight: 68,
  stenosisLeft: 31,
  ecstRight: 79,
  ecstLeft: 48,
  operativeRisk: 14,
  recommendation: "Intervention recommandée sur la carotide droite (sténose ≥ 60%, critère NASCET). Risque opératoire acceptable au regard du bénéfice attendu.",
  shouldOperate: true,
}

export function PatientAnalysis() {
  const [files, setFiles] = useState<File[]>([])
  const [currentSlice, setCurrentSlice] = useState(0)
  const [analyzing, setAnalyzing] = useState(false)
  const [result, setResult] = useState<AnalysisResult | null>(null)

  function handleFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? [])
      .filter(f => f.name.endsWith('.dcm'))
      .sort((a, b) => a.name.localeCompare(b.name))
    setFiles(selected)
    setCurrentSlice(0)
    setResult(null)
  }

  function handleAnalyze() {
    setAnalyzing(true)
    setTimeout(() => {
      setResult(MOCK_RESULT)
      setAnalyzing(false)
    }, 2000)
  }

  const currentFile = files[currentSlice] ?? null

  return (
    <div className="flex h-[calc(100vh-68px)]">

      {/* Colonne gauche — viewer */}
      <div className="flex-1 flex flex-col gap-4 p-6">

        <label className="border-2 border-dashed border-gray-700 rounded-xl p-8 flex flex-col items-center gap-3 cursor-pointer hover:border-gray-500 transition-colors bg-gray-900">
          <span className="text-5xl text-gray-500">↑</span>
          <p className="text-lg font-medium text-gray-200">
            {files.length > 0 ? `${files.length} fichiers DICOM chargés` : 'Déposer les fichiers .dcm du patient'}
          </p>
          <p className="text-base text-gray-500">Cliquer pour parcourir ou glisser-déposer</p>
          <input
            type="file"
            accept=".dcm"
            multiple
            className="hidden"
            onChange={handleFiles}
          />
        </label>

        <div className="flex-1 bg-black rounded-xl overflow-hidden">
          <DicomViewer file={currentFile} />
        </div>

        {files.length > 1 && (
          <div className="flex items-center gap-3">
            <span className="text-base text-gray-400 whitespace-nowrap">
              Coupe {currentSlice + 1} / {files.length}
            </span>
            <input
              type="range"
              min={0}
              max={files.length - 1}
              value={currentSlice}
              onChange={e => setCurrentSlice(Number(e.target.value))}
              className="flex-1"
            />
          </div>
        )}
      </div>

      {/* Colonne droite — résultats */}
      <aside className="w-96 border-l border-gray-800 bg-gray-900 flex flex-col gap-5 p-6 overflow-y-auto">
        <h2 className="text-xl font-semibold text-gray-100">Analyse du patient</h2>

        <button
          onClick={handleAnalyze}
          disabled={files.length === 0 || analyzing}
          className="w-full py-3 rounded-lg border border-gray-700 text-base font-medium text-gray-100 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {analyzing ? 'Analyse en cours…' : '▶  Lancer l\'analyse IA'}
        </button>

        {result && (
          <>
            <hr className="border-gray-800" />

            <p className="text-base font-medium text-gray-400">Sténose carotidienne</p>

            <div className="bg-gray-800 rounded-lg p-4">
              <p className="text-sm text-gray-400 mb-1">Carotide droite — NASCET</p>
              <p className="text-4xl font-semibold text-white">{result.stenosisRight}%</p>
              <p className="text-sm text-gray-500 mt-1">
                ECST : {result.ecstRight}% &nbsp;
                <span className={`px-2 py-0.5 rounded text-sm ${result.stenosisRight >= 60 ? 'bg-orange-900/50 text-orange-300' : 'bg-green-900/50 text-green-300'}`}>
                  {result.stenosisRight >= 70 ? 'Sévère' : result.stenosisRight >= 50 ? 'Modérée-sévère' : 'Modérée'}
                </span>
              </p>
            </div>

            <div className="bg-gray-800 rounded-lg p-4">
              <p className="text-sm text-gray-400 mb-1">Carotide gauche — NASCET</p>
              <p className="text-4xl font-semibold text-white">{result.stenosisLeft}%</p>
              <p className="text-sm text-gray-500 mt-1">
                ECST : {result.ecstLeft}% &nbsp;
                <span className={`px-2 py-0.5 rounded text-sm ${result.stenosisLeft >= 60 ? 'bg-orange-900/50 text-orange-300' : 'bg-green-900/50 text-green-300'}`}>
                  {result.stenosisLeft >= 70 ? 'Sévère' : result.stenosisLeft >= 50 ? 'Modérée-sévère' : 'Modérée'}
                </span>
              </p>
            </div>

            <hr className="border-gray-800" />

            <p className="text-base font-medium text-gray-400">Risque opératoire</p>
            <div className="bg-gray-800 rounded-lg p-4">
              <p className="text-sm text-gray-400 mb-1">Probabilité de complication</p>
              <p className="text-4xl font-semibold text-white">{result.operativeRisk}%</p>
            </div>

            <hr className="border-gray-800" />

            <div className={`rounded-lg p-4 border ${result.shouldOperate ? 'border-red-800/50 bg-red-950/40' : 'border-green-800/50 bg-green-950/40'}`}>
              <p className={`text-base font-medium mb-2 ${result.shouldOperate ? 'text-red-400' : 'text-green-400'}`}>
                {result.shouldOperate ? '⚠ Intervention recommandée' : '✓ Surveillance recommandée'}
              </p>
              <p className="text-base text-gray-300 leading-relaxed">{result.recommendation}</p>
            </div>
          </>
        )}
      </aside>
    </div>
  )
}