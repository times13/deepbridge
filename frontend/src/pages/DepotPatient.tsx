import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../services/api';
import type { EtatTravail, Travail } from '../types/analysis';

const COULEUR_ETAT: Record<EtatTravail, string> = {
  en_attente: '#7E8CA0',
  prevol: '#E0AB4E',
  conversion: '#E0AB4E',
  segmentation: '#E0AB4E',
  axe: '#E0AB4E',
  mesure: '#E0AB4E',
  termine: '#63C9B4',
  echec: '#E0705E',
  annule: '#7E8CA0',
};

const FINI: EtatTravail[] = ['termine', 'echec', 'annule'];

/**
 * Dépôt d'un dossier DICOM et suivi de l'analyse.
 *
 * L'analyse dure une quinzaine de minutes : le dépôt rend la main
 * immédiatement et l'interface interroge l'état toutes les quatre secondes.
 * Fermer l'onglet n'interrompt rien — le travail vit côté serveur.
 */
export default function DepotPatient({
  onOuvrirPatient,
}: {
  onOuvrirPatient: (patient: string) => void;
}) {
  const [travaux, setTravaux] = useState<Travail[]>([]);
  const [envoi, setEnvoi] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [survol, setSurvol] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const rafraichir = useCallback(() => {
    api.travaux().then(setTravaux).catch(() => {});
  }, []);

  useEffect(() => {
    rafraichir();
    const t = setInterval(rafraichir, 4000);
    return () => clearInterval(t);
  }, [rafraichir]);

  async function envoyer(fichiers: File[]) {
    if (!fichiers.length) return;
    setErreur(null);
    setEnvoi(`Envoi de ${fichiers.length} fichiers…`);
    try {
      await api.deposer(fichiers);
      rafraichir();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setEnvoi(null);
    }
  }

  return (
    <div className="min-h-screen bg-[#191E26] p-6 text-[#DDE3EA] md:p-10">
      <h1 className="text-xl font-semibold uppercase tracking-[0.09em]">
        Nouveau patient
      </h1>
      <p className="mt-2 max-w-2xl text-[13px] text-[#8B97A8]">
        Déposez le dossier DICOM. L'analyse dure une quinzaine de minutes — vous
        pouvez fermer cet onglet, le travail se poursuit.
      </p>

      <div
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            input.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setSurvol(true);
        }}
        onDragLeave={() => setSurvol(false)}
        onDrop={(e) => {
          e.preventDefault();
          setSurvol(false);
          void envoyer([...e.dataTransfer.files]);
        }}
        className={`mt-6 max-w-2xl cursor-pointer rounded border border-dashed px-4 py-10 text-center text-[13px] transition ${
          survol
            ? 'border-[#63C9B4] bg-[#222933] text-[#DDE3EA]'
            : 'border-[#39424F] text-[#8B97A8] hover:border-[#63C9B4] hover:bg-[#222933]'
        }`}
      >
        {envoi ?? (
          <>
            Déposez ici le dossier DICOM du patient,
            <br />
            ou cliquez pour le choisir.
          </>
        )}
        <input
          ref={input}
          type="file"
          multiple
          // @ts-expect-error — attribut non standard, supporté par les navigateurs
          webkitdirectory=""
          hidden
          onChange={(e) => void envoyer([...(e.target.files ?? [])])}
        />
      </div>

      {erreur && (
        <div className="mt-4 max-w-2xl border-l-[3px] border-[#E0705E] bg-[#E0705E]/10 px-4 py-3 text-[13px]">
          <b className="text-[#E0705E]">Dépôt refusé.</b> {erreur}
        </div>
      )}

      <div className="mt-8 max-w-2xl space-y-3">
        {travaux.map((t) => (
          <CarteTravail key={t.id} t={t} onOuvrirPatient={onOuvrirPatient} />
        ))}
      </div>
    </div>
  );
}

function CarteTravail({
  t,
  onOuvrirPatient,
}: {
  t: Travail;
  onOuvrirPatient: (p: string) => void;
}) {
  const c = COULEUR_ETAT[t.etat] ?? '#7E8CA0';
  const fini = FINI.includes(t.etat);

  return (
    <div className="rounded border border-[#39424F] p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[13px]">{t.patient_id ?? '—'}</span>
        <span
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: c }}
        >
          {t.etat.replace('_', ' ')}
        </span>
      </div>

      <div className="my-2 h-1 overflow-hidden rounded bg-[#2B3340]">
        <div
          className="h-full transition-[width] duration-500"
          style={{ width: `${t.progression}%`, background: c }}
        />
      </div>

      <p className="text-[11.5px] leading-relaxed text-[#8B97A8]">{t.message}</p>

      {t.erreur && (
        <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-[#E0705E]">
          {t.erreur}
        </pre>
      )}

      {fini && t.etat === 'termine' && t.patient_id && (
        <button
          onClick={() => onOuvrirPatient(t.patient_id as string)}
          className="mt-3 text-[12px] font-semibold"
          style={{ color: c }}
        >
          → Voir les mesures
        </button>
      )}
    </div>
  );
}
