#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_components.py — Analyse des composantes connexes des masques carotidiens
produits par TotalSegmentator, sur un ou plusieurs patients.

But : identifier le MODE D'ECHEC dominant avant de concevoir le pipeline.
Trois modes possibles, que ce script distingue :

  1. FRAGMENTATION EN Z  : plusieurs composantes qui se suivent en Z sans se
     chevaucher, centroides alignes -> vraie rupture axiale du vaisseau.
  2. FUITE INTER-LABEL   : composantes qui se chevauchent en Z mais sont
     decalees lateralement -> structures differentes dans le meme label
     (CI + CE, ou CI + jugulaire).
  3. BRUIT               : petites composantes isolees (< seuil), a filtrer.

Sorties :
  - composantes.csv      : une ligne par composante (etendue, volume, centroide)
  - diagnostic.csv       : une ligne par label (verdict + metriques de synthese)
  - centroides.csv       : centroide par coupe et par composante (--centroides)
  - profils/*.png        : trace des centroides le long de Z (--figures)

Usage :
  # un seul patient
  python batch_components.py --seg "C:\\Projetsss\\Resultat_Test01\\seg" --out "C:\\Projetsss\\analyse"

  # tous les patients (dossiers de resultats cote a cote)
  python batch_components.py --root "C:\\Projetsss\\Resultats" --out "C:\\Projetsss\\analyse"

Prerequis :
  pip install nibabel numpy scipy matplotlib
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

try:
    import nibabel as nib
    from scipy import ndimage
except ImportError:
    sys.exit("[ERREUR] Dependances manquantes : pip install nibabel numpy scipy")


# Labels carotidiens produits par TotalSegmentator (tache headneck_bones_vessels).
# La nomenclature a change selon les versions : le script tolere les absents et
# detecte aussi tout fichier dont le nom contient "carotid".
LABELS_CAROTIDE = [
    "internal_carotid_artery_left",
    "internal_carotid_artery_right",
    "external_carotid_artery_left",
    "external_carotid_artery_right",
    "common_carotid_artery_left",
    "common_carotid_artery_right",
]

# Structures de reference pour detecter les fuites. La jugulaire interne est
# adjacente a la carotide, plus large, et rehaussee au temps veineux : c'est la
# confusion la plus probable. On teste aussi la jugulaire CONTROLATERALE (une
# composante carotidienne gauche qui touche la jugulaire droite signale une
# erreur de lateralite, pas une simple fuite de voisinage).
LABELS_REFERENCE = [
    "internal_jugular_vein_left",
    "internal_jugular_vein_right",
]

SEUIL_BRUIT_VOXELS = 100     # en dessous : composante consideree comme bruit
SEUIL_DECALAGE_MM = 6.0      # decalage lateral au-dela duquel on parle de fuite
SEUIL_CHEVAUCHEMENT_PCT = 20.0   # % de voxels dans une reference -> fuite avereee
SEUIL_PROXIMITE_MM = 3.0     # distance centroide-a-centroide jugee "collee"


def axe_z(img) -> int:
    """Determine l'indice de l'axe correspondant a la direction tete-pieds.

    On n'assume PAS que c'est l'axe 2 : selon l'orientation du NIfTI, ce peut
    etre un autre axe. On utilise les codes d'axe de l'affine.
    """
    try:
        codes = nib.aff2axcodes(img.affine)  # ex ('L','P','S')
        for i, c in enumerate(codes):
            if c in ("S", "I"):
                return i
    except Exception:
        pass
    return 2  # repli


def charger_references(dossier_seg: Path, forme_attendue) -> dict:
    """Charge les masques de reference (jugulaires) presents dans le dossier seg.

    Retourne {nom_label: tableau_booleen}. Les masques de forme incompatible
    sont ignores avec un avertissement plutot que de faire echouer l'analyse.
    """
    refs = {}
    for nom in LABELS_REFERENCE:
        f = dossier_seg / f"{nom}.nii.gz"
        if not f.exists():
            continue
        try:
            m = nib.load(str(f)).get_fdata() > 0.5
        except Exception as e:
            print(f"      [!] reference {nom} illisible : {e}")
            continue
        if m.shape != forme_attendue:
            print(f"      [!] reference {nom} de forme {m.shape}, attendu "
                  f"{forme_attendue} -> ignoree")
            continue
        if m.any():
            refs[nom] = m
    return refs


def tester_references(comp_masque, refs: dict, iz: int, axes_plan: list,
                      mm_plan: tuple) -> dict:
    """Confronte une composante aux masques de reference (jugulaires).

    Deux mesures complementaires :
      - chevauchement direct : % des voxels de la composante qui tombent DANS
        la reference. Un chevauchement franc = fuite averee.
      - proximite des centroides : une composante peut longer la jugulaire sans
        la chevaucher (segmentation qui deborde d'un cote). On mesure donc la
        distance mediane entre centroides, coupe par coupe, sur les coupes
        communes.

    Retourne un dict avec la reference la plus impliquee et ses metriques.
    """
    resultat = {
        "ref_principale": "",
        "chevauchement_pct": 0.0,
        "distance_mediane_mm": "",
        "verdict_ref": "OK",
    }
    if not refs:
        return resultat

    n_comp = int(comp_masque.sum())
    if n_comp == 0:
        return resultat

    meilleur = None
    for nom, ref in refs.items():
        inter = int(np.logical_and(comp_masque, ref).sum())
        pct = 100.0 * inter / n_comp

        # Distance entre centroides sur les coupes ou les deux existent
        distances = []
        z_comp = np.where(comp_masque.any(axis=tuple(axes_plan)))[0]
        z_ref = np.where(ref.any(axis=tuple(axes_plan)))[0]
        z_communs = np.intersect1d(z_comp, z_ref)
        # On echantillonne au plus 40 coupes : suffisant pour une mediane stable
        if len(z_communs) > 40:
            z_communs = z_communs[np.linspace(0, len(z_communs) - 1, 40).astype(int)]
        for z in z_communs:
            sl = [slice(None)] * 3
            sl[iz] = int(z)
            ca = comp_masque[tuple(sl)]
            cr = ref[tuple(sl)]
            if not ca.any() or not cr.any():
                continue
            ia, ir = np.argwhere(ca), np.argwhere(cr)
            d = np.hypot((ia[:, 0].mean() - ir[:, 0].mean()) * mm_plan[0],
                         (ia[:, 1].mean() - ir[:, 1].mean()) * mm_plan[1])
            distances.append(d)

        d_med = float(np.median(distances)) if distances else float("nan")
        # On retient la reference la plus problematique : d'abord le
        # chevauchement, puis a chevauchement egal la plus proche.
        score = (pct, -d_med if d_med == d_med else -999)
        if meilleur is None or score > meilleur[0]:
            meilleur = (score, nom, pct, d_med)

    if meilleur is None:
        return resultat

    _, nom, pct, d_med = meilleur
    resultat["ref_principale"] = nom
    resultat["chevauchement_pct"] = round(pct, 1)
    resultat["distance_mediane_mm"] = round(d_med, 2) if d_med == d_med else ""

    if pct >= SEUIL_CHEVAUCHEMENT_PCT:
        resultat["verdict_ref"] = "FUITE_JUGULAIRE"
    elif pct > 0:
        resultat["verdict_ref"] = "CONTACT_JUGULAIRE"
    elif d_med == d_med and d_med < SEUIL_PROXIMITE_MM:
        resultat["verdict_ref"] = "ADJACENT_JUGULAIRE"

    return resultat


def analyser_label(chemin_nii: Path, patient: str, refs: dict = None) -> tuple:
    """Analyse un masque binaire : composantes connexes + centroides par coupe.

    Si 'refs' est fourni (masques jugulaires), chaque composante est confrontee
    a ces references pour distinguer une vraie carotide d'une fuite veineuse.

    Retourne (lignes_composantes, ligne_diagnostic, dict_contexte).
    """
    refs = refs or {}
    img = nib.load(str(chemin_nii))
    data = img.get_fdata()
    masque = data > 0.5

    label_nom = chemin_nii.name.replace(".nii.gz", "").replace(".nii", "")
    zooms = img.header.get_zooms()[:3]
    iz = axe_z(img)
    # Les deux axes du plan de coupe
    axes_plan = [a for a in range(3) if a != iz]
    mm_plan = (zooms[axes_plan[0]], zooms[axes_plan[1]])
    mm_z = zooms[iz]

    if not masque.any():
        diag = {
            "patient": patient, "label": label_nom, "verdict": "MASQUE_VIDE",
            "n_composantes": 0, "n_significatives": 0, "n_bruit": 0,
            "volume_mm3": 0, "z_min": "", "z_max": "", "etendue_z_mm": "",
            "n_gaps": 0, "longueur_gaps_mm": 0, "n_chevauchements": 0,
            "decalage_max_mm": "",
            "n_fuites_jugulaire": 0, "n_contacts_jugulaire": 0,
            "n_adjacents_jugulaire": 0, "chevauchement_jugulaire_max_pct": 0.0,
            "refs_disponibles": len(refs),
            "detail": "aucun voxel segmente",
        }
        return [], diag, {}

    # Connectivite 26 (full 3D) : la plus permissive, evite de fragmenter
    # artificiellement un vaisseau oblique.
    structure = np.ones((3, 3, 3), dtype=bool)
    etiquettes, n = ndimage.label(masque, structure=structure)

    composantes = []
    centroides = {}

    for i in range(1, n + 1):
        comp = etiquettes == i
        taille = int(comp.sum())

        indices = np.argwhere(comp)
        zmin, zmax = int(indices[:, iz].min()), int(indices[:, iz].max())

        # Centroide global (dans le plan de coupe)
        c0 = float(indices[:, axes_plan[0]].mean())
        c1 = float(indices[:, axes_plan[1]].mean())

        # Centroide par coupe : c'est LA donnee qui permet de distinguer
        # fragmentation (centroides alignes) de fuite (centroides ecartes).
        centro_par_z = {}
        for z in range(zmin, zmax + 1):
            sl = [slice(None)] * 3
            sl[iz] = z
            coupe = comp[tuple(sl)]
            if not coupe.any():
                continue
            idx = np.argwhere(coupe)
            centro_par_z[z] = (float(idx[:, 0].mean()),
                               float(idx[:, 1].mean()),
                               int(coupe.sum()))
        centroides[i] = centro_par_z

        # Confrontation aux masques de reference (jugulaires)
        ref_res = tester_references(comp, refs, iz, axes_plan, mm_plan)

        composantes.append({
            "patient": patient,
            "label": label_nom,
            "composante": i,
            "voxels": taille,
            "volume_mm3": round(taille * zooms[0] * zooms[1] * zooms[2], 1),
            "z_min": zmin,
            "z_max": zmax,
            "etendue_z": zmax - zmin + 1,
            "etendue_z_mm": round((zmax - zmin + 1) * mm_z, 1),
            "centroide_a": round(c0, 1),
            "centroide_b": round(c1, 1),
            "type": "BRUIT" if taille < SEUIL_BRUIT_VOXELS else "SIGNIFICATIVE",
            "ref_principale": ref_res["ref_principale"],
            "chevauchement_ref_pct": ref_res["chevauchement_pct"],
            "distance_ref_mm": ref_res["distance_mediane_mm"],
            "verdict_ref": ref_res["verdict_ref"],
        })

    significatives = [c for c in composantes if c["type"] == "SIGNIFICATIVE"]
    bruit = [c for c in composantes if c["type"] == "BRUIT"]

    # --- Detection des gaps et chevauchements ------------------------------
    # On ne raisonne QUE sur les composantes significatives : le bruit fausse
    # tout le diagnostic.
    sig_tries = sorted(significatives, key=lambda c: c["z_min"])
    gaps = []
    chevauchements = []
    decalage_max = 0.0

    for a, b in zip(sig_tries, sig_tries[1:]):
        if b["z_min"] > a["z_max"] + 1:
            # Trou en Z : candidat fragmentation
            longueur = (b["z_min"] - a["z_max"] - 1)
            # Le decalage lateral entre l'extremite de a et le debut de b
            # permet de savoir si les deux morceaux sont dans le prolongement
            # l'un de l'autre (vraie fragmentation) ou non.
            ca = centroides[a["composante"]].get(a["z_max"])
            cb = centroides[b["composante"]].get(b["z_min"])
            if ca and cb:
                d = np.hypot((ca[0] - cb[0]) * mm_plan[0],
                             (ca[1] - cb[1]) * mm_plan[1])
            else:
                d = float("nan")
            gaps.append({
                "de": a["composante"], "vers": b["composante"],
                "z_debut": a["z_max"], "z_fin": b["z_min"],
                "longueur_coupes": longueur,
                "longueur_mm": round(longueur * mm_z, 1),
                "decalage_mm": round(d, 2) if d == d else "",
            })
        else:
            # Chevauchement en Z : candidat fuite inter-label
            z_communs = range(max(a["z_min"], b["z_min"]),
                              min(a["z_max"], b["z_max"]) + 1)
            distances = []
            for z in z_communs:
                ca = centroides[a["composante"]].get(z)
                cb = centroides[b["composante"]].get(z)
                if ca and cb:
                    distances.append(np.hypot((ca[0] - cb[0]) * mm_plan[0],
                                              (ca[1] - cb[1]) * mm_plan[1]))
            d_moy = float(np.mean(distances)) if distances else float("nan")
            if distances:
                decalage_max = max(decalage_max, max(distances))
            chevauchements.append({
                "comp_a": a["composante"], "comp_b": b["composante"],
                "n_coupes_communes": len(list(z_communs)),
                "decalage_moyen_mm": round(d_moy, 2) if d_moy == d_moy else "",
            })

    # --- Bilan des fuites jugulaires ---------------------------------------
    # Priorite au diagnostic de fuite : si une composante significative tombe
    # dans la jugulaire, ce n'est pas un probleme de fragmentation mais
    # d'identification de structure, et ca change entierement la strategie.
    fuites = [c for c in significatives if c["verdict_ref"] == "FUITE_JUGULAIRE"]
    contacts = [c for c in significatives if c["verdict_ref"] == "CONTACT_JUGULAIRE"]
    adjacents = [c for c in significatives if c["verdict_ref"] == "ADJACENT_JUGULAIRE"]

    # --- Verdict -----------------------------------------------------------
    if len(significatives) == 0:
        verdict = "BRUIT_SEUL"
        detail = f"{len(bruit)} composante(s), toutes sous {SEUIL_BRUIT_VOXELS} voxels"
    elif fuites:
        verdict = "FUITE_JUGULAIRE"
        ids = ", ".join(f"#{c['composante']}({c['chevauchement_ref_pct']}%)"
                        for c in fuites)
        detail = (f"{len(fuites)} composante(s) dans la jugulaire : {ids} "
                  f"-> le masque melange artere et veine")
    elif len(significatives) == 1:
        verdict = "PROPRE"
        detail = "une seule composante significative, pas de fragmentation"
    elif chevauchements and not gaps:
        verdict = "FUITE_INTER_LABEL"
        detail = (f"{len(chevauchements)} paire(s) chevauchante(s), "
                  f"decalage max {decalage_max:.1f}mm -> structures distinctes "
                  f"dans le meme label")
    elif gaps and not chevauchements:
        verdict = "FRAGMENTATION_Z"
        total_mm = sum(g["longueur_mm"] for g in gaps)
        detail = f"{len(gaps)} gap(s), {total_mm:.1f}mm manquants au total"
    else:
        verdict = "MIXTE"
        detail = (f"{len(gaps)} gap(s) ET {len(chevauchements)} "
                  f"chevauchement(s) -> les deux modes coexistent")

    z_tous = [c["z_min"] for c in composantes] + [c["z_max"] for c in composantes]
    diag = {
        "patient": patient,
        "label": label_nom,
        "verdict": verdict,
        "n_composantes": n,
        "n_significatives": len(significatives),
        "n_bruit": len(bruit),
        "volume_mm3": round(sum(c["volume_mm3"] for c in significatives), 1),
        "z_min": min(z_tous),
        "z_max": max(z_tous),
        "etendue_z_mm": round((max(z_tous) - min(z_tous) + 1) * mm_z, 1),
        "n_gaps": len(gaps),
        "longueur_gaps_mm": round(sum(g["longueur_mm"] for g in gaps), 1),
        "n_chevauchements": len(chevauchements),
        "decalage_max_mm": round(decalage_max, 2) if decalage_max else "",
        "n_fuites_jugulaire": len(fuites),
        "n_contacts_jugulaire": len(contacts),
        "n_adjacents_jugulaire": len(adjacents),
        "chevauchement_jugulaire_max_pct": round(
            max((c["chevauchement_ref_pct"] for c in significatives), default=0.0), 1),
        "refs_disponibles": len(refs),
        "detail": detail,
    }

    return composantes, diag, {"centroides": centroides, "gaps": gaps,
                               "chevauchements": chevauchements,
                               "iz": iz, "mm_z": mm_z, "mm_plan": mm_plan}


def tracer_profil(patient, label_nom, contexte, composantes, dossier_fig):
    """Trace les centroides de chaque composante le long de Z.

    Deux morceaux d'une meme artere -> courbes qui se prolongent.
    Deux arteres distinctes -> courbes paralleles decalees.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    centroides = contexte["centroides"]
    sig = {c["composante"] for c in composantes if c["type"] == "SIGNIFICATIVE"}
    if not sig:
        return

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    couleurs = plt.cm.tab10(np.linspace(0, 1, 10))

    for i, (comp_id, par_z) in enumerate(sorted(centroides.items())):
        if not par_z:
            continue
        est_sig = comp_id in sig
        zs = sorted(par_z.keys())
        a = [par_z[z][0] for z in zs]
        b = [par_z[z][1] for z in zs]
        aire = [par_z[z][2] for z in zs]
        style = dict(color=couleurs[i % 10],
                     alpha=1.0 if est_sig else 0.35,
                     linewidth=2.0 if est_sig else 1.0,
                     linestyle="-" if est_sig else ":")
        etiq = f"comp {comp_id}" + ("" if est_sig else " (bruit)")
        axes[0].plot(zs, a, label=etiq, **style)
        axes[1].plot(zs, b, label=etiq, **style)
        axes[2].plot(zs, aire, label=etiq, **style)

    axes[0].set_title("Centroide — axe plan 1")
    axes[1].set_title("Centroide — axe plan 2")
    axes[2].set_title("Aire par coupe (voxels)")
    for ax in axes:
        ax.set_xlabel("coupe (axe Z)")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("position (voxels)")
    axes[2].set_ylabel("voxels")
    axes[0].legend(fontsize=7)

    fig.suptitle(f"{patient} — {label_nom}", fontsize=11)
    fig.tight_layout()
    chemin = dossier_fig / f"{patient}_{label_nom}.png"
    fig.savefig(chemin, dpi=120)
    plt.close(fig)


def trouver_dossiers_seg(root: Path) -> list:
    """Trouve tous les dossiers 'seg' sous une racine de resultats."""
    if root.name == "seg":
        return [root]
    dossiers = [d for d in root.rglob("seg") if d.is_dir()]
    if not dossiers:
        # peut-etre que les .nii.gz sont directement sous root
        if any(root.glob("*carotid*.nii.gz")):
            return [root]
    return dossiers


def main():
    p = argparse.ArgumentParser(
        description="Analyse des composantes connexes carotidiennes"
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--seg", type=Path, help="un seul dossier seg")
    g.add_argument("--root", type=Path,
                   help="racine contenant plusieurs dossiers de resultats")
    p.add_argument("--out", required=True, type=Path, help="dossier de sortie")
    p.add_argument("--figures", action="store_true",
                   help="genere les traces de centroides (PNG)")
    p.add_argument("--centroides", action="store_true",
                   help="exporte le CSV des centroides par coupe (volumineux)")
    p.add_argument("--seuil-bruit", type=int, default=100,
                   help="seuil voxels sous lequel une composante est du bruit "
                        "(defaut 100)")
    p.add_argument("--sans-jugulaire", action="store_true",
                   help="desactive la confrontation aux masques jugulaires "
                        "(plus rapide, mais perd le diagnostic de fuite veineuse)")
    args = p.parse_args()

    globals()["SEUIL_BRUIT_VOXELS"] = args.seuil_bruit

    args.out.mkdir(parents=True, exist_ok=True)
    dossier_fig = args.out / "profils"
    if args.figures:
        dossier_fig.mkdir(exist_ok=True)

    racine = args.seg if args.seg else args.root
    dossiers_seg = trouver_dossiers_seg(racine)
    if not dossiers_seg:
        sys.exit(f"[ERREUR] Aucun dossier 'seg' trouve sous {racine}")
    print(f"[1/3] {len(dossiers_seg)} dossier(s) de segmentation trouve(s)")

    toutes_composantes = []
    tous_diagnostics = []
    lignes_centroides = []

    for k, dseg in enumerate(dossiers_seg, 1):
        # Nom du patient = dossier parent du dossier seg
        patient = dseg.parent.name if dseg.name == "seg" else dseg.name

        fichiers = []
        for nom in LABELS_CAROTIDE:
            f = dseg / f"{nom}.nii.gz"
            if f.exists():
                fichiers.append(f)
        # Filet de securite : tout autre fichier contenant "carotid"
        for f in dseg.glob("*carotid*.nii.gz"):
            if f not in fichiers:
                fichiers.append(f)

        if not fichiers:
            print(f"  [{k}/{len(dossiers_seg)}] {patient} : aucun masque carotidien")
            continue

        # Chargement des references (jugulaires) : une seule fois par dossier,
        # les masques sont volumineux. La forme est celle du premier masque
        # carotidien, qui sert de reference de compatibilite.
        refs = {}
        if not args.sans_jugulaire:
            try:
                forme = nib.load(str(fichiers[0])).shape
                refs = charger_references(dseg, forme)
            except Exception as e:
                print(f"      [!] chargement references : {e}")

        etat_ref = (f"{len(refs)} ref. jugulaire" if refs
                    else "sans ref. jugulaire")
        print(f"  [{k}/{len(dossiers_seg)}] {patient} : {len(fichiers)} label(s), "
              f"{etat_ref}")

        for f in fichiers:
            try:
                comps, diag, ctx = analyser_label(f, patient, refs)
            except Exception as e:
                print(f"      [!] {f.name} : {e}")
                continue

            toutes_composantes.extend(comps)
            tous_diagnostics.append(diag)

            marque = {"PROPRE": "  ", "FRAGMENTATION_Z": "->",
                      "FUITE_INTER_LABEL": "!!", "FUITE_JUGULAIRE": "!!",
                      "MIXTE": "!!", "MASQUE_VIDE": "xx",
                      "BRUIT_SEUL": "xx"}.get(diag["verdict"], "  ")
            print(f"      {marque} {diag['label']:38s} {diag['verdict']:20s} "
                  f"({diag['n_significatives']} sig. / {diag['n_bruit']} bruit)")

            # Detail des composantes en contact avec la jugulaire : c'est
            # l'information qui permet d'identifier LA composante fautive.
            for c in comps:
                if c["verdict_ref"] in ("FUITE_JUGULAIRE", "CONTACT_JUGULAIRE"):
                    print(f"         comp #{c['composante']:2d} "
                          f"({c['voxels']:6d} vox) -> {c['verdict_ref']} "
                          f"{c['chevauchement_ref_pct']}% dans "
                          f"{c['ref_principale'].replace('internal_jugular_vein_', 'jug.')}")

            if args.figures and ctx:
                try:
                    tracer_profil(patient, diag["label"], ctx, comps, dossier_fig)
                except Exception as e:
                    print(f"      [!] figure : {e}")

            if args.centroides and ctx:
                for comp_id, par_z in ctx["centroides"].items():
                    for z, (a, b, aire) in sorted(par_z.items()):
                        lignes_centroides.append({
                            "patient": patient, "label": diag["label"],
                            "composante": comp_id, "z": z,
                            "centroide_a": round(a, 2), "centroide_b": round(b, 2),
                            "aire_voxels": aire,
                        })

    if not tous_diagnostics:
        sys.exit("[ERREUR] Aucun masque analyse.")

    # --- Ecriture des CSV --------------------------------------------------
    f_comp = args.out / "composantes.csv"
    if toutes_composantes:
        with open(f_comp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(toutes_composantes[0].keys()),
                               delimiter=";")
            w.writeheader()
            w.writerows(toutes_composantes)
        print(f"\n[2/3] {len(toutes_composantes)} composantes -> {f_comp}")

    f_diag = args.out / "diagnostic.csv"
    with open(f_diag, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(tous_diagnostics[0].keys()),
                           delimiter=";")
        w.writeheader()
        w.writerows(tous_diagnostics)
    print(f"[2/3] {len(tous_diagnostics)} diagnostics -> {f_diag}")

    if lignes_centroides:
        f_cent = args.out / "centroides.csv"
        with open(f_cent, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(lignes_centroides[0].keys()),
                               delimiter=";")
            w.writeheader()
            w.writerows(lignes_centroides)
        print(f"[2/3] {len(lignes_centroides)} centroides -> {f_cent}")

    # --- Synthese ----------------------------------------------------------
    from collections import Counter
    verdicts = Counter(d["verdict"] for d in tous_diagnostics)

    print("\n" + "=" * 62)
    print("SYNTHESE — MODE D'ECHEC DOMINANT")
    print("=" * 62)
    total = len(tous_diagnostics)
    for v, n in verdicts.most_common():
        print(f"  {v:22s} {n:4d}  ({100*n/total:5.1f}%)")

    gaps_tot = sum(d["n_gaps"] for d in tous_diagnostics)
    chev_tot = sum(d["n_chevauchements"] for d in tous_diagnostics)
    fuites_tot = sum(d["n_fuites_jugulaire"] for d in tous_diagnostics)
    contacts_tot = sum(d["n_contacts_jugulaire"] for d in tous_diagnostics)
    adj_tot = sum(d["n_adjacents_jugulaire"] for d in tous_diagnostics)
    sans_ref = sum(1 for d in tous_diagnostics if d["refs_disponibles"] == 0)

    print(f"\n  Gaps en Z (total)          : {gaps_tot}")
    print(f"  Chevauchements (total)     : {chev_tot}")

    if gaps_tot:
        longueurs = [d["longueur_gaps_mm"] for d in tous_diagnostics if d["n_gaps"]]
        print(f"  Longueur mediane de gap    : {np.median(longueurs):.1f} mm")

    print(f"\n  Composantes dans la jugulaire (fuite)   : {fuites_tot}")
    print(f"  Composantes en contact jugulaire        : {contacts_tot}")
    print(f"  Composantes adjacentes (<{SEUIL_PROXIMITE_MM}mm, sans contact) : {adj_tot}")
    if sans_ref:
        print(f"  [!] {sans_ref} label(s) analyse(s) sans reference jugulaire "
              f"disponible -> diagnostic de fuite impossible sur ces cas")

    print("\n  Interpretation :")
    dominant = verdicts.most_common(1)[0][0]
    if dominant == "FUITE_JUGULAIRE":
        print("    Le masque carotidien englobe de la jugulaire interne. Ce n'est")
        print("    ni de la fragmentation ni un probleme de continuite : le modele")
        print("    confond artere et veine. Aucune approche de reconnexion ne")
        print("    corrigera ca. Deux pistes : filtrer les composantes par")
        print("    soustraction du masque jugulaire, ou repasser sur une serie")
        print("    au temps arteriel si le CTA disponible est trop tardif.")
    elif dominant == "FUITE_INTER_LABEL":
        print("    Le probleme principal N'EST PAS la fragmentation axiale mais")
        print("    la confusion entre structures (CI/CE/jugulaire). Une approche")
        print("    par centerline + polaire ne suffira pas seule : il faut d'abord")
        print("    resoudre l'attribution de label.")
    elif dominant == "FRAGMENTATION_Z":
        print("    Fragmentation axiale confirmee comme mode dominant. L'approche")
        print("    centerline + reechantillonnage polaire attaque directement la")
        print("    cause. Priorite a l'interpolation d'axe a travers les gaps.")
    elif dominant == "PROPRE":
        print("    TotalSegmentator produit des masques propres sur la majorite")
        print("    des cas. Concentre l'effort sur le sous-ensemble en echec")
        print("    (filtre diagnostic.csv sur verdict != PROPRE).")
    elif dominant == "MIXTE":
        print("    Les deux modes coexistent. Traite d'abord la fuite inter-label")
        print("    (elle fausse la detection de gap), puis la fragmentation.")
    else:
        print("    Beaucoup de masques vides ou de bruit : verifie que la bonne")
        print("    tache TotalSegmentator a ete utilisee et que la serie d'entree")
        print("    est bien un CTA cervical.")

    print("\n  Etape suivante : ouvre diagnostic.csv, trie par verdict, et")
    print("  inspecte 2-3 cas de chaque categorie dans 3D Slicer avant de coder.")


if __name__ == "__main__":
    main()