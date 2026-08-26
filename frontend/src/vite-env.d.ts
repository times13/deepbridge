// Cornerstone ne publie pas de typages officiels. On declare les modules pour
// que tsc les accepte, sans typer une bibliotheque qu'on n'utilise pas encore.
//
// A remplacer par de vrais typages quand l'ecran de mesure manuelle sera
// construit — la conversion pixel/mm et le caliper meritent d'etre types.
declare module "cornerstone-core";
declare module "cornerstone-wado-image-loader";
declare module "dicom-parser";
