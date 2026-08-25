#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etape2_centerline.py — DeepBridge, etape 2 / increment 1.

Extrait la CENTERLINE (axe central) d'une carotide interne a partir du masque
TotalSegmentator, la lisse, la reechantillonne a pas constant en millimetres,
et calcule la tangente en chaque point.

Pourquoi la centerline d'abord : toute la suite (coupes perpendiculaires,
profils radiaux, FWHM) se construit sur cet axe. Si l'axe est faux ou bruite,
les diametres le seront aussi. On la valide donc seule, avec des PNG de
controle, avant d'aller plus loin.

Ce script ne fait PAS encore de mesure FWHM. Il produit en bonus un profil de
diametre NAIF (a partir de l'aire du masque coupe par coupe) dont le seul but
est de montrer l'ampleur du biais d'obliquite qu'on va corriger a l'increment 2.

Sorties (dans <out>/<patient>_<cote>/) :
  centerline.csv        axe reechantillonne : position, coordonnees, tangente
  01_projections.png    masque projete + centerline superposee (controle visuel)
  02_lissage.png        coordonnees brutes vs lissees (controle du lissage)
  03_coupes.png         6 coupes axiales CT + contour du masque + centroide
  04_diametre_naif.png  diametre naif et angle d'obliquite le long de l'axe

Usage :
  python etape2_centerline.py --patient "C:\\Projetsss\\Resultats\\1359673019" ^
                              --cote gauche --out "C:\\Projetsss\\etape2"

Prerequis : nibabel, numpy, scipy, matplotlib  (deja installes dans ts_test)
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

try:
    import nibabel as nib
    from scipy import ndimage
    from scipy.interpolate import CubicSpline, interp1d
    from scipy.signal import savgol_filter
except ImportError:
    sys.exit("[ERREUR] Dependances : pip install nibabel numpy scipy matplotlib")

import matplotlib
matplotlib.use("Agg")          # backend sans fenetre : indispensable en CLI
import matplotlib.pyplot as plt


COTES = {"gauche": "left", "droite": "right"}
SEUIL_ANGLE_ALERTE = 45.0      # au-dela, le centroide par coupe devient douteux


# ---------------------------------------------------------------------------
# Geometrie NIfTI
# ---------------------------------------------------------------------------

def axe_z(img) -> int:
    """Indice de l'axe tete-pieds. Repris de batch_components.py.

    Un volume NIfTI est un tableau 3D dont les axes ne sont PAS forcement
    (x, y, z) anatomiques : l'affine dit comment passer des indices de voxel
    aux millimetres dans le repere du scanner. aff2axcodes traduit ca en
    lettres ('L','P','S' = axe 0 vers la Gauche, axe 1 vers l'arriere,
    axe 2 vers le haut). On cherche l'axe porteur de S (Superior) ou I.
    """
    try:
        for i, c in enumerate(nib.aff2axcodes(img.affine)):
            if c in ("S", "I"):
                return i
    except Exception:
        pass
    return 2


def coupe_2d(dataobj, iz: int, z: int) -> np.ndarray:
    """Extrait une coupe perpendiculaire a l'axe iz SANS charger tout le volume.

    dataobj est le proxy nibabel : l'indexation lit uniquement les octets
    necessaires sur le disque. Utile pour le CT (599 coupes x 512 x 512).
    """
    sl = [slice(None)] * 3
    sl[iz] = int(z)
    return np.asarray(dataobj[tuple(sl)], dtype=np.float32)


def decrire_geometrie(nom: str, img) -> None:
    zooms = img.header.get_zooms()[:3]
    codes = nib.aff2axcodes(img.affine)
    print(f"  {nom}")
    print(f"    dimensions (voxels) : {img.shape}")
    print(f"    espacement (mm)     : {zooms[0]:.4f} x {zooms[1]:.4f} x {zooms[2]:.4f}")
    print(f"    orientation         : {''.join(codes)}  (axe tete-pieds = {axe_z(img)})")


# ---------------------------------------------------------------------------
# Extraction des centroides par coupe
# ---------------------------------------------------------------------------

def plus_grande_composante(masque: np.ndarray) -> np.ndarray:
    """Ne garde que la plus grosse composante connexe 3D (connectivite 26).

    Sur un cas PROPRE il n'y en a qu'une ; ce filtre est un garde-fou contre
    les quelques voxels de bruit qui deplaceraient les centroides.
    """
    etiquettes, n = ndimage.label(masque, structure=np.ones((3, 3, 3), bool))
    if n <= 1:
        return masque
    tailles = ndimage.sum(masque, etiquettes, range(1, n + 1))
    garde = int(np.argmax(tailles)) + 1
    print(f"    [i] {n} composantes -> on garde la #{garde} "
          f"({int(tailles[garde - 1])} voxels, "
          f"{100 * tailles[garde - 1] / tailles.sum():.1f}% du total)")
    return etiquettes == garde


def centroides_par_coupe(masque: np.ndarray, iz: int, rogner: int = 2):
    """Centroide (en indices de voxel) de la section du masque, coupe par coupe.

    Sur chaque coupe on ne retient que la plus grosse region 2D : si le masque
    attrape une bribe de carotide externe sur quelques coupes, le centroide
    global sauterait lateralement.

    'rogner' supprime les premieres et dernieres coupes : aux extremites le
    masque se termine souvent par une lamelle de quelques voxels dont le
    centroide est instable, et c'est justement la que le lissage propage
    l'erreur.

    Retourne (indices_z, points_voxels Nx3, aires_mm2_en_voxels).
    """
    zs = np.where(masque.any(axis=tuple(a for a in range(3) if a != iz)))[0]
    if zs.size == 0:
        sys.exit("[ERREUR] Masque vide.")
    if rogner > 0 and zs.size > 2 * rogner + 10:
        zs = zs[rogner:-rogner]

    axes_plan = [a for a in range(3) if a != iz]
    z_gardes, points, aires = [], [], []

    for z in zs:
        c2d = coupe_2d(masque, iz, z) > 0.5
        et, n = ndimage.label(c2d)          # connectivite 4 : sections compactes
        if n == 0:
            continue
        if n > 1:
            tailles = ndimage.sum(c2d, et, range(1, n + 1))
            c2d = et == (int(np.argmax(tailles)) + 1)
        idx = np.argwhere(c2d)
        p = np.empty(3)
        p[iz] = z
        p[axes_plan[0]] = idx[:, 0].mean()
        p[axes_plan[1]] = idx[:, 1].mean()
        z_gardes.append(int(z))
        points.append(p)
        aires.append(int(c2d.sum()))

    return np.array(z_gardes), np.array(points), np.array(aires)


# ---------------------------------------------------------------------------
# Lissage et reechantillonnage
# ---------------------------------------------------------------------------

def lisser(points_mm: np.ndarray, fenetre: int, ordre: int = 2) -> np.ndarray:
    """Filtre de Savitzky-Golay sur chaque coordonnee.

    Pourquoi SavGol plutot qu'une moyenne glissante : il ajuste localement un
    polynome, donc il lisse le bruit de discretisation (le centroide saute d'un
    demi-voxel d'une coupe a l'autre) SANS aplatir les courbures reelles du
    vaisseau, qui sont exactement ce qu'on veut conserver.

    Pourquoi pas une spline d'ajustement (splprep) : son parametre de lissage
    's' est difficile a regler de facon reproductible. Ici la fenetre est en
    nombre de coupes, donc directement interpretable en millimetres.
    """
    n = len(points_mm)
    f = min(fenetre if fenetre % 2 == 1 else fenetre + 1, n if n % 2 == 1 else n - 1)
    if f <= ordre + 1:
        print("    [!] trop peu de points pour lisser -> centerline brute")
        return points_mm.copy()
    return np.column_stack([savgol_filter(points_mm[:, k], f, ordre) for k in range(3)])


def reechantillonner(points_mm: np.ndarray, pas_mm: float):
    """Reechantillonne la courbe a pas d'abscisse curviligne constant.

    Indispensable : les points d'origine sont espaces d'une coupe (0,625 mm en
    Z), mais si le vaisseau est oblique la distance REELLE entre deux points
    consecutifs est plus grande, et variable. Un pas constant en millimetres
    parcourus le long du vaisseau est la seule parametrisation qui donne des
    tangentes correctes et un profil de diametre a echelle honnete.

    Methode : parametrisation par longueur de corde -> spline cubique ->
    re-parametrisation par la vraie longueur d'arc de la spline (une passe
    suffit, l'ecart residuel est tres inferieur au voxel).

    Retourne (points Mx3, tangentes unitaires Mx3, abscisses curvilignes M).
    """
    d = np.linalg.norm(np.diff(points_mm, axis=0), axis=1)
    t = np.concatenate([[0.0], np.cumsum(d)])
    spl = CubicSpline(t, points_mm, axis=0)

    # Longueur d'arc reelle, estimee finement puis inversee
    t_fin = np.linspace(t[0], t[-1], max(2000, 20 * len(points_mm)))
    p_fin = spl(t_fin)
    s_fin = np.concatenate([[0.0],
                            np.cumsum(np.linalg.norm(np.diff(p_fin, axis=0), axis=1))])
    longueur = float(s_fin[-1])

    s_cible = np.arange(0.0, longueur + 1e-9, pas_mm)
    t_cible = interp1d(s_fin, t_fin)(s_cible)

    pts = spl(t_cible)
    tan = spl(t_cible, 1)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    return pts, tan, s_cible


# ---------------------------------------------------------------------------
# Figures de controle
# ---------------------------------------------------------------------------

def fig_projections(masque, iz, cl_vox, dossier, titre):
    """Masque projete sur deux plans + centerline superposee.

    C'est le controle le plus parlant : si l'axe sort du vaisseau ou coupe un
    virage en ligne droite, ca se voit immediatement.
    """
    axes_plan = [a for a in range(3) if a != iz]
    fig, axs = plt.subplots(1, 2, figsize=(11, 6))
    for k, ap in enumerate(axes_plan):
        proj = masque.max(axis=ap)              # projection d'intensite maximale
        # Apres la projection, les axes restants sont dans l'ordre croissant.
        # On veut l'axe tete-pieds en ordonnee : on transpose si besoin.
        restants = [a for a in range(3) if a != ap]
        if restants.index(iz) == 1:
            proj = proj.T
        axs[k].imshow(proj, cmap="gray", origin="lower", aspect="auto")
        abscisse = [a for a in axes_plan if a != ap][0]
        axs[k].plot(cl_vox[:, abscisse], cl_vox[:, iz], "r-", lw=1.4,
                    label="centerline lissee")
        axs[k].set_title(f"projection le long de l'axe {ap}")
        axs[k].set_xlabel(f"axe {abscisse} (voxels)")
        axs[k].set_ylabel(f"axe {iz} (coupes)")
        axs[k].legend(loc="upper right", fontsize=8)
    fig.suptitle(f"{titre} — controle de l'axe (rouge) sur le masque projete")
    fig.tight_layout()
    fig.savefig(dossier / "01_projections.png", dpi=120)
    plt.close(fig)


def fig_lissage(z_idx, bruts_mm, lisses_mm, dossier, titre):
    """Coordonnees brutes vs lissees, plus l'ecart. Verifie qu'on n'a pas
    sur-lisse (l'ecart doit rester de l'ordre du dixieme de millimetre)."""
    ecart = np.linalg.norm(lisses_mm - bruts_mm, axis=1)
    fig, axs = plt.subplots(1, 4, figsize=(16, 4))
    for k, nom in enumerate("XYZ"):
        axs[k].plot(z_idx, bruts_mm[:, k], ".", ms=3, alpha=.5, label="brut")
        axs[k].plot(z_idx, lisses_mm[:, k], "-", lw=1.5, label="lisse")
        axs[k].set_title(f"coordonnee monde {nom} (mm)")
        axs[k].set_xlabel("coupe")
        axs[k].legend(fontsize=8)
    axs[3].plot(z_idx, ecart, "-", color="crimson")
    axs[3].axhline(np.median(ecart), ls="--", color="gray",
                   label=f"median {np.median(ecart):.2f} mm")
    axs[3].set_title("ecart lissage (mm)")
    axs[3].set_xlabel("coupe")
    axs[3].legend(fontsize=8)
    fig.suptitle(f"{titre} — effet du lissage")
    fig.tight_layout()
    fig.savefig(dossier / "02_lissage.png", dpi=120)
    plt.close(fig)


def fig_coupes(ct_obj, masque, iz, z_idx, pts_vox, dossier, titre):
    """6 coupes axiales reparties : CT en fond, contour du masque, centroide.

    Fenetrage [-100, 700] HU : les unites Hounsfield sont l'echelle de densite
    du CT (eau = 0, air = -1000, os = +1000). Un lumen carotidien opacifie se
    situe vers +250 a +450 HU, la graisse cervicale vers -100. Cette fenetre
    fait donc ressortir le vaisseau sans saturer.
    """
    choix = np.linspace(0, len(z_idx) - 1, 6).astype(int)
    fig, axs = plt.subplots(2, 3, figsize=(12, 8))
    axes_plan = [a for a in range(3) if a != iz]
    for ax, k in zip(axs.ravel(), choix):
        z = int(z_idx[k])
        m = coupe_2d(masque, iz, z) > 0.5
        cy, cx = pts_vox[k, axes_plan[0]], pts_vox[k, axes_plan[1]]
        demi = 40                                  # vignette de 80 voxels de cote
        y0, x0 = int(cy) - demi, int(cx) - demi
        y1, x1 = y0 + 2 * demi, x0 + 2 * demi
        if ct_obj is not None:
            fond = coupe_2d(ct_obj, iz, z)
            ax.imshow(fond[max(y0, 0):y1, max(x0, 0):x1], cmap="gray",
                      vmin=-100, vmax=700, origin="lower")
        else:
            ax.imshow(m[max(y0, 0):y1, max(x0, 0):x1], cmap="gray", origin="lower")
        ax.contour(m[max(y0, 0):y1, max(x0, 0):x1], levels=[0.5],
                   colors="deepskyblue", linewidths=1.2)
        ax.plot(cx - max(x0, 0), cy - max(y0, 0), "r+", ms=12, mew=2)
        ax.set_title(f"coupe {z}", fontsize=9)
        ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(f"{titre} — CT (gris), masque (bleu), centroide (rouge)")
    fig.tight_layout()
    fig.savefig(dossier / "03_coupes.png", dpi=120)
    plt.close(fig)


def fig_diametre_naif(s_coupes, d_axial, d_corrige, angles, dossier, titre):
    """Profil de diametre naif + angle d'obliquite.

    d_axial   : diametre equivalent de la section AXIALE du masque.
    d_corrige : meme chose corrigee par cos(angle). Une coupe axiale traverse
                un vaisseau oblique en biais, donc sa section est plus grande
                que la section vraie d'un facteur 1/cos(angle). A 30 deg le
                diametre est surestime de ~7 %, a 45 deg de ~19 %.
    Cette correction reste approximative (elle suppose un vaisseau localement
    cylindrique) : c'est precisement pour cela qu'on passera a de vraies coupes
    perpendiculaires a l'increment 2.
    """
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(s_coupes, d_axial, "-", color="steelblue",
            label="diametre equivalent, coupe axiale")
    ax.plot(s_coupes, d_corrige, "-", color="darkorange",
            label="corrige par cos(angle)")
    ax.set_xlabel("abscisse curviligne le long de l'axe (mm)")
    ax.set_ylabel("diametre (mm)")
    ax.grid(alpha=.3)
    ax.legend(loc="upper left", fontsize=9)
    ax2 = ax.twinx()
    ax2.plot(s_coupes, angles, ":", color="gray", lw=1)
    ax2.set_ylabel("angle axe / vertical (deg)", color="gray")
    ax2.set_ylim(0, 90)
    fig.suptitle(f"{titre} — profil NAIF (aire du masque), a titre de reference")
    fig.tight_layout()
    fig.savefig(dossier / "04_diametre_naif.png", dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="DeepBridge etape 2 — centerline")
    ap.add_argument("--patient", required=True,
                    help="dossier patient contenant ct.nii.gz et seg/")
    ap.add_argument("--cote", default="gauche", choices=list(COTES),
                    help="carotide interne a traiter")
    ap.add_argument("--out", required=True, help="dossier de sortie")
    ap.add_argument("--pas-mm", type=float, default=0.5,
                    help="pas de reechantillonnage le long de l'axe (defaut 0.5)")
    ap.add_argument("--fenetre", type=int, default=11,
                    help="fenetre de lissage, en coupes, impaire (defaut 11)")
    ap.add_argument("--rogner", type=int, default=2,
                    help="coupes ignorees a chaque extremite (defaut 2)")
    ap.add_argument("--sans-ct", action="store_true",
                    help="ne pas charger le CT (figures de coupes en masque seul)")
    args = ap.parse_args()

    dossier_patient = Path(args.patient)
    patient = dossier_patient.name
    f_seg = dossier_patient / "seg" / f"internal_carotid_artery_{COTES[args.cote]}.nii.gz"
    f_ct = dossier_patient / "ct.nii.gz"
    if not f_seg.exists():
        sys.exit(f"[ERREUR] Masque introuvable : {f_seg}")

    sortie = Path(args.out) / f"{patient}_{args.cote}"
    sortie.mkdir(parents=True, exist_ok=True)

    print(f"\n=== DeepBridge etape 2 — centerline ===")
    print(f"Patient {patient}, carotide interne {args.cote}\n")

    # --- 1. Chargement et geometrie ---------------------------------------
    print("[1/5] Geometrie")
    img_m = nib.load(str(f_seg))
    decrire_geometrie("masque", img_m)

    img_ct = None
    if not args.sans_ct and f_ct.exists():
        img_ct = nib.load(str(f_ct))
        decrire_geometrie("CT", img_ct)
        if img_ct.shape != img_m.shape:
            print("    [!] CT et masque de dimensions differentes -> un "
                  "reechantillonnage sera necessaire avant la mesure FWHM")
        elif not np.allclose(img_ct.affine, img_m.affine, atol=1e-3):
            print("    [!] affines differentes malgre des dimensions egales "
                  "-> a verifier avant l'increment 3")
        else:
            print("    CT et masque partagent exactement la meme grille : "
                  "les indices de voxel sont directement comparables.")
    elif not args.sans_ct:
        print("    [!] ct.nii.gz absent -> figures de coupes sur le masque seul")

    iz = axe_z(img_m)
    zooms = np.array(img_m.header.get_zooms()[:3], dtype=float)
    axes_plan = [a for a in range(3) if a != iz]
    aire_voxel = float(zooms[axes_plan[0]] * zooms[axes_plan[1]])

    # get_fdata renvoie du float64 : sur un 512x512x599 cela ferait ~1,2 Go.
    # On passe par dataobj en float32, puis on binarise et on libere.
    brut = np.asarray(img_m.dataobj, dtype=np.float32)
    masque = brut > 0.5
    del brut
    print(f"    voxels segmentes : {int(masque.sum())} "
          f"({masque.sum() * zooms.prod():.0f} mm3)")

    # --- 2. Centroides par coupe ------------------------------------------
    print("\n[2/5] Centroides par coupe")
    masque = plus_grande_composante(masque)
    z_idx, pts_vox, aires_vox = centroides_par_coupe(masque, iz, args.rogner)
    print(f"    {len(z_idx)} coupes exploitees (z {z_idx[0]} a {z_idx[-1]}, "
          f"{args.rogner} rognees de chaque cote)")

    # Passage des indices de voxel aux millimetres du repere scanner.
    # C'est l'affine qui fait ce travail : sans elle, une distance calculee sur
    # les indices melange 0,59 mm dans le plan et 0,625 mm en Z.
    pts_mm = nib.affines.apply_affine(img_m.affine, pts_vox)

    # --- 3. Lissage et reechantillonnage ----------------------------------
    print("\n[3/5] Lissage et reechantillonnage")
    fenetre_mm = args.fenetre * zooms[iz]
    print(f"    Savitzky-Golay, fenetre {args.fenetre} coupes (~{fenetre_mm:.1f} mm)")
    lisses_mm = lisser(pts_mm, args.fenetre)
    ecart = np.linalg.norm(lisses_mm - pts_mm, axis=1)
    print(f"    ecart au brut : median {np.median(ecart):.2f} mm, "
          f"max {ecart.max():.2f} mm")

    cl_mm, tangentes, s = reechantillonner(lisses_mm, args.pas_mm)
    print(f"    longueur de l'axe : {s[-1]:.1f} mm -> {len(s)} points "
          f"a {args.pas_mm} mm")

    # Angle entre la tangente et la verticale anatomique. L'affine etant en
    # RAS, la troisieme coordonnee monde est l'axe tete-pieds.
    angles = np.degrees(np.arccos(np.clip(np.abs(tangentes[:, 2]), 0, 1)))
    n_alerte = int((angles > SEUIL_ANGLE_ALERTE).sum())
    print(f"    obliquite : mediane {np.median(angles):.1f} deg, "
          f"max {angles.max():.1f} deg")
    if n_alerte:
        print(f"    [!] {n_alerte} point(s) au-dela de {SEUIL_ANGLE_ALERTE} deg : "
              f"le centroide par coupe y est peu fiable (vaisseau trop couche). "
              f"A surveiller si cette zone porte la stenose.")

    # --- 4. Profil naif ----------------------------------------------------
    print("\n[4/5] Profil de diametre naif (reference, sera remplace)")
    d_axial = 2.0 * np.sqrt(aires_vox * aire_voxel / np.pi)
    # abscisse curviligne de chaque coupe d'origine, pour lire l'angle au bon endroit
    d_cum = np.concatenate([[0.0],
                            np.cumsum(np.linalg.norm(np.diff(lisses_mm, axis=0), axis=1))])
    s_coupes = np.clip(d_cum, s[0], s[-1])
    angles_coupes = interp1d(s, angles)(s_coupes)
    d_corrige = d_axial * np.sqrt(np.cos(np.radians(angles_coupes)))
    print(f"    diametre axial   : min {d_axial.min():.2f}, "
          f"median {np.median(d_axial):.2f}, max {d_axial.max():.2f} mm")
    print(f"    apres correction : min {d_corrige.min():.2f}, "
          f"median {np.median(d_corrige):.2f}, max {d_corrige.max():.2f} mm")
    print("    (ces valeurs incluent la paroi et les calcifications : elles ne")
    print("     sont PAS un diametre de lumen exploitable pour NASCET)")

    # --- 5. Sorties --------------------------------------------------------
    print("\n[5/5] Ecriture des sorties")
    cl_vox = nib.affines.apply_affine(np.linalg.inv(img_m.affine), cl_mm)

    f_csv = sortie / "centerline.csv"
    with open(f_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["i", "s_mm", "x_mm", "y_mm", "z_mm",
                    "tx", "ty", "tz", "angle_deg",
                    "vox_0", "vox_1", "vox_2", "source"])
        for k in range(len(s)):
            w.writerow([k, round(float(s[k]), 3)]
                       + [round(float(v), 4) for v in cl_mm[k]]
                       + [round(float(v), 5) for v in tangentes[k]]
                       + [round(float(angles[k]), 2)]
                       + [round(float(v), 3) for v in cl_vox[k]]
                       + ["segmente"])
    print(f"    {f_csv}")

    titre = f"{patient} — CI {args.cote}"
    fig_projections(masque, iz, cl_vox, sortie, titre)
    fig_lissage(z_idx, pts_mm, lisses_mm, sortie, titre)
    fig_coupes(img_ct.dataobj if img_ct is not None else None,
               masque, iz, z_idx, pts_vox, sortie, titre)
    fig_diametre_naif(s_coupes, d_axial, d_corrige, angles_coupes, sortie, titre)
    for n in ["01_projections.png", "02_lissage.png", "03_coupes.png",
              "04_diametre_naif.png"]:
        print(f"    {sortie / n}")

    print("\nA verifier avant l'increment 2 :")
    print("  - 01 : l'axe rouge reste-t-il au centre du masque, sans a-coups ?")
    print("  - 02 : l'ecart de lissage reste-t-il sous ~0,5 mm ?")
    print("  - 03 : la croix rouge est-elle bien au centre du lumen opacifie ?")
    print("  - 04 : le profil est-il continu, sans marche artificielle ?\n")


if __name__ == "__main__":
    main()