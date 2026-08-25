#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventory_dicom.py — Inventaire complet d'un dataset DICOM multi-patients.

But : savoir, AVANT de lancer TotalSegmentator sur 150 examens (des heures en CPU),
combien de series sont reellement exploitables pour un pipeline carotidien.

Ce script ne lit QUE les en-tetes DICOM (pas les pixels) : il est rapide.
Il produit deux CSV :
  - inventaire_series.csv : une ligne par serie, avec tous les criteres de tri
  - inventaire_patients.csv : une ligne par patient unique (PatientID reel)

Usage :
  python inventory_dicom.py --root "E:\\dataset_chu_nice_2020_2021\\scan" --out "C:\\Projetsss\\inventaire"

Options :
  --sample N     n'analyse que les N premiers dossiers (test rapide)
  --workers N    parallelisation (defaut 4)

Prerequis :
  pip install pydicom
"""

import argparse
import csv
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

try:
    import pydicom
    from pydicom.errors import InvalidDicomError
except ImportError:
    sys.exit("[ERREUR] pydicom manquant. Installe-le : pip install pydicom")


# --------------------------------------------------------------------------- #
# Criteres d'exploitabilite pour un pipeline carotidien
# --------------------------------------------------------------------------- #
EPAISSEUR_MAX_MM = 1.5      # au-dela, continuite en Z trop degradee
COUPES_MIN = 100            # en dessous, probablement un scout ou une repetition
MATRICE_MIN = 512           # matrice inferieure = resolution insuffisante

# Mots-cles de description de serie qui signalent une serie NON pertinente.
# La liste est volontairement large : mieux vaut ecarter trop que trop peu,
# la colonne 'description' du CSV permet de revenir dessus.
DESC_EXCLURE = (
    "scout", "localizer", "topogram", "surview", "dose", "report",
    "screen save", "secondary", "summary", "mip", "mpr", "vrt",
    "bone", "osseux", "perfusion", "dyn", "sub",
)

# Mots-cles qui signalent une serie angio cervicale pertinente.
DESC_INCLURE = (
    "angio", "cta", "tsa", "carotid", "carotide", "cou", "neck",
    "cervical", "vaisseaux", "polygone", "willis",
)


def _get(ds, name, default=""):
    """Lit un attribut DICOM sans lever d'exception si absent.

    Les tags multi-valeurs (PixelSpacing, ImagePositionPatient) sont des objets
    MultiValue pydicom : on les serialise en '/' pour l'affichage CSV.
    """
    try:
        v = getattr(ds, name, default)
        if v is None:
            return default
        # MultiValue n'est ni list ni tuple : on teste l'iterabilite non-string
        if not isinstance(v, str):
            try:
                return "/".join(str(x) for x in v)
            except TypeError:
                pass
        return str(v).strip()
    except Exception:
        return default


def _multi(ds, name):
    """Retourne un tag multi-valeurs sous forme de liste de float, ou []."""
    try:
        v = getattr(ds, name, None)
        if v is None:
            return []
        if isinstance(v, str):
            v = v.replace("\\", "/").split("/")
        return [float(x) for x in v]
    except (TypeError, ValueError):
        return []


def _float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def analyser_serie(serie_dir: Path) -> dict:
    """Analyse un dossier de serie : lit le 1er et le dernier fichier DICOM.

    Retourne un dict de metadonnees, ou None si le dossier ne contient pas
    de DICOM lisible.
    """
    fichiers = sorted(
        f for f in serie_dir.iterdir()
        if f.is_file() and not f.name.startswith(".")
    )
    if not fichiers:
        return None

    # Lecture du premier fichier lisible
    ds = None
    for f in fichiers[: min(5, len(fichiers))]:
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
            if _get(ds, "SOPClassUID"):
                break
        except (InvalidDicomError, OSError):
            continue
    if ds is None:
        return None

    n_fichiers = len(fichiers)

    # Etendue en Z : on lit le dernier fichier pour comparer la position.
    # ImagePositionPatient = [x, y, z] : la 3e valeur est la position axiale.
    z_premier = z_dernier = None
    ipp = _multi(ds, "ImagePositionPatient")
    if len(ipp) >= 3:
        z_premier = ipp[2]
    if n_fichiers > 1:
        try:
            ds_fin = pydicom.dcmread(str(fichiers[-1]), stop_before_pixels=True,
                                     force=True)
            ipp_fin = _multi(ds_fin, "ImagePositionPatient")
            if len(ipp_fin) >= 3:
                z_dernier = ipp_fin[2]
        except Exception:
            pass

    couverture_z = None
    if z_premier is not None and z_dernier is not None:
        couverture_z = round(abs(z_dernier - z_premier), 1)

    # Repli : si la position n'est pas lisible, on estime la couverture par
    # nombre de coupes x espacement inter-coupes.
    if couverture_z is None:
        sbs = _float(_get(ds, "SpacingBetweenSlices"))
        ep_ = _float(_get(ds, "SliceThickness"))
        pas = sbs if sbs else ep_
        if pas:
            couverture_z = round(n_fichiers * pas, 1)

    # Espacement dans le plan : PixelSpacing = [ligne, colonne] en mm
    ps = _multi(ds, "PixelSpacing")
    pixel_spacing = round(ps[0], 4) if ps else None

    epaisseur = _float(_get(ds, "SliceThickness"))
    rows = _float(_get(ds, "Rows"))
    cols = _float(_get(ds, "Columns"))
    description = _get(ds, "SeriesDescription")
    desc_bas = description.lower()
    contraste = _get(ds, "ContrastBolusAgent")
    modalite = _get(ds, "Modality").upper()

    # --- Classement automatique --------------------------------------------
    motifs_rejet = []

    if modalite != "CT":
        motifs_rejet.append(f"modalite={modalite or '?'}")

    if any(mot in desc_bas for mot in DESC_EXCLURE):
        motif = next(m for m in DESC_EXCLURE if m in desc_bas)
        motifs_rejet.append(f"description({motif})")

    if n_fichiers < COUPES_MIN:
        motifs_rejet.append(f"coupes={n_fichiers}")

    if epaisseur is not None and epaisseur > EPAISSEUR_MAX_MM:
        motifs_rejet.append(f"epaisseur={epaisseur}mm")

    if rows is not None and rows < MATRICE_MIN:
        motifs_rejet.append(f"matrice={int(rows)}")

    # Signaux positifs (informatifs, ne rejettent rien)
    signaux = []
    if any(mot in desc_bas for mot in DESC_INCLURE):
        signaux.append("desc_angio")
    if contraste:
        signaux.append("contraste")
    if couverture_z is not None and 100 <= couverture_z <= 400:
        signaux.append("couverture_cervicale")

    return {
        "chemin": str(serie_dir),
        "examen": serie_dir.parent.parent.name,
        "patient_id": _get(ds, "PatientID"),
        "etude_uid": _get(ds, "StudyInstanceUID"),
        "serie_uid": _get(ds, "SeriesInstanceUID"),
        "serie_num": _get(ds, "SeriesNumber"),
        "date_etude": _get(ds, "StudyDate"),
        "modalite": modalite,
        "description": description,
        "protocole": _get(ds, "ProtocolName"),
        "partie_corps": _get(ds, "BodyPartExamined"),
        "n_coupes": n_fichiers,
        "epaisseur_mm": epaisseur if epaisseur is not None else "",
        "pixel_spacing_mm": pixel_spacing if pixel_spacing is not None else "",
        "matrice": f"{int(rows)}x{int(cols)}" if rows and cols else "",
        "kvp": _get(ds, "KVP"),
        "contraste": contraste,
        "couverture_z_mm": couverture_z if couverture_z is not None else "",
        "annotation_incrustee": _get(ds, "BurnedInAnnotation"),
        "constructeur": _get(ds, "Manufacturer"),
        "modele": _get(ds, "ManufacturerModelName"),
        "exploitable": "OUI" if not motifs_rejet else "NON",
        "motifs_rejet": " | ".join(motifs_rejet),
        "signaux": " | ".join(signaux),
    }


def trouver_dossiers_series(root: Path) -> list:
    """Retourne les dossiers feuilles (ceux qui contiennent des fichiers, pas des
    sous-dossiers). Dans ton arborescence CHU Nice, ce sont les dossiers nommes
    par SeriesInstanceUID."""
    feuilles = []
    for d in root.rglob("*"):
        if not d.is_dir():
            continue
        a_des_fichiers = False
        a_des_sousdossiers = False
        try:
            for enfant in d.iterdir():
                if enfant.is_dir():
                    a_des_sousdossiers = True
                    break
                a_des_fichiers = True
        except (PermissionError, OSError):
            continue
        if a_des_fichiers and not a_des_sousdossiers:
            feuilles.append(d)
    return feuilles


def _worker(chemin_str):
    """Wrapper pour le pool de processus (doit etre au niveau module)."""
    try:
        return analyser_serie(Path(chemin_str))
    except Exception:
        return {"chemin": chemin_str, "erreur": traceback.format_exc(limit=1)}


def main():
    p = argparse.ArgumentParser(
        description="Inventaire DICOM d'un dataset multi-patients"
    )
    p.add_argument("--root", required=True, type=Path,
                   help="racine du dataset (ex: E:\\dataset_chu_nice_2020_2021\\scan)")
    p.add_argument("--out", required=True, type=Path,
                   help="dossier de sortie pour les CSV")
    p.add_argument("--sample", type=int, default=0,
                   help="n'analyser que les N premieres series (test rapide)")
    p.add_argument("--workers", type=int, default=4,
                   help="nombre de processus paralleles (defaut 4)")
    args = p.parse_args()

    if not args.root.exists():
        sys.exit(f"[ERREUR] Racine introuvable : {args.root}")
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] Recherche des dossiers de series sous {args.root} ...")
    dossiers = trouver_dossiers_series(args.root)
    print(f"[1/3] {len(dossiers)} dossier(s) feuille trouve(s)")

    if args.sample > 0:
        dossiers = dossiers[: args.sample]
        print(f"[1/3] Mode echantillon : {len(dossiers)} dossier(s) analyse(s)")

    if not dossiers:
        sys.exit("[ERREUR] Aucun dossier de serie trouve.")

    print(f"[2/3] Lecture des en-tetes ({args.workers} processus) ...")
    lignes = []
    erreurs = 0
    chemins = [str(d) for d in dossiers]

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_worker, c): c for c in chemins}
        for i, fut in enumerate(as_completed(futures), 1):
            res = fut.result()
            if res is None:
                continue
            if "erreur" in res:
                erreurs += 1
                continue
            lignes.append(res)
            if i % 50 == 0 or i == len(chemins):
                print(f"      {i}/{len(chemins)} traites, {len(lignes)} series valides")

    if not lignes:
        sys.exit("[ERREUR] Aucune serie DICOM lisible.")

    # --- Ecriture du CSV series -------------------------------------------
    lignes.sort(key=lambda r: (r.get("patient_id", ""), r.get("date_etude", ""),
                               -r.get("n_coupes", 0)))
    csv_series = args.out / "inventaire_series.csv"
    colonnes = list(lignes[0].keys())
    with open(csv_series, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colonnes, delimiter=";")
        w.writeheader()
        w.writerows(lignes)
    print(f"[3/3] {len(lignes)} series -> {csv_series}")

    # --- Agregation par patient -------------------------------------------
    patients = {}
    for r in lignes:
        pid = r.get("patient_id") or "INCONNU"
        p_ = patients.setdefault(pid, {
            "patient_id": pid,
            "n_series": 0,
            "n_series_exploitables": 0,
            "etudes": set(),
            "meilleure_serie": None,
            "meilleur_score": -1,
        })
        p_["n_series"] += 1
        p_["etudes"].add(r.get("date_etude", ""))
        if r["exploitable"] == "OUI":
            p_["n_series_exploitables"] += 1
            # Score de selection : coupes nombreuses + signaux angio
            score = r["n_coupes"] + 500 * len(r["signaux"].split("|")) if r["signaux"] else r["n_coupes"]
            if score > p_["meilleur_score"]:
                p_["meilleur_score"] = score
                p_["meilleure_serie"] = r

    lignes_patients = []
    for pid, p_ in sorted(patients.items()):
        best = p_["meilleure_serie"]
        lignes_patients.append({
            "patient_id": pid,
            "n_etudes": len(p_["etudes"]),
            "n_series": p_["n_series"],
            "n_series_exploitables": p_["n_series_exploitables"],
            "statut": "EXPLOITABLE" if p_["n_series_exploitables"] > 0 else "A_ECARTER",
            "serie_retenue": best["chemin"] if best else "",
            "serie_coupes": best["n_coupes"] if best else "",
            "serie_epaisseur": best["epaisseur_mm"] if best else "",
            "serie_description": best["description"] if best else "",
            "serie_signaux": best["signaux"] if best else "",
        })

    csv_patients = args.out / "inventaire_patients.csv"
    with open(csv_patients, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes_patients[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(lignes_patients)
    print(f"[3/3] {len(lignes_patients)} patients uniques -> {csv_patients}")

    # --- Resume console ----------------------------------------------------
    n_expl = sum(1 for l in lignes if l["exploitable"] == "OUI")
    n_pat_expl = sum(1 for l in lignes_patients if l["statut"] == "EXPLOITABLE")

    print("\n" + "=" * 62)
    print("RESUME")
    print("=" * 62)
    print(f"  Series analysees        : {len(lignes)}")
    print(f"  Series exploitables     : {n_expl} ({100*n_expl/len(lignes):.0f}%)")
    print(f"  Patients uniques        : {len(lignes_patients)}")
    print(f"  Patients exploitables   : {n_pat_expl} "
          f"({100*n_pat_expl/len(lignes_patients):.0f}%)")
    if erreurs:
        print(f"  Dossiers en erreur      : {erreurs}")

    # Motifs de rejet les plus frequents
    from collections import Counter
    motifs = Counter()
    for l in lignes:
        if l["exploitable"] == "NON":
            for m in l["motifs_rejet"].split(" | "):
                motifs[m.split("=")[0].split("(")[0]] += 1
    if motifs:
        print("\n  Motifs de rejet :")
        for m, n in motifs.most_common(8):
            print(f"    {m:24s} {n}")

    # Alerte annotations incrustees (risque RGPD)
    incrustees = [l for l in lignes if l["annotation_incrustee"].upper() == "YES"]
    if incrustees:
        print(f"\n  [!] {len(incrustees)} serie(s) avec BurnedInAnnotation=YES")
        print("      -> identifiants patient possiblement graves dans les pixels.")
        print("      -> a verifier visuellement AVANT toute diffusion.")

    print("\n  Etape suivante : ouvre inventaire_patients.csv, filtre sur")
    print("  statut=EXPLOITABLE, et utilise la colonne 'serie_retenue' comme")
    print("  entree pour le traitement par lot.")


if __name__ == "__main__":
    main()