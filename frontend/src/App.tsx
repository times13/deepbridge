import { useEffect, useState } from 'react';

import DepotPatient from './pages/DepotPatient';
import FichePatientPage from './pages/FichePatient';
import { BarreReduction, n1 } from './components/Verdict';
import { api } from './services/api';
import type { Axe, Synthese } from './types/analysis';

type Vue = 'depot' | 'file' | 'patient';

/**
 * Routage par état local plutôt que react-router : trois vues, aucune URL
 * partageable à ce stade, et une dépendance de moins à installer.
 */
export default function App() {
  const [vue, setVue] = useState<Vue>('depot');
  const [patient, setPatient] = useState<string | null>(null);
  const [synthese, setSynthese] = useState<Synthese | null>(null);

  useEffect(() => {
    api.synthese().then(setSynthese).catch(() => {});
  }, []);

  const ouvrir = (p: string) => {
    setPatient(p);
    setVue('patient');
  };

  return (
    <div className="min-h-screen bg-[#191E26] font-sans text-[#DDE3EA]">
      <header className="flex flex-wrap items-baseline gap-4 border-b border-[#39424F] bg-[#222933] px-6 py-3">
        <h1 className="text-base font-bold uppercase tracking-[0.09em]">
          DeepBridge
        </h1>
        <nav className="flex gap-4 text-[13px]">
          {(
            [
              ['depot', 'Nouveau patient'],
              ['file', 'File prioritaire'],
            ] as const
          ).map(([v, lib]) => (
            <button
              key={v}
              onClick={() => setVue(v)}
              className={
                vue === v
                  ? 'font-semibold text-[#DDE3EA]'
                  : 'text-[#8B97A8] hover:text-[#DDE3EA]'
              }
            >
              {lib}
            </button>
          ))}
        </nav>
        {synthese && (
          <span className="ml-auto text-[12px] text-[#8B97A8]">
            Cohorte d'étude <b className="text-[#DDE3EA]">{synthese.etude.axes}</b> axes ·
            médiane <b className="text-[#DDE3EA]">{n1(synthese.etude.mediane_publiee)} %</b> ·
            dossiers cliniques <b className="text-[#DDE3EA]">{synthese.clinique.axes}</b>
          </span>
        )}
      </header>

      {vue === 'depot' && <DepotPatient onOuvrirPatient={ouvrir} />}
      {vue === 'file' && <FilePrioritaire onOuvrirPatient={ouvrir} />}
      {vue === 'patient' && patient && (
        <FichePatientPage patient={patient} onRetour={() => setVue('depot')} />
      )}
    </div>
  );
}

/**
 * File prioritaire — les axes non mesurables, triés par sténose présumée.
 *
 * Ce n'est pas un journal d'échecs. Les refus sont significativement plus
 * sténosés que les mesures publiées (56,8 % contre 46,8 %, p = 3e-7), et
 * 16,8 % dépasseraient 70 % contre 5,2 %. La chaîne ne sait pas mesurer les
 * cas graves, mais elle sait les reconnaître.
 */
function FilePrioritaire({
  onOuvrirPatient,
}: {
  onOuvrirPatient: (p: string) => void;
}) {
  const [axes, setAxes] = useState<Axe[] | null>(null);

  useEffect(() => {
    api.filePrioritaire().then(setAxes).catch(() => setAxes([]));
  }, []);

  if (!axes) return <p className="p-8 text-[#8B97A8]">Chargement…</p>;

  return (
    <div className="p-6 md:p-10">
      <h2 className="text-xl font-semibold">File prioritaire</h2>
      <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-[#8B97A8]">
        {axes.length} axes non mesurables, classés par sténose présumée décroissante.
        Les valeurs marquées <span className="font-mono">~</span> sont indicatives et ne
        doivent pas être reportées dans un compte rendu.
      </p>

      <div className="mt-6 max-w-3xl divide-y divide-[#39424F] border-y border-[#39424F]">
        {axes.map((a) => (
          <button
            key={`${a.patient}-${a.cote}`}
            onClick={() => onOuvrirPatient(a.patient)}
            className="block w-full px-2 py-3 text-left hover:bg-[#222933]"
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-mono text-[13px]">
                {a.patient} <em className="not-italic text-[#8B97A8]">{a.cote}</em>
              </span>
              <span className="font-mono text-[12px] text-[#E0705E]">
                ~ {n1(a.nascet_implicite)} %
              </span>
            </div>
            <p className="mt-1 text-[11.5px] text-[#8B97A8]">{a.cause}</p>
            <BarreReduction axe={a} />
          </button>
        ))}
      </div>
    </div>
  );
}
