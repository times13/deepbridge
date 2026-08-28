import { useEffect } from 'react';

/**
 * Visionneuse plein écran.
 *
 * Les figures de etape2c/etape2d sont denses — profils de diamètre, coupes
 * multiples, projections. En vignette on voit qu'il y a quelque chose ; en
 * grand on voit quoi. Or c'est précisément sur ces images que se juge la
 * validité d'un axe.
 *
 * Sans dépendance : une div en position fixe, fermée par Échap ou par clic.
 */
export default function Loupe({
  url,
  legende,
  onFermer,
}: {
  url: string;
  legende: string;
  onFermer: () => void;
}) {
  // Échap ferme, et le défilement du fond est bloqué pendant l'affichage.
  useEffect(() => {
    const onTouche = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onFermer();
    };
    window.addEventListener('keydown', onTouche);
    const avant = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onTouche);
      document.body.style.overflow = avant;
    };
  }, [onFermer]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={legende}
      onClick={onFermer}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/92 p-4"
    >
      <img
        src={url}
        alt={legende}
        // stopPropagation : cliquer l'image ne ferme pas, seul le fond ferme.
        onClick={(e) => e.stopPropagation()}
        className="max-h-[88vh] max-w-full cursor-default object-contain"
      />
      <div className="mt-3 flex items-center gap-5 text-[12px] text-[#8B97A8]">
        <span className="font-mono">{legende}</span>
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="hover:text-[#DDE3EA]"
        >
          ouvrir dans un onglet ↗
        </a>
        <span>Échap ou clic pour fermer</span>
      </div>
    </div>
  );
}
