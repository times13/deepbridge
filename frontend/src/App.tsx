import { useEffect, useState } from 'react';

import DepotPatient from './pages/DepotPatient';
import FichePatientPage from './pages/FichePatient';
import { BarreReduction, COULEUR, n1 } from './components/Verdict';
import { api } from './services/api';
import type { Axe, Synthese, Verdict } from './types/analysis';

type Vue = 'depot' | 'cohorte' | 'patient';

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
              ['cohorte', "Cohorte d'étude"],
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
      {vue === 'cohorte' && (
        <CohorteEtude synthese={synthese} onOuvrirPatient={ouvrir} />
      )}
      {vue === 'patient' && patient && (
        <FichePatientPage patient={patient} onRetour={() => setVue('depot')} />
      )}
    </div>
  );
}

/**
 * Cohorte d'étude — les 292 axes mesurés en lot, filtrables par verdict.
 *
 * Cet écran n'a PAS de vocation clinique : ces patients ont été opérés entre
 * 2010 et 2017, aucun clinicien ne rouvrira leur dossier. Il sert à inspecter
 * le travail et à le montrer.
 *
 * Les axes non mesurables y sont triés par sténose présumée décroissante. Les
 * refus sont significativement plus sténosés que les mesures publiées —
 * 56,8 % contre 46,8 %, p = 3e-7 — et 16,8 % dépasseraient 70 % contre 5,2 %.
 * La chaîne ne sait pas mesurer les cas graves, mais elle sait les reconnaître.
 */
function CohorteEtude({
  synthese,
  onOuvrirPatient,
}: {
  synthese: Synthese | null;
  onOuvrirPatient: (p: string) => void;
}) {
  const [filtre, setFiltre] = useState<Verdict | null>(null);
  const [axes, setAxes] = useState<Axe[] | null>(null);

  useEffect(() => {
    setAxes(null);
    const p =
      filtre === 'non_calculable'
        ? api.filePrioritaire()   // triés par sévérité présumée
        : api.axes('etude', filtre ?? undefined);
    p.then(setAxes).catch(() => setAxes([]));
  }, [filtre]);

  const v = synthese?.etude.verdicts ?? [];

  return (
    <div className="p-6 md:p-10">
      <h2 className="text-xl font-semibold uppercase tracking-[0.09em]">
        Cohorte d'étude
      </h2>
      <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-[#8B97A8]">
        292 axes mesurés en lot sur 146 patients du CHU de Nice, examens de 2010
        à 2017. Fichier figé, en lecture seule — c'est ce qui rend les chiffres
        du mémoire vérifiables. Aucune vocation clinique : ces patients ont tous
        été opérés.
      </p>

      {/* Le bandeau EST la répartition des verdicts, à l'échelle. Il filtre. */}
      <div className="mt-6 flex h-9 max-w-4xl overflow-hidden rounded">
        {v.map((x) => (
          <button
            key={x.code}
            onClick={() => setFiltre(filtre === x.code ? null : x.code)}
            title={`${x.libelle} — ${x.n} axes (${x.pct} %)`}
            aria-pressed={filtre === x.code}
            className="flex items-center justify-center gap-2 whitespace-nowrap px-2 text-[11.5px] font-semibold text-[#10141A] transition hover:brightness-110"
            style={{
              background: COULEUR[x.code],
              flex: Math.max(x.n, 12),
              boxShadow: filtre === x.code ? 'inset 0 -3px 0 #10141A' : undefined,
            }}
          >
            <span className="truncate">{x.libelle}</span>
            <span className="font-mono">{x.n}</span>
          </button>
        ))}
      </div>

      <p className="mt-3 max-w-3xl text-[12px] text-[#8B97A8]">
        {!axes
          ? 'Chargement…'
          : filtre === 'non_calculable'
            ? `${axes.length} axes non mesurables, classés par sténose présumée décroissante. Les valeurs marquées ~ sont indicatives et ne doivent pas être reportées dans un compte rendu.`
            : filtre
              ? `${axes.length} axes — cliquez à nouveau sur la bande pour enlever le filtre.`
              : `${axes.length} axes. Chaque barre trace d réf et d min à la même échelle.`}
      </p>

      <div className="mt-5 max-w-3xl divide-y divide-[#39424F] border-y border-[#39424F]">
        {(axes ?? []).map((a) => (
          <button
            key={`${a.patient}-${a.cote}`}
            onClick={() => onOuvrirPatient(a.patient)}
            className="block w-full px-2 py-3 text-left hover:bg-[#222933]"
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-mono text-[13px]">
                {a.patient} <em className="not-italic text-[#8B97A8]">{a.cote}</em>
              </span>
              <span
                className="font-mono text-[12.5px] font-semibold"
                style={{ color: COULEUR[a.verdict] }}
              >
                {a.nascet_pct !== null
                  ? `≥ ${n1(a.nascet_pct)} %`
                  : a.verdict === 'non_calculable'
                    ? `~ ${n1(a.nascet_implicite)} %`
                    : '—'}
              </span>
            </div>
            {a.cause && (
              <p className="mt-1 text-[11.5px] text-[#8B97A8]">{a.cause}</p>
            )}
            <BarreReduction axe={a} />
          </button>
        ))}
      </div>
    </div>
  );
}
