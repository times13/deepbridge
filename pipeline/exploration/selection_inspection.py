#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selection_inspection.py — Selectionne les cas les plus representatifs de chaque
mode d'echec et indique OU regarder dans 3D Slicer.

Objectif : eviter de scroller a l'aveugle dans Slicer. Pour chaque cas retenu,
le script donne la coupe precise a inspecter (milieu du gap pour une
fragmentation, zone de chevauchement pour une fuite) et un plan d'observation
cible ("verifie si la 2e composante est la carotide externe", etc.).

Entree : les CSV produits par batch_components.py (diagnostic.csv + composantes.csv)

Sortie :
  - inspection.csv : la liste ordonnee des cas a ouvrir, avec coupe cible
  - affichage console : un plan d'inspection lisible, categorie par categorie

Usage :
  python selection_inspection.py --analyse "C:\\Projetsss\\analyse" ^
      --resultats "C:\\Projetsss" ^
      --par-categorie 2

  --par-categorie N : nombre de cas a retenir par mode d'echec (defaut 2)
  --resultats       : racine ou trouver les ct.nii.gz (pour afficher le chemin
                      exact a ouvrir dans Slicer). Facultatif.
"""

import argparse
import csv
import sys
from pathlib import Path


def lire_csv(chemin: Path) -> list:
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _f(v, defaut=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return defaut


def _i(v, defaut=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return defaut


def composantes_du_label(comps: list, patient: str, label: str) -> list:
    """Retourne les composantes SIGNIFICATIVES d'un label donne, triees par z."""
    sel = [c for c in comps
           if c["patient"] == patient and c["label"] == label
           and c["type"] == "SIGNIFICATIVE"]
    return sorted(sel, key=lambda c: _i(c["z_min"]))


def coupe_cible(diag: dict, comps_label: list) -> tuple:
    """Determine la coupe la plus interessante a inspecter selon le verdict.

    Retourne (z_cible, description_de_la_zone).
    """
    verdict = diag["verdict"]

    if verdict == "FRAGMENTATION_Z" and len(comps_label) >= 2:
        # Milieu du plus grand gap entre deux composantes consecutives
        meilleur_gap, z_gap = -1, None
        for a, b in zip(comps_label, comps_label[1:]):
            gap = _i(b["z_min"]) - _i(a["z_max"])
            if gap > meilleur_gap:
                meilleur_gap = gap
                z_gap = (_i(a["z_max"]) + _i(b["z_min"])) // 2
        return z_gap, f"milieu du gap (~{meilleur_gap} coupes manquantes)"

    if verdict in ("FUITE_INTER_LABEL", "MIXTE") and len(comps_label) >= 2:
        # Coupe ou deux composantes coexistent : on prend le milieu de la
        # plage de chevauchement des deux plus grosses composantes.
        gros = sorted(comps_label, key=lambda c: -_i(c["voxels"]))[:2]
        a, b = gros
        z0 = max(_i(a["z_min"]), _i(b["z_min"]))
        z1 = min(_i(a["z_max"]), _i(b["z_max"]))
        if z0 <= z1:
            return (z0 + z1) // 2, "zone ou 2 composantes coexistent (chevauchement)"
        # Pas de chevauchement en z malgre le verdict : on pointe la 2e composante
        return _i(b["z_min"]) + (_i(b["z_max"]) - _i(b["z_min"])) // 2, \
            "milieu de la 2e composante (structure a identifier)"

    if verdict == "PROPRE" and comps_label:
        c = comps_label[0]
        z_mid = (_i(c["z_min"]) + _i(c["z_max"])) // 2
        return z_mid, "milieu du vaisseau (controle : doit etre un lumen net)"

    # Repli
    if comps_label:
        c = comps_label[0]
        return (_i(c["z_min"]) + _i(c["z_max"])) // 2, "milieu de la 1re composante"
    return None, "aucune composante significative"


