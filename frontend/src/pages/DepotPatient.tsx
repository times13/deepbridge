import { useCallback, useEffect, useState } from 'react';

import { api } from '../services/api';
import type {
  DossierDisponible, EtatTravail, Prevol, Travail,
} from '../types/analysis';

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

const TEINTE = {
  recevable: { bord: '#63C9B4', fond: 'rgba(99,201,180,.1)' },
  reserve: { bord: '#E0AB4E', fond: 'rgba(224,171,78,.1)' },
  refus: { bord: '#E0705E', fond: 'rgba(224,112,94,.1)' },
} as const;

/**
 * Dépôt d'un dossier DICOM par SÉLECTION, non par téléversement.
 *
 * Le navigateur ne transmet jamais de chemin de fichier à JavaScript : une
 * page ne peut envoyer que du contenu. Téléverser 600 Mo vers un serveur qui
 * tourne sur la même machine que le fichier n'a aucun sens — et c'est l'inverse
 * de l'usage réel, où un poste hospitalier monte le partage PACS et désigne un
 * dossier.
 *
 * Le serveur énumère donc ce qu'il voit sous ses racines déclarées, le client
 * choisit. Zéro octet transféré.
 */
export default function DepotPatient({
  onOuvrirPatient,
}: {
  onOuvrirPatient: (patient: string) => void;
}) {
  const [dossiers, setDossiers] = useState<DossierDisponible[] | null>(null);
  const [choisi, setChoisi] = useState<string | null>(null);
  const [prevol, setPrevol] = useState<Prevol | null>(null);
  const [travaux, setTravaux] = useState<Travail[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [occupe, setOccupe] = useState(false);

  const rafraichir = useCallback(() => {
    api.travaux().then(setTravaux).catch(() => {});
  }, []);

  useEffect(() => {
    api.dossiersDisponibles().then(setDossiers).catch((e) => {
      setDossiers([]);
      setErreur(String(e));
    });
    rafraichir();
    const t = setInterval(rafraichir, 4000);
    return () => clearInterval(t);
  }, [rafraichir]);

  // Le pré-vol coûte deux secondes de lecture d'en-têtes contre douze minutes
  // de segmentation : autant savoir avant de lancer.
  async function selectionner(chemin: string) {
    setChoisi(chemin);
    setPrevol(null);
    setErreur(null);
    try {
      setPrevol(await api.prevol(chemin));
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    }
  }

  async function lancer() {
    if (!choisi) return;
    setOccupe(true);
    setErreur(null);
    try {
      await api.deposerLocal(choisi);
      setChoisi(null);
      setPrevol(null);
      rafraichir();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setOccupe(false);
    }
  }

  const teinte = prevol ? TEINTE[prevol.issue] : null;

    // Un même dossier peut être redéposé après un échec : chaque dépôt crée un
  // nouveau travail, l'ancien reste en trace. Sans marquer les dépassés, deux
  // cartes du même patient s'affichent sans qu'on sache laquelle fait foi.
  // La liste étant triée du plus récent au plus ancien, le premier travail
  // rencontré pour un patient est celui qui compte.
  const vus = new Set<string>();
  const depasses = new Set<string>();
  for (const t of travaux) {
    if (!t.patient_id) continue;
    if (vus.has(t.patient_id)) depasses.add(t.id);
    else vus.add(t.patient_id);
  }

  return (
    <div className="min-h-screen bg-[#191E26] p-6 text-[#DDE3EA] md:p-10">
      <h1 className="text-xl font-semibold uppercase tracking-[0.09em]">
        Nouveau patient
      </h1>
      <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-[#8B97A8]">
        Choisissez un dossier DICOM parmi ceux que le serveur voit. L'analyse dure
        une quinzaine de minutes — vous pouvez fermer cette page, le travail se 
        poursuit côté serveur.
      </p>

      {erreur && (
        <div className="mt-4 max-w-3xl border-l-[3px] border-[#E0705E] bg-[#E0705E]/10 px-4 py-3 text-[13px]">
          <b className="text-[#E0705E]">Erreur.</b> {erreur}
        </div>
      )}

      <div className="mt-6 grid max-w-5xl gap-6 lg:grid-cols-2">
        <section>
          <h2 className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-[#8B97A8]">
            Dossiers disponibles
          </h2>
          {dossiers === null ? (
            <p className="text-[13px] text-[#8B97A8]">Lecture…</p>
          ) : dossiers.length === 0 ? (
            <p className="max-w-md text-[13px] leading-relaxed text-[#8B97A8]">
              Aucun dossier. Renseignez{' '}
              <span className="font-mono">racines_dicom</span> dans{' '}
              <span className="font-mono">backend/.env</span>, par exemple{' '}
              <span className="font-mono">
                racines_dicom=["E:/dataset_chu_nice/scan"]
              </span>
            </p>
          ) : (
            <div className="max-h-[26rem] divide-y divide-[#39424F] overflow-y-auto rounded border border-[#39424F]">
              {dossiers.map((d) => (
                <button
                  key={d.chemin}
                  onClick={() => void selectionner(d.chemin)}
                  className={`block w-full px-3 py-2.5 text-left hover:bg-[#222933] ${
                    choisi === d.chemin ? 'bg-[#2B3340]' : ''
                  }`}
                >
                  <div className="truncate font-mono text-[12px]">{d.nom}</div>
                  <div className="text-[11px] text-[#8B97A8]">
                    {d.fichiers} fichiers
                  </div>
                </button>
              ))}
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-[#8B97A8]">
            Recevabilité
          </h2>
          {!choisi ? (
            <p className="text-[13px] text-[#8B97A8]">
              Choisissez un dossier pour contrôler sa recevabilité.
            </p>
          ) : !prevol || !teinte ? (
            <p className="text-[13px] text-[#8B97A8]">Lecture des en-têtes…</p>
          ) : (
            <>
              <div
                className="border-l-[3px] px-4 py-3 text-[13px]"
                style={{ borderColor: teinte.bord, background: teinte.fond }}
              >
                <b>{prevol.message}</b>
                {[...prevol.bloquants, ...prevol.reserves].map((x) => (
                  <p key={x} className="mt-2 text-[#8B97A8]">
                    {x}
                  </p>
                ))}
              </div>

              <table className="mt-3 w-full text-[12px]">
                <tbody>
                  {Object.entries(prevol.indices)
                    .filter(([, v]) => v !== null && v !== undefined)
                    .map(([k, v]) => (
                      <tr key={k} className="border-b border-[#39424F]">
                        <td className="py-1 text-[#8B97A8]">{k}</td>
                        <td className="py-1 text-right font-mono">
                          {String(v)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>

              <button
                onClick={() => void lancer()}
                disabled={prevol.issue === 'refus' || occupe}
                className="mt-4 rounded px-4 py-2 text-[13px] font-semibold text-[#10141A] disabled:cursor-not-allowed disabled:bg-[#39424F] disabled:text-[#8B97A8]"
                style={
                  prevol.issue === 'refus' || occupe
                    ? undefined
                    : { background: '#63C9B4' }
                }
              >
                {occupe ? 'Lancement…' : "Lancer l'analyse"}
              </button>
            </>
          )}
        </section>
      </div>

            {travaux.length > 0 && (
        <section className="mt-10 max-w-3xl">
          <h2 className="mb-3 text-[11px] font-bold uppercase tracking-[0.1em] text-[#8B97A8]">
            Analyses ({travaux.length})
          </h2>
          <div className="space-y-3">
            {travaux.map((t) => (
              <CarteTravail
                key={t.id}
                t={t}
                depasse={depasses.has(t.id)}
                onOuvrirPatient={onOuvrirPatient}
              />
            ))}
          </div>
        </section>
      )}
      </div>
  );
}

function CarteTravail({
  t,
  depasse = false,
  onOuvrirPatient,
}: {
  t: Travail;
  depasse?: boolean;
  onOuvrirPatient: (p: string) => void;
}) {
  const c = COULEUR_ETAT[t.etat] ?? '#7E8CA0';

  return (
    <div
      className={`rounded border border-[#39424F] p-4 ${
        depasse ? 'opacity-45' : ''
      }`}
    >
            <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {/* Le dossier d'abord : c'est ce que l'utilisateur a choisi.
              Le PatientID vient du DICOM et n'apparaît qu'après le pré-vol. */}
          <div className="truncate font-mono text-[12.5px]" title={t.dossier_nom ?? ''}>
            {t.dossier_nom ?? '—'}
          </div>
            <div className="mt-0.5 text-[11px] text-[#8B97A8]">
            {t.patient_id
              ? <>PatientID <span className="font-mono text-[#DDE3EA]">{t.patient_id}</span></>
              : 'PatientID en cours de lecture'}
            {' · '}
            <span className="font-mono">
              {new Date(t.cree_le).toLocaleString('fr-FR', {
                day: '2-digit', month: '2-digit',
                hour: '2-digit', minute: '2-digit',
              })}
            </span>
          </div>
        </div>
        <span
          className="shrink-0 text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: c }}
        >
          {t.etat.replace('_', ' ')}
        </span>
      {depasse && (
        <p className="mt-1 text-[11px] italic text-[#8B97A8]">
          Remplacé par une analyse plus récente de ce patient.
        </p>
      )}
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

      {FINI.includes(t.etat) && t.etat === 'termine' && t.patient_id && (
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
