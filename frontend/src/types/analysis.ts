// Contrat d'API. Miroir de backend/app/services/mesures.py.
//
// `verdict` est obligatoire et `nascet_pct` nullable : le compilateur refuse
// ainsi d'afficher une valeur sans son verdict. Une valeur sans statut se
// lirait comme une mesure ferme.

export type Verdict =
  | 'mesure'
  | 'mesure_incertaine'
  | 'pas_de_stenose'
  | 'non_calculable'
  | 'region_incompatible';

export interface Preuve {
  sections_totales: number | null;
  sections_retenues: number | null;
  pct_retenues: number | null;
  frac_vaisseau_pct: number | null;
  frac_voisinage_pct: number | null;
  hu_lumen_median: number | null;
  obliquite_mediane: number | null;
  espacement_mm: number | null;
  stenose_aire_pct: number | null;
}

export interface Axe {
  patient: string;
  cote: 'gauche' | 'droite';
  cohorte: 'etude' | 'clinique';
  verdict: Verdict;
  verdict_libelle: string;
  conduite: string;
  /** null dès que le verdict n'autorise pas la publication. */
  nascet_pct: number | null;
  /** Toujours 'basse' quand une valeur existe : la détection à mi-hauteur
   *  surestime le lumen résiduel d'environ 0,19 mm, donc SOUS-ESTIME la
   *  sténose. La valeur réelle est supérieure ou égale. */
  borne: 'basse' | null;
  nascet_corrige: number | null;
  /** Valeur brute et valeur débiaisée de part et d'autre de 70 % : deux
   *  conduites opposées pour un même axe. */
  alerte_seuil: boolean;
  d_min_mm: number | null;
  d_ref_mm: number | null;
  z_minimum: number | null;
  /** Indicatif, calculé même sur les refus. Ne jamais reporter dans un
   *  compte rendu — sert au tri de la file prioritaire. */
  nascet_implicite: number | null;
  cause?: string;
  cause_brute?: string;
  preuve?: Preuve;
  artefacts?: Record<string, string>;
}

export interface Recommandation {
  cote_le_plus_atteint: string;
  nascet_pct: number;
  au_dessus_seuil_symptomatique: boolean;
  au_dessus_seuil_asymptomatique: boolean;
  seuil_symptomatique: number;
  seuil_asymptomatique: number;
}

export interface FichePatient {
  patient: string;
  axes: Axe[];
  recommandation: Recommandation | null;
}

export type EtatTravail =
  | 'en_attente' | 'prevol' | 'conversion' | 'segmentation'
  | 'axe' | 'mesure' | 'termine' | 'echec' | 'annule';

export interface Travail {
  id: string;
  patient_id: string | null;
  /** Chemin complet du dossier déposé, et son nom seul — un radiologue
   *  reconnaît le dossier qu'il a choisi, pas un PatientID DICOM. */
  dossier_depot: string | null;
  dossier_nom: string | null;
  etat: EtatTravail;
  etape: string | null;
  progression: number;
  message: string | null;
  erreur: string | null;
  cree_le: string;
  duree_s: number | null;
  journal: { t: string; m: string }[];
  axes?: Axe[];
}

export interface SyntheseCohorte {
  cohorte: string;
  axes: number;
  patients: number;
  verdicts: { code: Verdict; libelle: string; n: number; pct: number }[];
  mediane_publiee: number | null;
  n_alertes_seuil: number;
  n_refus: number;
}

export interface Synthese {
  etude: SyntheseCohorte;
  clinique: SyntheseCohorte;
}

export interface Prevol {
  issue: 'recevable' | 'reserve' | 'refus';
  verdict: string | null;
  message: string;
  bloquants: string[];
  reserves: string[];
  indices: Record<string, unknown>;
}

export interface DossierDisponible {
  nom: string;
  chemin: string;
  fichiers: number;
}