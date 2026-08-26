import type { Axe, Verdict } from '../types/analysis';

/** Quatre verdicts, quatre couleurs. Pas d'accent unique : la couleur porte
 *  du sens, elle ne décore pas. */
export const COULEUR: Record<Verdict, string> = {
  mesure: '#63C9B4',
  mesure_incertaine: '#E0AB4E',
  pas_de_stenose: '#7E8CA0',
  non_calculable: '#E0705E',
  region_incompatible: '#7E8CA0',
};

export function PuceVerdict({ axe }: { axe: Axe }) {
  return (
    <span
      className="rounded px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-[#10141A]"
      style={{ background: COULEUR[axe.verdict] }}
    >
      {axe.verdict_libelle}
    </span>
  );
}

/**
 * Barre de réduction — l'élément signature.
 *
 * Trace d_ref et d_min à la MÊME échelle en millimètres, identique pour tous
 * les axes : deux carotides se comparent d'un coup d'œil. La différence
 * visible entre les deux traits EST le rapport NASCET, pas une représentation
 * de celui-ci.
 *
 * Sur un axe refusé, la barre passe en pointillé : la géométrie existe, la
 * mesure n'est pas publiable.
 */
export function BarreReduction({ axe, grand = false }: { axe: Axe; grand?: boolean }) {
  const { d_ref_mm: ref, d_min_mm: min } = axe;
  if (!ref || !min) return null;

  // 7 mm couvre le calibre d'une carotide interne saine.
  const ech = (mm: number) => Math.min(100, (100 * mm) / 7);
  const c = COULEUR[axe.verdict];
  const fantome = axe.nascet_pct === null;

  return (
    <div className={grand ? 'mt-5 max-w-xl' : 'mt-2'}>
      <div className={`relative ${grand ? 'h-6' : 'h-3'}`}>
        <div
          className="absolute left-0 top-0 h-full rounded-[1px] border border-[#39424F] bg-[#2B3340]"
          style={{ width: `${ech(ref)}%` }}
        />
        <div
          className="absolute left-0 top-0 h-full rounded-[1px] transition-[width] duration-300"
          style={{
            width: `${ech(min)}%`,
            background: fantome ? 'none' : c,
            border: fantome ? `1px dashed ${c}` : undefined,
            opacity: fantome ? 0.75 : 1,
          }}
        />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10.5px] text-[#8B97A8]">
        <span>d min {min.toFixed(2)} mm</span>
        <span>d réf {ref.toFixed(2)} mm</span>
      </div>
    </div>
  );
}

export const n1 = (x: number | null | undefined) =>
  x === null || x === undefined ? '—' : x.toFixed(1);