def score_representativite(diag: dict) -> float:
    """Score pour choisir les cas les PLUS clairs de chaque categorie.

    On privilegie les cas nets : pour une fragmentation, un gap franc ; pour une
    fuite, un decalage important ; pour un cas propre, un gros volume sans bruit.
    Un cas representatif est un cas ou le phenomene est evident a l'oeil, donc
    pedagogique pour valider le classement.
    """
    verdict = diag["verdict"]
    if verdict == "FRAGMENTATION_Z":
        # gap franc mais pas absurde (5-15 mm ideal), peu de bruit
        g = _f(diag["longueur_gaps_mm"])
        proximite_ideal = -abs(g - 9)  # 9 mm ~ ideal pedagogique
        return 100 + proximite_ideal - 5 * _i(diag["n_bruit"])
    if verdict == "FUITE_INTER_LABEL":
        # decalage lateral important = fuite evidente
        return 100 + _f(diag["decalage_max_mm"]) - 5 * _i(diag["n_bruit"])
    if verdict == "MIXTE":
        return 100 + _f(diag["decalage_max_mm"]) + _f(diag["longueur_gaps_mm"])
    if verdict == "PROPRE":
        # gros volume, zero bruit
        return _f(diag["volume_mm3"]) / 100 - 20 * _i(diag["n_bruit"])
    return 0.0


def trouver_ct(racine: Path, patient: str) -> Path:
    """Cherche le ct.nii.gz d'un patient sous la racine des resultats."""
    if racine is None:
        return None
    for motif in (racine / patient / "ct.nii.gz",
                  racine / "Resultats" / patient / "ct.nii.gz"):
        if motif.exists():
            return motif
    # recherche large
    for p in racine.rglob(f"{patient}/ct.nii.gz"):
        return p
    return None


def trouver_seg(racine: Path, patient: str) -> Path:
    if racine is None:
        return None
    for motif in (racine / patient / "seg",
                  racine / "Resultats" / patient / "seg"):
        if motif.is_dir():
            return motif
    for p in racine.rglob(f"{patient}/seg"):
        return p
    return None


# Plans d'observation cibles par categorie : quoi chercher precisement.
PLANS = {
    "FRAGMENTATION_Z": [
        "A la coupe cible, le lumen doit etre tres etroit ou absent (sténose).",
        "Remonte/descends de quelques coupes : le vaisseau reprend-il de part et",
        "  d'autre du trou ? Si oui = vraie fragmentation sur sténose serrée.",
        "Verifie qu'il n'y a pas de calcification massive (blanc dense) expliquant",
        "  le décrochage du masque.",
    ],
    "FUITE_INTER_LABEL": [
        "A la coupe cible, DEUX structures sont dans le label carotide interne.",
        "Identifie la 2e : est-ce la carotide EXTERNE (part vers l'avant/dehors,",
        "  se divise en branches) ou une autre artere ?",
        "Compare avec le cote controlateral s'il est PROPRE : la vraie CI est",
        "  celle dont la position correspond au cote sain en miroir.",
    ],
    "MIXTE": [
        "Cas cumulant fuite ET fragmentation : le plus complexe.",
        "Identifie d'abord la fuite (2 structures cote a cote), puis cherche",
        "  le gap axial sur la vraie carotide.",
        "C'est le cas qui dira si ton pipeline doit traiter la fuite AVANT",
        "  la fragmentation (probablement oui).",
    ],
    "PROPRE": [
        "Controle negatif : le masque doit coller au lumen sur toute la hauteur.",
        "Verifie qu'un cas 'PROPRE' est reellement exploitable pour NASCET :",
        "  lumen continu, pas de fuite discrete non detectee.",
    ],
}


