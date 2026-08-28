import { useEffect, useState } from 'react';

import { api } from '../services/api';
import { BarreReduction, COULEUR, PuceVerdict, n1 } from '../components/Verdict';
import Loupe from '../components/Loupe';
import type { Axe, FichePatient as Fiche } from '../types/analysis';

/**
 * Fiche patient — l'écran que voit le radiologue après une analyse.
 *
 * Ce qui s'affiche n'est jamais un pourcentage seul, mais le quadruplet
 * (verdict, valeur, justification, pièce à conviction). Trois règles :
 *
 *   – aucune valeur sans son verdict ;
 *   – aucune valeur sans sa borne ;
 *   – aucun axe refusé masqué.
 */
export default function FichePatientPage({
  patient,
  onRetour,
}: {
  patient: string;
  onRetour?: () => void;
}) {
  const [fiche, setFiche] = useState<Fiche | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  // Le statut symptomatique n'est dans aucun DICOM : il faut le demander.
  // Les seuils d'indication chirurgicale en dépendent entièrement.
  const [symptomatique, setSymptomatique] = useState<boolean | null>(null);

  useEffect(() => {
    setFiche(null);
    setErreur(null);
    api.patient(patient).then(setFiche).catch((e) => setErreur(String(e)));
  }, [patient]);

  if (erreur) return <p className="p-8 text-[#E0705E]">{erreur}</p>;
  if (!fiche) return <p className="p-8 text-[#8B97A8]">Chargement…</p>;

  const r = fiche.recommandation;
  const seuil = symptomatique === null
    ? null
    : symptomatique ? r?.seuil_symptomatique : r?.seuil_asymptomatique;
  const auDessus = symptomatique === null || !r
    ? null
    : symptomatique ? r.au_dessus_seuil_symptomatique : r.au_dessus_seuil_asymptomatique;

  return (
    <div className="min-h-screen bg-[#191E26] p-6 text-[#DDE3EA] md:p-10">
      {onRetour && (
        <button
          onClick={onRetour}
          className="mb-5 text-[13px] text-[#8B97A8] hover:text-[#DDE3EA]"
        >
          ← Retour
        </button>
      )}

      <h1 className="font-mono text-2xl font-semibold">
        {fiche.patient}
        <span className="ml-3 text-base font-normal text-[#8B97A8]">
          {fiche.axes[0]?.cohorte === 'clinique' ? 'dossier clinique' : "cohorte d'étude"}
        </span>
      </h1>

      {/* ── Indication chirurgicale ─────────────────────────────────── */}
      <section className="mt-6 rounded border border-[#39424F] bg-[#222933] p-5">
        <h2 className="text-[11px] font-bold uppercase tracking-[0.1em] text-[#8B97A8]">
          Indication
        </h2>

        {!r ? (
          <p className="mt-3 max-w-2xl text-[#8B97A8]">
            Aucun ratio publiable sur ce patient. L'indication chirurgicale dépend
            du degré de sténose : sans mesure, elle ne peut pas être établie.
          </p>
        ) : (
          <>
            <div className="mt-4 flex flex-wrap items-center gap-3 text-[13px]">
              <span className="text-[#8B97A8]">Patient symptomatique ?</span>
              {([['Oui', true], ['Non', false]] as const).map(([lib, val]) => (
                <button
                  key={lib}
                  onClick={() => setSymptomatique(val)}
                  className={`rounded border px-3 py-1 ${
                    symptomatique === val
                      ? 'border-[#63C9B4] bg-[#63C9B4] font-semibold text-[#10141A]'
                      : 'border-[#39424F] text-[#8B97A8] hover:text-[#DDE3EA]'
                  }`}
                >
                  {lib}
                </button>
              ))}
            </div>

            {symptomatique === null ? (
              <p className="mt-4 max-w-2xl text-[13px] text-[#8B97A8]">
                Le seuil d'indication est de {r.seuil_symptomatique} % chez le patient
                symptomatique et de {r.seuil_asymptomatique} % sinon. Cette information
                ne figure dans aucun DICOM — elle doit être renseignée pour conclure.
              </p>
            ) : (
              <div className="mt-4">
                <p className="text-lg">
                  Côté le plus atteint :{' '}
                  <span className="font-mono font-semibold">
                    {r.cote_le_plus_atteint} ≥ {n1(r.nascet_pct)} %
                  </span>
                  <span className="text-[#8B97A8]"> · seuil {seuil} %</span>
                </p>
                <p
                  className="mt-2 text-xl font-semibold"
                  style={{ color: auDessus ? '#63C9B4' : '#7E8CA0' }}
                >
                  {auDessus ? 'Au-dessus du seuil d\u2019indication' : 'En dessous du seuil'}
                </p>
                <p className="mt-3 max-w-2xl text-[12px] leading-relaxed text-[#8B97A8]">
                  Seuils issus des essais randomisés NASCET et ECST. Ils encodent la
                  comparaison entre opérer et ne pas opérer — comparaison qu'aucune
                  donnée locale ne contient, tous les patients de la base ayant été
                  opérés. La décision reste au clinicien.
                </p>
              </div>
            )}
          </>
        )}
      </section>

      {/* ── Un bloc par carotide ────────────────────────────────────── */}
      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        {fiche.axes
          .sort((a, b) => a.cote.localeCompare(b.cote))
          .map((a) => (
            <BlocAxe key={a.cote} axe={a} />
          ))}
      </div>
    </div>
  );
}

