// Appels au backend. Vite proxifie /api vers http://127.0.0.1:8000
// (voir vite.config.ts).

import type {
  Axe, DossierDisponible, FichePatient, Prevol, Synthese, Travail,
} from '../types/analysis';

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${url}`);
  return (await r.json()) as T;
}

export const api = {
  synthese: () => get<Synthese>('/api/synthese'),

  axes: (cohorte: 'etude' | 'clinique' = 'etude', verdict?: string) =>
    get<Axe[]>(
      `/api/axes?cohorte=${cohorte}` + (verdict ? `&verdict=${verdict}` : ''),
    ),

  /** Les refus, triés par sténose présumée décroissante. */
  filePrioritaire: () => get<Axe[]>('/api/file-prioritaire'),

  patient: (id: string) => get<FichePatient>(`/api/patients/${id}`),

  /** Dossiers DICOM que le serveur voit sous ses racines declarees. */
  dossiersDisponibles: () =>
    get<DossierDisponible[]>('/api/dossiers-disponibles'),

  /** Recevabilite d'un dossier, sans lancer l'analyse. Deux secondes de
   *  lecture d'en-tetes contre douze minutes de segmentation. */
  prevol: (dossier: string) =>
    fetch('/api/dossiers/prevol', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dossier }),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail ?? 'controle impossible');
      return (await r.json()) as Prevol;
    }),

  /** Cree un travail sur un dossier deja present sur le serveur.
   *  Zero octet transfere : le pipeline lit la ou le fichier se trouve. */
  deposerLocal: (dossier: string) =>
    fetch('/api/travaux/local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dossier }),
    }).then(async (r) => {
      if (!r.ok) throw new Error((await r.json()).detail ?? 'depot impossible');
      return (await r.json()) as Travail;
    }),

  travaux: () => get<Travail[]>('/api/travaux'),

  travail: (id: string) => get<Travail>(`/api/travaux/${id}`),

  /** Crée un travail et rend la main : l'analyse dure une quinzaine de
   *  minutes, aucune requête HTTP ne tient cette durée. */
  async deposer(fichiers: File[]): Promise<Travail> {
    const fd = new FormData();
    fichiers.forEach((f) => fd.append('fichiers', f, f.name));
    const r = await fetch('/api/travaux', { method: 'POST', body: fd });
    if (!r.ok) {
      const e = await r.json().catch(() => ({ detail: 'envoi impossible' }));
      throw new Error(e.detail ?? 'envoi impossible');
    }
    return (await r.json()) as Travail;
  },

  annuler: (id: string) =>
    fetch(`/api/travaux/${id}/annuler`, { method: 'POST' }).then((r) => r.json()),

  corriger: (c: {
    patient: string;
    cote: string;
    cohorte?: string;
    verdict_humain: 'mesurable' | 'non_mesurable' | 'pas_de_stenose';
    auteur?: string;
    nascet_humain?: number;
    commentaire?: string;
  }) =>
    fetch('/api/corrections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(c),
    }).then((r) => r.json()),
};