def main():
    p = argparse.ArgumentParser(
        description="Selection des cas representatifs a inspecter dans Slicer")
    p.add_argument("--analyse", required=True, type=Path,
                   help="dossier contenant diagnostic.csv et composantes.csv")
    p.add_argument("--resultats", type=Path, default=None,
                   help="racine des resultats (pour afficher le chemin des ct.nii.gz)")
    p.add_argument("--par-categorie", type=int, default=2,
                   help="nombre de cas a retenir par categorie (defaut 2)")
    args = p.parse_args()

    f_diag = args.analyse / "diagnostic.csv"
    f_comp = args.analyse / "composantes.csv"
    if not f_diag.exists() or not f_comp.exists():
        sys.exit(f"[ERREUR] diagnostic.csv ou composantes.csv introuvable dans "
                 f"{args.analyse}")

    diagnostics = lire_csv(f_diag)
    composantes = lire_csv(f_comp)

    # Regroupement par verdict
    par_verdict = {}
    for d in diagnostics:
        par_verdict.setdefault(d["verdict"], []).append(d)

    # Selection des N plus representatifs par categorie
    ordre_categories = ["FRAGMENTATION_Z", "FUITE_INTER_LABEL", "MIXTE", "PROPRE"]
    selection = []
    for verdict in ordre_categories:
        cas = par_verdict.get(verdict, [])
        cas_tries = sorted(cas, key=score_representativite, reverse=True)
        selection.append((verdict, cas_tries[:args.par_categorie]))

    # --- Affichage console -------------------------------------------------
    print("\n" + "=" * 68)
    print("PLAN D'INSPECTION 3D SLICER — cas representatifs par mode d'echec")
    print("=" * 68)
    print("\nRappel : dans Slicer, charge d'abord le ct.nii.gz (Volume), puis le")
    print("masque carotide concerne (Segmentation ou Volume + colormap). Va a la")
    print("coupe indiquee via la reglette axiale ou le champ de coordonnees.")
    print("Le numero de coupe est l'index sur l'axe long du NIfTI.\n")

    lignes_csv = []
    for verdict, cas_liste in selection:
        if not cas_liste:
            continue
        print("\n" + "-" * 68)
        print(f"  {verdict}  ({len(par_verdict.get(verdict, []))} cas au total, "
              f"{len(cas_liste)} retenu(s))")
        print("-" * 68)

        for d in cas_liste:
            patient, label = d["patient"], d["label"]
            cote = "GAUCHE" if label.endswith("left") else "DROITE"
            comps_label = composantes_du_label(composantes, patient, label)
            z, zone = coupe_cible(d, comps_label)

            ct = trouver_ct(args.resultats, patient)
            seg = trouver_seg(args.resultats, patient)
            masque = (seg / f"{label}.nii.gz") if seg else None

            print(f"\n  >> {patient}  —  carotide interne {cote}")
            print(f"     verdict    : {verdict}")
            print(f"     detail     : {d['detail']}")
            if z is not None:
                print(f"     COUPE Z    : {z}   ({zone})")
            print(f"     composantes: {d['n_significatives']} significative(s), "
                  f"{d['n_bruit']} bruit")
            if verdict in ("FUITE_INTER_LABEL", "MIXTE"):
                print(f"     decalage   : {d['decalage_max_mm']} mm entre structures")
            if verdict in ("FRAGMENTATION_Z", "MIXTE"):
                print(f"     gap        : {d['longueur_gaps_mm']} mm")

            # Cote controlateral : utile pour identifier la vraie CI
            autre = "right" if label.endswith("left") else "left"
            label_autre = label.replace(
                "left" if label.endswith("left") else "right", autre)
            d_autre = next((x for x in diagnostics
                            if x["patient"] == patient and x["label"] == label_autre),
                           None)
            if d_autre:
                print(f"     cote oppose: {d_autre['verdict']} "
                      f"(reference miroir pour identifier la vraie CI)")

            if ct:
                print(f"     ouvrir CT  : {ct}")
            if masque and masque.exists():
                print(f"     + masque   : {masque}")

            lignes_csv.append({
                "categorie": verdict,
                "patient": patient,
                "cote": cote,
                "coupe_z": z if z is not None else "",
                "zone": zone,
                "detail": d["detail"],
                "gap_mm": d["longueur_gaps_mm"],
                "decalage_mm": d["decalage_max_mm"],
                "cote_oppose": d_autre["verdict"] if d_autre else "",
                "ct": str(ct) if ct else "",
                "masque": str(masque) if masque and masque.exists() else "",
            })

        # Plan d'observation de la categorie
        print(f"\n     Quoi regarder ({verdict}) :")
        for ligne in PLANS.get(verdict, []):
            print(f"       {ligne}")

    # --- Ecriture CSV ------------------------------------------------------
    if lignes_csv:
        f_out = args.analyse / "inspection.csv"
        with open(f_out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(lignes_csv[0].keys()),
                               delimiter=";")
            w.writeheader()
            w.writerows(lignes_csv)
        print("\n" + "=" * 68)
        print(f"  {len(lignes_csv)} cas a inspecter -> {f_out}")
        print("=" * 68)

    # --- Rappel methodologique --------------------------------------------
    print("\n  Ordre conseille : commence par un cas PROPRE (pour caler ton oeil")
    print("  sur ce qu'est un bon masque), puis FRAGMENTATION, puis FUITE, puis")
    print("  MIXTE. Note pour chaque cas si le verdict automatique est correct —")
    print("  c'est ta validation du classifieur, un resultat en soi pour le rapport.")


if __name__ == "__main__":
    main()