function BlocAxe({ axe }: { axe: Axe }) {
  const c = COULEUR[axe.verdict];
  const p = axe.preuve;
  const figures = Object.entries(axe.artefacts ?? {});
  const [loupe, setLoupe] = useState<[string, string] | null>(null);

  return (
    <section className="rounded border border-[#39424F] bg-[#222933] p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-lg font-semibold">Carotide {axe.cote}</h2>
        <PuceVerdict axe={axe} />
      </div>
      <p className="mt-2 text-[13px] text-[#8B97A8]">{axe.conduite}</p>

      {/* La valeur, jamais nue : toujours avec son opérateur et sa borne. */}
      {axe.nascet_pct !== null && (
        <>
          <div className="mt-4 flex items-baseline gap-2 font-mono">
            <span className="text-2xl text-[#8B97A8]">≥</span>
            <span className="text-5xl font-semibold" style={{ color: c }}>
              {n1(axe.nascet_pct)}
            </span>
            <span className="text-xl text-[#8B97A8]">%</span>
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-[#8B97A8]">
            Borne basse. La détection de bord à mi-hauteur place le contour environ
            0,19 mm trop loin du centre : le lumen résiduel est surestimé, donc la
            sténose sous-estimée. La valeur réelle est supérieure ou égale.
          </p>
        </>
      )}

      {axe.alerte_seuil && (
        <div className="mt-4 border-l-[3px] border-[#E0AB4E] bg-[#E0AB4E]/10 px-4 py-3 text-[13px]">
          <b className="text-[#E0AB4E]">Franchit le seuil après correction du biais.</b>{' '}
          Valeur brute {n1(axe.nascet_pct)} %, corrigée {n1(axe.nascet_corrige)} %. Les
          deux tombent de part et d'autre de 70 % : la conduite diffère selon celle
          qu'on retient.
        </div>
      )}

      {axe.cause && (
        <div className="mt-4 border-l-[3px] border-[#E0705E] bg-[#E0705E]/10 px-4 py-3 text-[13px]">
          <b className="text-[#E0705E]">Pourquoi la mesure a été refusée.</b>
          <br />
          {axe.cause}
          {axe.z_minimum !== null && (
            <>
              <br />
              <br />
              Coupe à inspecter : <span className="font-mono">z = {axe.z_minimum}</span>.
              Le vaisseau et l'axe sont construits ; seule la mesure du bord échoue.
            </>
          )}
        </div>
      )}

      <BarreReduction axe={axe} grand />

      {p && (
        <>
          <h3 className="mt-6 border-b border-[#39424F] pb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-[#8B97A8]">
            Pièces à conviction
          </h3>
          <table className="mt-2 w-full text-[13px]">
            <tbody>
              {[
                ['Diamètre minimal', `${n1(axe.d_min_mm)} mm`],
                ['Diamètre de référence distal', `${n1(axe.d_ref_mm)} mm`],
                ['Coupe du minimum', axe.z_minimum ?? '—'],
                ['Sections retenues', `${p.sections_retenues ?? '—'} / ${p.sections_totales ?? '—'}`],
                ['Vaisseau exploitable', `${n1(p.frac_vaisseau_pct)} %`],
                ['Voisinage du minimum', `${n1(p.frac_voisinage_pct)} %`],
                ['Rehaussement luminal médian', `${n1(p.hu_lumen_median)} UH`],
                ['Obliquité médiane de l’axe', `${n1(p.obliquite_mediane)}°`],
              ].map(([k, v]) => (
                <tr key={String(k)} className="border-b border-[#39424F]">
                  <td className="py-1.5 text-[#8B97A8]">{k}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {figures.length > 0 && (
        <>
          <h3 className="mt-6 border-b border-[#39424F] pb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-[#8B97A8]">
            Images
          </h3>
          <div className="mt-2 grid grid-cols-2 gap-3">
            {figures.map(([nom, url]) => (
              <figure
                key={nom}
                className="overflow-hidden rounded border border-[#39424F] bg-black"
              >
                <button
                  onClick={() => setLoupe([url, nom])}
                  className="block w-full cursor-zoom-in"
                  aria-label={`Agrandir ${nom}`}
                >
                  <img src={url} alt={nom} loading="lazy" className="block w-full" />
                </button>
                <figcaption className="bg-[#222933] px-2 py-1 text-[10.5px] text-[#8B97A8]">
                  {nom}
                </figcaption>
              </figure>
            ))}
          </div>
        </>
      )}

      {loupe && (
        <Loupe url={loupe[0]} legende={loupe[1]} onFermer={() => setLoupe(null)} />
      )}
    </section>
  );
}
