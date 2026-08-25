#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etape2d_fwhm.py — DeepBridge, etape 2 / increment 2.

Mesure le diametre du lumen le long de la centerline geodesique, par
reformatage POLAIRE sur des coupes PERPENDICULAIRES a l'axe, avec detection du
bord par largeur a mi-hauteur (FWHM) sur l'image CT.

CE QUE CA CORRIGE
-----------------
1. L'obliquite. On ne mesure plus sur des coupes axiales mais sur des sections
   reellement perpendiculaires a l'axe local. Le biais en 1/cos(theta) (jusqu'a
   +75 % sur ce patient) disparait par construction.
2. La resolution. Le diametre inscrit comptait des voxels ; le FWHM interpole
   entre eux. Sur un lumen de 2 voxels de large, c'est la difference entre une
   valeur inutilisable et une mesure.
3. Les calcifications. Une plaque calcifiee est PLUS DENSE que le produit de
   contraste (900-1200 HU contre 250-450). Un seuil naif la compte comme du
   lumen et surestime le diametre residuel — exactement la ou il ne faut pas se
   tromper. Ici, un rayon qui rencontre du calcium s'arrete la : la plaque
   borne le lumen.

METHODE
-------
- Repere transporte le long de l'axe (parallel transport frame). On ne choisit
  PAS un perpendiculaire arbitraire a chaque point : il tournerait au hasard
  d'une section a l'autre et la carte polaire serait illisible. On transporte
  le repere par rotation minimale, ce qui garantit sa continuite.
- A chaque point d'axe, N rayons partent du centre dans le plan perpendiculaire.
  Le CT est lu par interpolation trilineaire (map_coordinates) le long de chaque
  rayon, a pas fin (0,1 mm par defaut).
- Seuil FWHM = (I_lumen + I_fond) / 2, avec I_lumen estime au centre en
  excluant le calcium, et I_fond estime en peripherie du meme rayon. Le bord est
  le premier passage sous le seuil, localise par interpolation lineaire entre
  les deux echantillons qui l'encadrent.
- Diametres deduits : d_eq (aire du polygone), d_min et d_max (calipers passant
  par le centre). NASCET se prend sur d_min : un lumen residuel est presque
  toujours excentre, et c'est sa plus petite dimension qui compte.

Sorties (dans <out>/<patient>_<cote>/) :
  profil_fwhm.csv       une ligne par position d'axe
  30_mpr.png            deux MPR curvilignes (le vaisseau "deroule")
  31_sections.png       sections perpendiculaires + contour detecte
  32_comparaison.png    FWHM vs diametre inscrit vs axial
  33_stenose.png        gros plan sur la section la plus serree

Usage :
  python etape2d_fwhm.py --patient "C:\\Projetsss\\Resultats\\1359673019" ^
        --cote gauche --out "C:\\Projetsss\\etape2"

Prerequis : nibabel, numpy, scipy, matplotlib + centerline_geo.csv (etape2c)
"""

import argparse
import csv
import warnings
import sys
from pathlib import Path

import numpy as np

try:
    import nibabel as nib
    from scipy import ndimage
except ImportError:
    sys.exit("[ERREUR] Dependances : pip install nibabel numpy scipy matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


COTES = {"gauche": "left", "droite": "right"}

# Seuil au-dela duquel un voxel est considere comme calcifie (ou osseux).
# Le produit de contraste iode plafonne vers 400-500 HU dans une carotide ;
# une plaque calcifiee demarre vers 600-700 et monte au-dela de 1000.
SEUIL_CALCIUM_HU = 600.0

# Biais du FWHM mesure sur fantomes calibres (VALID/GAP/GAP2) : le bord detecte
# tombe en moyenne 0,19 mm trop loin du centre, avec un ecart-type de 0,05 mm.
# Il depend de la PSF et du rehaussement, donc ce n'est pas une constante
# universelle — a re-estimer par examen si un jour on veut vraiment de-biaiser.
DELTA_FWHM_MM = 0.19


# ---------------------------------------------------------------------------
# Repere le long de l'axe
# ---------------------------------------------------------------------------

def repere_transporte(tangentes):
    """Construit un repere (U, V) perpendiculaire a l'axe, continu le long de lui.

    A chaque point on fait tourner le repere precedent par la rotation MINIMALE
    qui amene l'ancienne tangente sur la nouvelle (formule de Rodrigues). Sans
    ce transport, choisir un perpendiculaire arbitraire a chaque section ferait
    tourner l'origine des angles au hasard : la carte polaire et les MPR
    seraient inexploitables.
    """
    n = len(tangentes)
    U = np.zeros((n, 3))
    # amorce : n'importe quel vecteur non colineaire a la tangente
    aide = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(tangentes[0], aide)) > 0.9:
        aide = np.array([1.0, 0.0, 0.0])
    u = np.cross(tangentes[0], aide)
    U[0] = u / np.linalg.norm(u)

    for i in range(1, n):
        t0, t1 = tangentes[i - 1], tangentes[i]
        axe = np.cross(t0, t1)
        s = np.linalg.norm(axe)
        if s < 1e-9:                      # tangentes alignees : rien a tourner
            U[i] = U[i - 1]
        else:
            axe = axe / s
            ang = np.arctan2(s, float(np.dot(t0, t1)))
            u = U[i - 1]
            # rotation de Rodrigues
            U[i] = (u * np.cos(ang) + np.cross(axe, u) * np.sin(ang)
                    + axe * np.dot(axe, u) * (1 - np.cos(ang)))
        # reprojection : on retire toute derive hors du plan perpendiculaire
        U[i] -= tangentes[i] * np.dot(U[i], tangentes[i])
        U[i] /= np.linalg.norm(U[i])
    V = np.cross(tangentes, U)
    return U, V


def lire_ct(ct, affine_inv, points_mm):
    """Lit le CT aux positions monde données, par interpolation trilineaire.

    On repasse en indices de voxel via l'affine inverse. order=1 = trilineaire :
    sans elle le profil radial serait en marches d'escalier et le FWHM n'aurait
    aucune resolution sous-voxel.
    """
    forme = points_mm.shape[:-1]
    vox = nib.affines.apply_affine(affine_inv, points_mm.reshape(-1, 3))
    val = ndimage.map_coordinates(ct, vox.T, order=1, mode="constant", cval=-1000.0)
    return val.reshape(forme)


# ---------------------------------------------------------------------------
# Mesure FWHM
# ---------------------------------------------------------------------------

def rayons_fwhm(prof, r, seuil_calcium, i_lum, frac_fond=0.30, i_max=None,
                seuil_os=None):
    """Detecte le bord du lumen sur chaque rayon d'une section.

    prof : tableau (n_angles, n_r) des intensites CT le long de chaque rayon.
    r    : abscisses radiales en mm.

    Pour chaque rayon, deux evenements peuvent borner le lumen :
      - une descente sous le seuil a mi-hauteur (bord normal, vers les tissus) ;
      - une montee au-dessus du seuil calcium (plaque : le lumen s'arrete la).
    On retient le PREMIER des deux.

    Retourne (rayons_mm, valide, calcifie).
    """
    n_ang, n_r_total = prof.shape
    # PORTEE ADAPTATIVE. Les rayons ne doivent jamais atteindre un vaisseau
    # voisin : sur une bifurcation carotidienne, la carotide externe est a moins
    # de 10 mm et le contour fusionnerait les deux lumens. On borne donc la
    # recherche a partir du calibre local connu par le masque.
    n_r = n_r_total if i_max is None else int(min(i_max, n_r_total))
    prof = prof[:, :n_r]
    # Fond estime sur la peripherie de chaque rayon, calcium exclu : le voisinage
    # d'une carotide n'est pas homogene (graisse, muscle, veine), un fond global
    # serait trop grossier.
    debut_fond = int((1 - frac_fond) * n_r)
    queue = prof[:, debut_fond:].copy()
    queue[queue > seuil_calcium] = np.nan
    with np.errstate(invalid="ignore", all="ignore"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            i_fond = np.nanmedian(queue, axis=1)
    secours = np.nanmedian(prof[prof < seuil_calcium]) if (prof < seuil_calcium).any() else 0.0
    i_fond = np.where(np.isfinite(i_fond), i_fond, secours)

    seuil = 0.5 * (i_lum + i_fond)              # un seuil par rayon

    rayons = np.full(n_ang, np.nan)
    calcifie = np.zeros(n_ang, bool)
    osseux = np.zeros(n_ang, bool)
    for j in range(n_ang):
        p = prof[j]
        # premier passage sous le seuil (bord tissulaire)
        sous = np.where(p < seuil[j])[0]
        i_bord = sous[0] if sous.size else None
        # premiere rencontre de calcium
        cal = np.where(p > seuil_calcium)[0]
        i_cal = cal[0] if cal.size else None

        if seuil_os is not None and (p > seuil_os).any():
            osseux[j] = True          # os dans la portee : rayon inexploitable
            continue
        if i_bord is None and i_cal is None:
            continue
        if i_cal is not None and (i_bord is None or i_cal <= i_bord):
            # la plaque borne le lumen : bord au debut de la montee calcique
            rayons[j] = r[i_cal]
            calcifie[j] = True
            continue
        if i_bord == 0:
            continue                            # centre deja sous le seuil
        # interpolation lineaire entre les deux echantillons qui encadrent
        a, b = p[i_bord - 1], p[i_bord]
        f = (a - seuil[j]) / (a - b) if a != b else 0.0
        rayons[j] = r[i_bord - 1] + f * (r[i_bord] - r[i_bord - 1])

    return rayons, np.isfinite(rayons), calcifie, osseux


def diametres(rayons, angles, calcifie=None, lissage=7, pct=5.0):
    """Diametres deduits des rayons : equivalent, minimal et maximal.

    Deux precautions indispensables, apprises a la dure sur les fantomes :

    1. LISSAGE CIRCULAIRE. Le bord d'un lumen est une courbe reguliere ; un
       rayon qui devie brutalement de ses voisins est du bruit, pas de
       l'anatomie. On applique donc un filtre median circulaire avant toute
       mesure.

    2. MINIMUM ROBUSTE. Prendre le minimum STRICT sur 90 calipers revient a
       laisser un seul rayon aberrant fixer le resultat — et comme ce minimum
       est le numerateur de NASCET, l'erreur se propage directement au ratio.
       On prend donc un percentile bas (5 % par defaut) plutot que le minimum.

    Les rayons marques 'calcifie' sont ECARTES : la plaque brille plus que le
    contraste et son halo (blooming) noie le bord du lumen. Mieux vaut mesurer
    sur le secteur lisible et signaler la limite que produire un chiffre faux.
    """
    n = len(rayons)
    ok = np.isfinite(rayons)
    if calcifie is not None:
        ok = ok & ~calcifie
    if ok.sum() < n * 0.5:
        return np.nan, np.nan, np.nan, float(ok.sum()) / n, np.nan

    # comblement circulaire des rayons manquants, puis median circulaire
    idx = np.arange(n)
    rr = np.interp(idx, idx[ok], rayons[ok], period=n)
    if lissage >= 3:
        etendu = np.concatenate([rr[-lissage:], rr, rr[:lissage]])
        rr = ndimage.median_filter(etendu, size=lissage)[lissage:lissage + n]

    dtheta = angles[1] - angles[0]
    aire = 0.5 * np.sum(rr * np.roll(rr, -1) * np.sin(dtheta))
    d_eq = 2.0 * np.sqrt(max(aire, 0) / np.pi)

    demi = n // 2
    calipers = rr[:demi] + rr[demi:2 * demi]
    # on ne retient que les calipers dont LES DEUX rayons sont exploitables
    bons = ok[:demi] & ok[demi:2 * demi]
    cal_bons = calipers[bons] if bons.sum() >= 5 else calipers
    d_min = float(np.percentile(cal_bons, pct))
    d_max = float(np.percentile(cal_bons, 100 - pct))
    # MINIMUM STRICT, conserve pour comparaison. Le percentile est un
    # estimateur robuste ; le minimum strict, lui, est BIAISE VERS LE BAS et
    # d'autant plus que le nombre de rayons est eleve — un seul rayon aberrant
    # sur quatre-vingt-dix le fixe. Publier les deux permet de montrer que la
    # mesure ne depend pas d'un rayon isole, ce qui est verifiable et non
    # seulement affirme.
    d_min_strict = float(cal_bons.min())
    return d_eq, d_min, d_max, float(ok.sum()) / n, d_min_strict


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="DeepBridge — mesure FWHM polaire")
    ap.add_argument("--patient", required=True)
    ap.add_argument("--cote", default="gauche", choices=list(COTES))
    ap.add_argument("--out", required=True)
    ap.add_argument("--centerline", default=None,
                    help="chemin de centerline_geo.csv (defaut : dans --out)")
    ap.add_argument("--n-angles", type=int, default=180)
    ap.add_argument("--r-max", type=float, default=7.0, help="portee des rayons (mm)")
    ap.add_argument("--pas-r", type=float, default=0.10, help="pas radial (mm)")
    ap.add_argument("--seuil-calcium", type=float, default=SEUIL_CALCIUM_HU,
                    help="plancher absolu du seuil calcium (defaut 600 HU)")
    ap.add_argument("--marge-calcium", type=float, default=250.0,
                    help="ecart minimal entre le lumen et le seuil calcium (HU)")
    ap.add_argument("--seuil-os", type=float, default=800.0,
                    help="HU au-dela desquels on suspecte de l'os (defaut 800)")
    ap.add_argument("--longueur-min-mm", type=float, default=1.0,
                    help="longueur minimale d'une lesion : fenetre du median "
                         "glissant le long de l'axe (defaut 3 mm)")
    ap.add_argument("--excentration-soutenue", type=float, default=1.8,
                    help="rapport d_eq/d_min au-dela duquel une section est "
                         "dite excentree, pour le test de soutien")
    ap.add_argument("--marge-bulbe-mm", type=float, default=5.0,
                    help="distance minimale en amont du minimum pour estimer "
                         "le calibre au niveau de la lesion (defaut 5 mm)")
    ap.add_argument("--fenetre-bulbe-mm", type=float, default=25.0,
                    help="fenetre en amont du minimum ou chercher le calibre "
                         "du bulbe (defaut 25 mm)")
    ap.add_argument("--facteur-bulbe", type=float, default=1.8,
                    help="rapport max tolere entre calibre au niveau de la "
                         "lesion et reference distale")
    ap.add_argument("--frac-stenose-min", type=float, default=0.95,
                    help="si d_min depasse cette fraction de la reference "
                         "distale, aucun retrecissement focal n'est retenu "
                         "(defaut 0.95)")
    ap.add_argument("--facteur-ref", type=float, default=1.6,
                    help="rapport max tolere entre le plus grand diametre du "
                         "contour au minimum et la reference distale")
    ap.add_argument("--tolerance-cache-mm", type=float, default=0.3,
                    help="ecart (mm) au-dela duquel une section ecartee plus "
                         "etroite que le minimum retenu interdit toute mesure "
                         "incertaine")
    ap.add_argument("--frac-vaisseau", type=float, default=0.85,
                    help="fraction du vaisseau devant etre exploitable pour "
                         "qu'un minimum au voisinage degrade donne lieu a une "
                         "mesure incertaine (defaut 0.85)")
    ap.add_argument("--hu-min-incertain", type=float, default=280.0,
                    help="rehaussement median minimal pour une mesure "
                         "incertaine (defaut 280 HU)")
    ap.add_argument("--frac-voisinage", type=float, default=0.8,
                    help="fraction du voisinage du minimum qui doit etre "
                         "exploitable pour publier un ratio (defaut 0.8)")
    ap.add_argument("--voisinage-mm", type=float, default=3.0,
                    help="rayon autour du minimum qui doit etre entierement "
                         "fiable pour publier un NASCET (defaut 3 mm)")
    ap.add_argument("--facteur-masque", type=float, default=3.0,
                    help="rapport max tolere entre d_eq FWHM et d_inscrit masque")
    ap.add_argument("--frac-lumen", type=float, default=0.50,
                    help="fraction du rehaussement observe en dessous de "
                         "laquelle une section est jugee hors lumen")
    ap.add_argument("--hu-lumen-min", type=float, default=150.0,
                    help="rehaussement minimal pour qu'une section soit mesurable")
    ap.add_argument("--excentration-max", type=float, default=3.0,
                    help="rapport d_max/d_min au-dela duquel le contour est juge "
                         "aberrant")
    ap.add_argument("--csv", default=None,
                    help="fichier de synthese ; une ligne AJOUTEE par carotide")
    ap.add_argument("--sans-figures", action="store_true")
    ap.add_argument("--marge-mm", type=float, default=2.0,
                    help="extremites de l'axe ignorees (defaut 2 mm)")
    args = ap.parse_args()

    dp = Path(args.patient)
    patient = dp.name
    sortie = Path(args.out) / f"{patient}_{args.cote}"
    f_cl = Path(args.centerline) if args.centerline else sortie / "centerline_geo.csv"
    f_ct = dp / "ct.nii.gz"
    if not f_cl.exists():
        sys.exit(f"[ERREUR] Centerline introuvable : {f_cl}\n"
                 f"         Lance d'abord etape2c_centerline_geodesique.py")
    if not f_ct.exists():
        sys.exit(f"[ERREUR] CT introuvable : {f_ct}")

    print("\n=== DeepBridge — mesure FWHM sur coupes perpendiculaires ===")
    print(f"Patient {patient}, carotide interne {args.cote}\n")

    # --- 1. Chargement -----------------------------------------------------
    lignes = list(csv.DictReader(open(f_cl, encoding="utf-8-sig"), delimiter=";"))
    s = np.array([float(l["s_mm"]) for l in lignes])
    P = np.array([[float(l[k]) for k in ("x_mm", "y_mm", "z_mm")] for l in lignes])
    T = np.array([[float(l[k]) for k in ("tx", "ty", "tz")] for l in lignes])
    z_vox = np.array([float(l["vox_2"]) for l in lignes])
    d_ins = np.array([float(l["diametre_inscrit_mm"]) for l in lignes])
    # Obliquite : lue dans la centerline si presente, sinon recalculee depuis
    # la tangente. La troisieme coordonnee monde est l'axe tete-pieds, le
    # format NIfTI l'imposant quelle que soit l'orientation des axes du
    # tableau.
    if lignes and "angle_deg" in lignes[0]:
        angle_axe = np.array([float(l["angle_deg"]) for l in lignes])
    else:
        angle_axe = np.degrees(np.arccos(np.clip(np.abs(T[:, 2]), 0, 1)))
    T /= np.linalg.norm(T, axis=1, keepdims=True)

    if len(s) == 0:
        print("[!] Centerline vide : rien a mesurer.")
        sys.exit(0)
    garde = (s >= args.marge_mm) & (s <= s[-1] - args.marge_mm)
    s, P, T, z_vox, d_ins = s[garde], P[garde], T[garde], z_vox[garde], d_ins[garde]
    angle_axe = angle_axe[garde]
    # Le rognage des extremites peut ne rien laisser si l'axe est plus court
    # que deux fois la marge : un vaisseau de 8 mm avec 5 mm de marge de
    # chaque cote, par exemple. On s'arrete proprement plutot que de propager
    # un tableau vide dans toute la chaine de mesure.
    if len(s) == 0:
        print(f"[!] Axe trop court pour un rognage de {args.marge_mm} mm a "
              f"chaque extremite : rien a mesurer.")
        sys.exit(0)
    print(f"[1/4] Centerline : {len(s)} positions, {s[-1] - s[0]:.1f} mm "
          f"({args.marge_mm} mm rognes a chaque bout)")

    img = nib.load(str(f_ct))
    ct = np.asarray(img.dataobj, dtype=np.float32)
    affine_inv = np.linalg.inv(img.affine)
    # Espacement lu dans l'en-tete et non code en dur : il varie de 0,498 a
    # 0,592 mm dans la cohorte, soit 18 % d'ecart sur un comptage de voxels.
    zooms_ct = np.array(img.header.get_zooms()[:3], float)
    vox_plan = float(np.min(zooms_ct))
    print(f"      CT : {ct.shape}, {ct.min():.0f} a {ct.max():.0f} HU")

    # --- 2. Repere et echantillonnage polaire ------------------------------
    print(f"\n[2/4] Reformatage polaire "
          f"({args.n_angles} rayons, {args.r_max} mm, pas {args.pas_r} mm)")
    U, V = repere_transporte(T)
    angles = np.linspace(0, 2 * np.pi, args.n_angles, endpoint=False)
    r = np.arange(0, args.r_max + 1e-9, args.pas_r)
    ca, sa = np.cos(angles)[:, None], np.sin(angles)[:, None]

    prof_all = np.empty((len(s), args.n_angles, len(r)), dtype=np.float32)
    for i in range(len(s)):
        # points = centre + r * (cos(theta) U + sin(theta) V)
        dirs = ca * U[i] + sa * V[i]                       # (n_ang, 3)
        pts = P[i] + r[None, :, None] * dirs[:, None, :]   # (n_ang, n_r, 3)
        prof_all[i] = lire_ct(ct, affine_inv, pts)

    # Intensite du lumen : mediane des echantillons proches du centre, calcium
    # exclu. Estimee section par section car le rehaussement varie le long du
    # vaisseau (dilution du contraste, temps d'acquisition).
    n_centre = max(2, int(round(0.4 / args.pas_r)))
    coeur_brut = prof_all[:, :, :n_centre].reshape(len(s), -1)

    # SEUIL CALCIUM ADAPTATIF. Un seuil absolu ne peut pas marcher : le
    # rehaussement du lumen varie enormement d'un examen a l'autre (256, 417 et
    # 572 HU sur trois patients de cette cohorte). A 572 HU de lumen, un seuil
    # fixe a 600 fait passer le sang pour de la plaque sur 360 degres.
    # On exige donc un ecart minimal entre le lumen et le seuil, tout en
    # gardant un plancher absolu : une plaque calcifiee descend rarement sous
    # 600 HU. Premiere estimation du lumen sans exclusion (le centre d'un
    # vaisseau permeable est du lumen), puis le seuil, puis re-estimation.
    with np.errstate(invalid="ignore"):
        i_lum0 = np.nanmedian(coeur_brut, axis=1)
    i_lum0 = np.where(np.isfinite(i_lum0), i_lum0, 0.0)
    seuil_cal = np.maximum(args.seuil_calcium, i_lum0 + args.marge_calcium)
    # QUEL TERME EST ACTIF. Le seuil vaut max(plancher, lumen + marge) : un
    # seul des deux termes gouverne a la fois. Faire varier le terme dormant ne
    # change rien, et ce zero ne signifie PAS "sans influence" mais "masque sur
    # ce cas". Sans cette trace, un tableau de sensibilite n'est pas lisible.
    n_plancher = int((seuil_cal <= args.seuil_calcium + 1e-9).sum())
    terme_cal = ("plancher" if n_plancher > len(s) / 2 else "lumen+marge")
    print(f"      seuil calcium adaptatif : {seuil_cal.min():.0f} a "
          f"{seuil_cal.max():.0f} HU "
          f"(lumen {i_lum0.min():.0f}-{i_lum0.max():.0f} + "
          f"{args.marge_calcium:.0f}, plancher {args.seuil_calcium:.0f})")
    print(f"      TERME ACTIF calcium : {terme_cal} "
          f"({n_plancher}/{len(s)} sections au plancher) — "
          f"marge au basculement {abs(np.median(i_lum0 + args.marge_calcium - args.seuil_calcium)):.0f} HU")

    coeur = coeur_brut.copy()
    coeur[coeur > seuil_cal[:, None]] = np.nan
    with np.errstate(invalid="ignore"):
        i_lum = np.nanmedian(coeur, axis=1)
    i_lum = np.where(np.isfinite(i_lum), i_lum, np.nanmedian(coeur))

    # Fraction de chaque section occupee par de l'os. A la base du crane, la
    # carotide interne entre dans le canal carotidien : de l'os a 1000-1500 HU
    # se trouve a moins de 7 mm de l'axe. Il fausse l'estimation du fond, donc
    # le seuil FWHM, donc le diametre. Ces sections ne sont pas mesurables — et
    # elles sont de toute facon HORS du territoire cervical ou se prend la
    # reference NASCET.

    print(f"      rehaussement du lumen : median {np.median(i_lum):.0f} HU "
          f"(min {i_lum.min():.0f}, max {i_lum.max():.0f})")

    # --- 3. Detection des bords -------------------------------------------
    print(f"\n[3/4] Detection FWHM")
    d_eq = np.full(len(s), np.nan)
    d_min = np.full(len(s), np.nan)
    d_max = np.full(len(s), np.nan)
    n_ok = np.zeros(len(s), int)
    n_cal = np.zeros(len(s), int)
    n_os_rayon = np.zeros(len(s), int)
    frac_ok = np.zeros(len(s))
    d_min_strict = np.full(len(s), np.nan)
    # portee de recherche, section par section : 2x le calibre du masque,
    # bornee entre 2,5 mm et --r-max
    r_local = np.clip(2.0 * d_ins, 2.5, args.r_max)
    tous_rayons = np.full((len(s), args.n_angles), np.nan)

    for i in range(len(s)):
        i_max = int(np.ceil(r_local[i] / args.pas_r)) + 1
        ray, ok, cal, oss = rayons_fwhm(prof_all[i], r, float(seuil_cal[i]),
                                        i_lum[i], i_max=i_max,
                                        seuil_os=max(args.seuil_os,
                                                     float(seuil_cal[i]) + 200.0))
        tous_rayons[i] = ray
        n_ok[i], n_cal[i] = int(ok.sum()), int(cal.sum())
        n_os_rayon[i] = int(oss.sum())
        (d_eq[i], d_min[i], d_max[i], frac_ok[i],
         d_min_strict[i]) = diametres(ray, angles, cal)

    valides = np.isfinite(d_min)
    # Une section dont plus de la moitie de la circonference est calcifiee ou
    # illisible n'est pas mesurable : on la signale au lieu de la chiffrer.
    # Une section n'est retenue que si TOUT est plausible. Compter les rayons
    # qui ont trouve "un" bord ne suffit pas : un rayon peut trouver un bord au
    # mauvais endroit. On ajoute donc trois garde-fous physiques.
    with np.errstate(invalid="ignore"):
        excentration = d_max / np.maximum(d_min, 1e-6)
    # Seuil de rehaussement ADAPTATIF, comme pour le calcium. Un seuil absolu
    # de 150 HU n'a pas de sens sur un examen ou le lumen est a 550 : une
    # section lisant 220 HU au centre n'est pas un lumen faiblement rehausse,
    # c'est un axe qui frole la paroi. On se cale donc sur le rehaussement
    # reellement observe (percentile 75, robuste aux sections deja hors lumen).
    hu_ref = float(np.percentile(i_lum, 75))
    seuil_lum = max(args.hu_lumen_min, args.frac_lumen * hu_ref)
    terme_lum = ("plancher" if seuil_lum <= args.hu_lumen_min + 1e-9
                 else "fraction du rehaussement")
    print(f"      seuil de rehaussement : {seuil_lum:.0f} HU "
          f"({100 * args.frac_lumen:.0f} % de {hu_ref:.0f} HU observes, "
          f"plancher {args.hu_lumen_min:.0f})")
    print(f"      TERME ACTIF rehaussement : {terme_lum} — "
          f"marge au basculement "
          f"{abs(args.frac_lumen * hu_ref - args.hu_lumen_min):.0f} HU")
    crit = {
        "circonference lisible < 60 %": frac_ok < 0.60,
        f"rehaussement < {seuil_lum:.0f} HU (axe hors lumen ?)": i_lum < seuil_lum,
        "os dans la portee des rayons": n_os_rayon > args.n_angles * 0.10,
        # Garde-fou de coherence avec le masque : si le contour FWHM est
        # beaucoup plus large que le calibre segmente, c'est qu'il a fuit vers
        # une structure voisine. Le facteur est genereux (le masque
        # sous-segmente souvent au niveau d'une plaque), mais un facteur 3
        # n'est plus une sous-segmentation, c'est une fuite.
        "contour incoherent avec le masque (d_eq > 3x d_inscrit)":
            np.isfinite(d_eq) & (d_eq > args.facteur_masque * d_ins),
        # Tolerance d'excentration ADAPTEE AU CALIBRE. Une section circulaire
        # a un rapport proche de 1 ; le bulbe carotidien est anatomiquement
        # ovale (1,5 a 2) et un lumen residuel en croissant l'est davantage.
        # Un seuil fixe penalise donc les gros calibres, ou l'ovalisation est
        # normale, sans mieux detecter les contours qui ont fui — ceux-la sont
        # deja pris par le test de coherence avec le masque.
        f"contour aberrant (d_max/d_min > {args.excentration_max:.0f}"
        f", tolerance elargie sur gros calibre)":
            np.isfinite(excentration)
            & (excentration > args.excentration_max
               * np.clip(np.where(np.isfinite(d_eq), d_eq, 4.0) / 4.0, 1.0, 1.8)),
    }
    fiable = valides.copy()
    for m in crit.values():
        fiable &= ~m
    print(f"      {valides.sum()}/{len(s)} sections mesurees, "
          f"{fiable.sum()} retenues")
    for nom, m in crit.items():
        n = int((valides & m).sum())
        if n:
            print(f"        ecartees — {nom} : {n}")
    print(f"      rayons valides : {100 * n_ok.mean() / args.n_angles:.1f} % en moyenne")
    n_sect_cal = int((n_cal > 0).sum())
    if n_sect_cal:
        print(f"      calcium detecte sur {n_sect_cal} section(s) "
              f"({100 * n_sect_cal / len(s):.0f} %), "
              f"max {n_cal.max()} rayons sur {args.n_angles} "
              f"({360 * n_cal.max() / args.n_angles:.0f} deg d'arc)")

    # Minimum robuste LE LONG DE L'AXE. Meme raisonnement qu'autour de la
    # circonference : une section isolee qui plonge est du bruit. Une stenose a
    # une longueur physique ; plus courte que ~1,5 mm elle n'est de toute facon
    # pas resolue a 0,625 mm d'epaisseur de coupe. On lisse donc par median
    # glissant avant de chercher le minimum.
    # LONGUEUR MINIMALE D'UNE LESION. Une stenose a une longueur physique :
    # une chute et une remontee sur un seul point d'axe ne peut pas en etre
    # une. Une fenetre trop courte (1 mm) laissait passer des decrochements
    # ponctuels du contour — un secteur angulaire qui perd le bord sur une
    # section isolee — et les prenait pour le minimum.
    n_lis = max(3, int(round(args.longueur_min_mm
                             / max(np.median(np.diff(s)), 1e-6))))
    n_lis = n_lis if n_lis % 2 == 1 else n_lis + 1
    d_min_lisse = np.where(np.isfinite(d_min), d_min, np.nan)
    rempli = np.where(np.isfinite(d_min_lisse), d_min_lisse, np.nanmax(d_min_lisse))
    d_min_lisse = ndimage.median_filter(rempli, size=n_lis)
    print(f"      minimum cherche sur un median glissant de {n_lis} points "
          f"(~{n_lis * np.median(np.diff(s)):.1f} mm)")

    base = np.where(fiable, d_min_lisse, np.inf)
    if not np.isfinite(base).any():
        sys.exit("[ERREUR] Aucune section fiable : calcifications trop etendues.")
    k = int(np.argmin(base))
    # Reference NASCET : partie distale, hors zone calcifiee, la ou le calibre
    # est stable. On prend la mediane sur le tiers distal.
    dist = fiable & (s > s[0] + 0.66 * (s[-1] - s[0]))
    d_ref = float(np.median(d_min[dist])) if dist.sum() > 5 else np.nan

    print(f"\n      Diametre minimal (caliper par le centre) :")
    print(f"        {d_min[k]:.2f} mm a s={s[k]:.1f} mm (coupe {z_vox[k]:.0f})")
    print(f"        d_eq {d_eq[k]:.2f} mm | d_max {d_max[k]:.2f} mm "
          f"-> excentration {d_max[k] / max(d_min[k], 1e-6):.1f}x")
    # EXCENTRATION SOUTENUE OU PONCTUELLE.
    #
    # Une vraie stenose excentree l'est sur plusieurs millimetres : le lumen
    # residuel garde sa forme en croissant d'une section a l'autre. Un
    # decrochement du contour, lui, est ponctuel — un secteur angulaire perd
    # le bord sur une section isolee, le d_min s'effondre alors que le d_eq
    # de la meme section reste large.
    #
    # On ne rejette donc PAS sur la seule excentration : les donnees de
    # cohorte montrent que les fortes excentrations correspondent aux NASCET
    # eleves, c'est-a-dire a de vraies lesions serrees. On teste si elle est
    # PARTAGEE par le voisinage.
    with np.errstate(invalid="ignore", divide="ignore"):
        exc_eq = np.where(np.isfinite(d_eq) & (d_min > 0), d_eq / d_min, np.nan)
    vk = np.abs(s - s[k]) <= args.voisinage_mm
    vk_autres = vk & (np.arange(len(s)) != k)
    exc_k = float(exc_eq[k]) if np.isfinite(exc_eq[k]) else 0.0
    n_exc = int((exc_eq[vk_autres] > args.excentration_soutenue).sum())
    n_vois = int(vk_autres.sum())
    soutenue = (n_vois == 0) or (n_exc >= 0.4 * n_vois)
    if exc_k > args.excentration_soutenue and not soutenue:
        print(f"      [!] Section du minimum excentree (d_eq/d_min = "
              f"{exc_k:.1f}) mais ses voisines ne le sont pas "
              f"({n_exc}/{n_vois}).")
        print(f"          Decrochement ponctuel du contour probable, plutot "
              f"qu'une lesion. A verifier sur 33_stenose.png.")

    # NASCET PAR AIRE.
    #
    # Le ratio classique repose sur d_min, qui est UN SEUL caliper : deux
    # rayons opposes sur cent quatre-vingts. Sur un lumen residuel de 1 mm,
    # chacun ne porte que deux voxels et le bruit domine. Le diametre
    # equivalent, lui, agrege les cent quatre-vingts rayons via l'aire du
    # polygone : le bruit se moyenne, et un lumen en croissant — forme typique
    # d'une stenose severe — garde une aire mesurable alors que son plus petit
    # diametre s'effondre.
    #
    # La litterature va dans ce sens : sur 113 carotides stenosees a plus de
    # 50 %, la mesure par aire est sans biais face a l'echo-doppler (ecart
    # moyen -0,4 %) alors que la mesure par diametre sous-estime de 20,7 %,
    # avec une sensibilite de 81 % contre 23 % [Insights into Imaging, 2018].
    #
    # ATTENTION : le seuil de 70 % a ete valide sur des DIAMETRES (essai
    # NASCET). Une valeur calculee par aire ne se compare pas directement a ce
    # seuil. Les deux sont donc publiees cote a cote, sans substitution.
    d_ref_aire = np.nan
    nascet_aire = np.nan
    k_aire = None
    if dist.sum() > 5:
        d_ref_aire = float(np.median(d_eq[dist]))
    if np.isfinite(d_ref_aire) and d_ref_aire > 0:
        base_a = np.where(fiable & np.isfinite(d_eq), d_eq, np.inf)
        if np.isfinite(base_a).any():
            # meme lissage axial que pour le diametre, meme exigence de
            # longueur physique de la lesion
            rempli_a = np.where(np.isfinite(base_a), base_a, np.nanmax(d_eq))
            lisse_a = ndimage.median_filter(rempli_a, size=n_lis)
            lisse_a = np.where(fiable, lisse_a, np.inf)
            k_aire = int(np.argmin(lisse_a))
            if np.isfinite(d_eq[k_aire]):
                # RATIO D'AIRES, et non de diametres equivalents. La
                # litterature compare 1 - A_min/A_ref a 1 - d_min/d_ref.
                # Comme A est proportionnelle a d_eq^2, le ratio d'aires
                # s'ecrit 1 - (d_eq_min/d_eq_ref)^2 et donne TOUJOURS une
                # valeur superieure au ratio de diametres : 50 % en diametre
                # correspond a 75 % en aire.
                #
                # Une premiere version calculait 1 - d_eq_min/d_eq_ref, ce qui
                # est un ratio de DIAMETRES equivalents : il donnait des
                # valeurs INFERIEURES au NASCET classique, puisque le diametre
                # equivalent lisse l'excentration du lumen residuel et est donc
                # toujours superieur ou egal au plus petit caliper.
                nascet_aire = 100 * (1 - (d_eq[k_aire] / d_ref_aire) ** 2)

    print(f"      Reference distale : {d_ref:.2f} mm")
    # Une carotide interne distale normale mesure 4,5 a 5,5 mm. Nettement moins
    # signale un COLLAPSUS D'AVAL : en aval d'une stenose serree le debit chute
    # et le vaisseau se collabe. Or ce diametre est le DENOMINATEUR de NASCET :
    # quand il diminue, le ratio diminue avec lui et SOUS-ESTIME la lesion.
    # C'est une limite reconnue du critere, pas un defaut de mesure.
    if np.isfinite(d_ref) and d_ref < 3.8:
        print(f"      [!] Reference distale etroite (< 3,8 mm). Un collapsus")
        print(f"          d'aval est possible : NASCET sous-estime alors la")
        print(f"          lesion, par construction. Comparer au cote")
        print(f"          controlateral et envisager ECST.")

    # ECST. NASCET rapporte le lumen residuel au diametre de la CI DISTALE ;
    # ECST le rapporte au diametre qu'aurait le vaisseau AU NIVEAU MEME de la
    # stenose s'il n'y avait pas de plaque. On estime ce dernier en
    # interpolant le calibre mesure de part et d'autre de la lesion : c'est
    # l'approximation usuelle quand on ne segmente pas la paroi externe.
    #
    # ECST donne toujours un pourcentage PLUS ELEVE que NASCET, parce que son
    # denominateur (calibre au bulbe) est plus grand que la CI distale. La
    # correspondance publiee (Rothwell, Stroke 1994) est ECST = 0,6 x NASCET
    # + 40, ce qui place le seuil chirurgical de 70 % NASCET vers 82-84 % ECST.
    # Afficher un ECST sans rappeler SON seuil invite l'erreur de lecture.
    #
    # POURQUOI UNE ESTIMATION, ET PAS UNE MESURE. La definition d'ECST demande
    # le diametre de la paroi externe au niveau de la lesion. Sur angioscanner
    # cette paroi n'est pas seulement peu nette : elle est STRUCTURELLEMENT
    # INVISIBLE. La paroi non rehaussee et le tissu conjonctif peri-arteriel
    # ont des densites voisines, de quelques dizaines d'unites Hounsfield, et
    # le CTA ne les separe pas. Elle ne devient localement visible que sur
    # plaque calcifiee — c'est-a-dire precisement la ou l'epanouissement de
    # densite fausse la position du bord. La paroi n'est donc mesurable que la
    # ou sa mesure serait fausse. On interpole le calibre du lumen de part et
    # d'autre de la lesion : d'ou le nom ECST ESTIME.
    ecst_interp = np.nan
    d_bulbe = np.nan
    borne_bulbe_active = False
    if np.isfinite(d_ref):
        # bornes de la lesion : ou le diametre remonte au-dessus de 90 % de
        # la reference, de part et d'autre du minimum
        # ESTIMATION DU CALIBRE AU NIVEAU DE LA LESION.
        #
        # La version initiale cherchait les bornes de la lesion la ou le
        # diametre remonte au-dessus de 90 % de la reference DISTALE, puis
        # interpolait entre elles. Sur la cohorte, le rapport
        # calibre_lesion / d_ref valait 1,01 en mediane la ou l'anatomie impose
        # 1,3 a 1,6, et ECST sortait INFERIEUR a NASCET dans vingt cas sur
        # quarante-six — ce qui est impossible par definition.
        #
        # Cause : sur un vaisseau qui s'elargit vers le bas, la borne a 90 % de
        # la reference distale est atteinte des la sortie de la stenose, bien
        # avant le bulbe. On interpolait donc dans un segment deja retreci.
        #
        # Correction : on prend le calibre caracteristique EN AMONT de la
        # lesion — le bulbe est du cote des faibles abscisses, le sang circulant
        # vers le haut — via un centile eleve du diametre equivalent, qui est
        # plus stable que le plus petit caliper. Le resultat est borne
        # inferieurement par la reference distale : le vaisseau au niveau de la
        # lesion ne peut pas etre plus etroit que son segment distal sain.
        # Le calibre est pris dans une FENETRE en amont, et non sur tout
        # l'amont : avec la carotide commune fusionnee, l'axe descend jusqu'a
        # la clavicule, et un centile calcule sur tout le trajet capture le
        # calibre de la commune basse — plus large que le bulbe. Sur la
        # cohorte, cela donnait un rapport de 1,95 la ou l'anatomie impose
        # 1,3 a 1,6. On se limite donc au voisinage immediat de la lesion,
        # ou siege le bulbe, et on prend la mediane des sections les plus
        # larges de cette fenetre plutot qu'un centile extreme.
        # LE BULBE EST UN MAXIMUM LOCAL, PAS UNE DISTANCE FIXE.
        #
        # Une version precedente prenait le quart superieur du calibre dans une
        # fenetre de 25 mm en amont. Avec la carotide commune fusionnee, cette
        # fenetre tombe dans la commune elle-meme — 6 a 7,5 mm de calibre pour
        # une carotide interne distale de 3,5 a 4,5 : le rapport saturait la
        # borne de securite dans 72 % des cas, et ECST ne mesurait plus rien
        # d'autre que ce plafond.
        #
        # On remonte donc depuis la lesion TANT QUE LE CALIBRE AUGMENTE, et on
        # s'arrete au premier maximum local : c'est la definition geometrique
        # du bulbe. La remontee est bornee pour ne pas descendre dans la
        # commune si aucun maximum n'est rencontre.
        pas = float(np.median(np.diff(s))) if len(s) > 1 else 0.5
        n_marge = max(1, int(round(args.marge_bulbe_mm / max(pas, 1e-6))))
        n_max = max(n_marge + 2, int(round(args.fenetre_bulbe_mm / max(pas, 1e-6))))
        i = k - n_marge
        meilleur = None
        n_desc = 0
        while i > 0 and (k - i) <= n_max:
            if fiable[i] and np.isfinite(d_eq[i]):
                if meilleur is None or d_eq[i] > d_eq[meilleur]:
                    meilleur, n_desc = i, 0
                else:
                    n_desc += 1
                    # trois sections consecutives plus etroites : le maximum
                    # local est passe, on ne descend pas plus bas
                    if n_desc >= max(3, int(round(1.5 / max(pas, 1e-6)))):
                        break
            i -= 1
        if meilleur is not None:
            # moyenne locale autour du sommet, plus stable qu'une valeur isolee
            voisin_b = (np.abs(s - s[meilleur]) <= 1.5) & fiable & np.isfinite(d_eq)
            d_bulbe = float(np.median(d_eq[voisin_b])) if voisin_b.sum() >= 2 \
                else float(d_eq[meilleur])
            d_brut = d_bulbe
            d_bulbe = float(np.clip(d_bulbe, d_ref,
                                    args.facteur_bulbe * d_ref))
            # La borne est un GARDE-FOU DE PLAUSIBILITE contre une fuite du
            # contour, pas un calibrage. On trace quand elle agit, pour
            # pouvoir compter sur la cohorte les cas reellement bornes.
            borne_bulbe_active = abs(d_bulbe - d_brut) > 1e-6
            if borne_bulbe_active:
                print(f"          [i] Calibre borne : {d_brut:.2f} -> "
                      f"{d_bulbe:.2f} mm (garde-fou de plausibilite)")
            if d_bulbe > 0:
                ecst_interp = 100 * (1 - d_min[k] / d_bulbe)
                print(f"      Calibre estime au niveau de la lesion : "
                      f"{d_bulbe:.2f} mm (maximum local en amont, "
                      f"a s={s[meilleur]:.1f} mm soit "
                      f"{s[k] - s[meilleur]:.1f} mm de la lesion)")
                # NB : ce rapport est un INDICATEUR de couverture du bulbe,
                # pas une cible a atteindre. Un bulbe dilate en amont d'une
                # stenose donne legitimement un rapport superieur a la valeur
                # anatomique moyenne. Ajuster un parametre pour le ramener
                # dans une plage attendue reviendrait a calibrer sur une
                # valeur supposee plutot que mesuree.
                print(f"          rapport au diametre distal : "
                      f"{d_bulbe / d_ref:.2f} (indicateur de couverture du "
                      f"bulbe ; < 1,15 = bulbe absent du territoire)")
                if d_bulbe / d_ref < 1.15:
                    print(f"          [!] Rapport faible : le bulbe n'est "
                          f"probablement pas dans le territoire mesure.")
                    print(f"              Verifier la fusion de la carotide "
                          f"commune (--avec-commune).")
        if not np.isfinite(ecst_interp):
            print(f"      ECST estime non calculable : pas assez de sections "
                  f"exploitables en amont de la lesion pour estimer le "
                  f"calibre du bulbe")

    # Zones ou la mesure n'est pas possible. Une plaque calcifiee etendue noie
    # le bord du lumen par effet de blooming : c'est LA limite documentee de
    # l'angioscanner pour grader une stenose carotidienne. Si une telle zone
    # existe, on ne publie PAS de ratio — un chiffre faux est pire que pas de
    # chiffre pour un outil d'aide a la decision.
    mauvais = valides & ~fiable
    zones_ko = []
    if mauvais.any():
        w = np.where(mauvais)[0]
        deb = w[0]
        for a, b in zip(w, list(w[1:]) + [None]):
            if b is None or b - a > 3:
                zones_ko.append((deb, a)); deb = b

    # Une zone illisible ne disqualifie pas toute la mesure : ce qui compte est
    # de savoir si elle touche LA section la plus serree. Si le minimum et son
    # voisinage immediat sont propres, le ratio est publiable — les zones
    # illisibles restantes sont signalees a part, car elles pourraient masquer
    # une SECONDE lesion, pas fausser celle qu'on a mesuree.
    # VOISINAGE DU MINIMUM. Exiger que 100 % des sections voisines soient
    # exploitables revient a laisser UNE section rejetee bloquer toute la
    # mesure : sur 13 sections, une seule suffit. Or la section du minimum
    # elle-meme, si elle est fiable et entouree en majorite de sections
    # fiables, donne une mesure defendable. On exige donc que le minimum soit
    # fiable ET qu'une fraction suffisante du voisinage le soit.
    # ABSENCE DE STENOSE FOCALE.
    #
    # NASCET rapporte le lumen minimal au diametre distal. Si le point le plus
    # etroit du trajet est aussi large que la reference, il n'y a pas de
    # retrecissement focal : le vaisseau se reduit progressivement vers l'aval,
    # ce qui est le profil normal d'une artere saine. La formule n'a alors pas
    # d'objet, et elle peut meme rendre une valeur NEGATIVE — observee sur un
    # cas de la cohorte a -35,7 %, ou d_min valait 4,91 mm pour une reference
    # de 3,62 mm.
    #
    # Borner a zero masquerait l'information au lieu de la nommer. On distingue
    # donc trois situations : mesurer une stenose, ne pas pouvoir mesurer, et
    # n'avoir rien a mesurer. La derniere est un resultat, pas un echec.
    pas_de_stenose = bool(
        np.isfinite(d_min[k]) and np.isfinite(d_ref) and d_ref > 0
        and d_min[k] >= args.frac_stenose_min * d_ref)

    voisin = np.abs(s - s[k]) <= args.voisinage_mm
    frac_v = float(fiable[voisin].mean()) if voisin.sum() else 0.0
    minimum_propre = (bool(fiable[k]) and voisin.sum() >= 3
                      and frac_v >= args.frac_voisinage)

    # VERDICT INTERMEDIAIRE.
    #
    # Exiger 80 % du voisinage immediat revient a ecarter par construction les
    # lesions les plus serrees : un lumen residuel etroit degrade forcement ses
    # sections voisines. Or l'analyse de cohorte montre que les refus sont
    # significativement PLUS stenoses que les mesures publiees — le taux de
    # refus n'est donc pas independant de la severite.
    #
    # On ouvre un troisieme verdict pour les cas ou le vaisseau est mesurable
    # PRESQUE PARTOUT et l'image de bonne qualite, mais ou le voisinage
    # immediat du minimum est degrade. Trois conditions cumulatives, aucune
    # relachee sur le fond :
    #   - la section du minimum est elle-meme fiable ;
    #   - le vaisseau est exploitable sur au moins `--frac-vaisseau` de sa
    #     longueur, ce qui atteste que le probleme est local et non global ;
    #   - le rehaussement median atteint `--hu-min-incertain`, faute de quoi le
    #     bord n'est pas detectable de facon fiable, quelle que soit la section.
    #
    # Le ratio est alors publie AVEC UNE INCERTITUDE ELARGIE et un verdict
    # distinct, jamais confondu avec une mesure pleine.
    frac_vaisseau = float(fiable.mean())
    hu_med = float(np.median(i_lum))
    #   - AUCUNE section ecartee ne presente un lumen nettement plus etroit
    #     que le minimum retenu. Sans ce garde-fou, on publierait un minimum
    #     dont on SAIT qu'il n'est pas le plus petit : sur un fantome a plaque
    #     calcifiee, la vraie lesion est rejetee et la chaine annoncerait 16 %
    #     la ou la verite est 64 %. Publier un minimum que l'on sait faux est
    #     pire qu'un refus.
    ecartees = np.isfinite(d_min) & ~fiable
    minimum_cache = bool(
        ecartees.any()
        and np.nanmin(d_min[ecartees]) < d_min[k] - args.tolerance_cache_mm)
    #   - le contour du minimum n'est pas anormalement LARGE par rapport a la
    #     reference distale. Le critere de coherence avec le masque compare
    #     d_eq au diametre inscrit ; si le masque englobe lui-meme une
    #     structure voisine — fuite deja presente dans la segmentation — les
    #     deux sont larges ensemble et le test ne se declenche pas. On ancre
    #     donc la verification sur d_ref, qui est mesure ailleurs et sur un
    #     segment sain : une carotide interne ne double pas de calibre a son
    #     point le plus serre.
    contour_trop_large = bool(
        np.isfinite(d_max[k]) and np.isfinite(d_ref) and d_ref > 0
        and d_max[k] > args.facteur_ref * d_ref)
    minimum_incertain = (not minimum_propre
                         and bool(fiable[k])
                         and not minimum_cache
                         and not contour_trop_large
                         and frac_vaisseau >= args.frac_vaisseau
                         and hu_med >= args.hu_min_incertain)

    # Sections dont le VOISINAGE ENTIER est exploitable. Une section fiable
    # isolee au milieu de sections rejetees n'est pas une mesure : c'est un
    # survivant statistique qui a franchi le seuil de quelques HU. C'est sur
    # cet ensemble, et non sur les sections fiables prises isolement, qu'on
    # calcule une borne basse defendable.
    entoure = np.zeros(len(s), bool)
    for i in np.where(fiable)[0]:
        v = np.abs(s - s[i]) <= args.voisinage_mm
        entoure[i] = bool(v.sum() >= 3) and bool(fiable[v].all())

    if pas_de_stenose:
        print(f"\n      >>> PAS DE STENOSE FOCALE")
        print(f"          Lumen minimal {d_min[k]:.2f} mm pour une reference "
              f"distale de {d_ref:.2f} mm")
        print(f"          ({100 * d_min[k] / d_ref:.0f} % de la reference). Le "
              f"vaisseau se reduit progressivement")
        print(f"          vers l'aval, sans retrecissement localise : NASCET "
              f"n'a pas d'objet ici.")
        print(f"\n      Mesure automatique, a confirmer par un radiologue.")
    elif zones_ko and not minimum_propre and minimum_incertain:
        nascet = 100 * (1 - d_min[k] / d_ref) if (np.isfinite(d_ref)
                                                  and d_ref > 0) else np.nan
        print(f"\n      >>> NASCET = {nascet:.0f} %  [MESURE INCERTAINE]")
        print(f"          Section du minimum fiable, vaisseau exploitable a "
              f"{100 * frac_vaisseau:.0f} %, rehaussement {hu_med:.0f} HU.")
        print(f"          Mais le voisinage immediat du minimum est degrade "
              f"({100 * frac_v:.0f} % exploitable).")
        print(f"          Aucune section ecartee n'est plus etroite que ce "
              f"minimum : il n'est pas masque.")
        print(f"          Un lumen residuel etroit degrade ses sections "
              f"voisines : ce verdict")
        print(f"          evite d'ecarter systematiquement les lesions les "
              f"plus serrees, au prix")
        print(f"          d'une incertitude elargie. Relecture visuelle "
              f"recommandee.")
        if d_min[k] < 2.0:
            print(f"          Lumen de {d_min[k]:.2f} mm : sous le calibre "
                  f"validee sur fantome, l'erreur")
            print(f"          attendue est d'environ six points au lieu de "
                  f"un a trois.")
    elif zones_ko and not minimum_propre:
        if contour_trop_large:
            print(f"\n      [!] Contour du minimum anormalement large : "
                  f"d_max {d_max[k]:.2f} mm pour une reference distale de "
                  f"{d_ref:.2f} mm ({d_max[k] / d_ref:.1f}x).")
            print(f"          Une carotide interne ne double pas de calibre a "
                  f"son point le plus serre :")
            print(f"          le contour englobe probablement une structure "
                  f"voisine. Aucune valeur publiee.")
        if minimum_cache:
            print(f"\n      [!] Une section ecartee presente un lumen plus "
                  f"etroit ({np.nanmin(d_min[ecartees]):.2f} mm) que le "
                  f"minimum retenu ({d_min[k]:.2f} mm).")
            print(f"          Le point le plus serre n'est donc pas mesurable : "
                  f"aucune valeur, meme incertaine, ne peut etre publiee.")
        print(f"\n      /!\\ {len(zones_ko)} zone(s) NON MESURABLE(S) :")
        for a, b in zones_ko:
            print(f"          coupes {z_vox[a]:.0f}-{z_vox[b]:.0f} "
                  f"(s {s[a]:.1f}-{s[b]:.1f} mm), "
                  f"circonference lisible {100 * frac_ok[a:b + 1].min():.0f}-"
                  f"{100 * frac_ok[a:b + 1].max():.0f} %")
        # On nomme la cause DOMINANTE plutot que de toujours accuser le
        # calcium : selon les cas c'est le blooming, un axe sorti du lumen, ou
        # un contour incoherent, et la conduite a tenir n'est pas la meme.
        dans_ko = np.zeros(len(s), bool)
        for a, b in zones_ko:
            dans_ko[a:b + 1] = True
        causes = {nom: int((m & dans_ko).sum()) for nom, m in crit.items()}
        principale = max(causes, key=causes.get)
        print(f"\n      >>> NASCET NON CALCULABLE.")
        print(f"          Cause dominante : {principale}")
        for nom, n in sorted(causes.items(), key=lambda kv: -kv[1]):
            if n:
                print(f"            {nom} : {n} section(s)")
        if "rehaussement" in principale:
            print(f"          L'axe ne suit pas le lumen sur cette portion —")
            print(f"          verifier 20_projection.png et 30_mpr.png. Si le")
            print(f"          vaisseau est visible sur le CT, un point de")
            print(f"          reperage manuel dans la zone reglerait le suivi.")
        else:
            print(f"          Relecture manuelle indispensable ; envisager une")
            print(f"          autre modalite (echo-doppler, ARM).")
        if entoure.any() and np.isfinite(d_ref) and d_ref > 0:
            ks = int(np.argmin(np.where(entoure, d_min, np.inf)))
            print(f"\n          BORNE BASSE defendable, mesuree hors des zones")
            print(f"          douteuses (coupe {z_vox[ks]:.0f}, voisinage propre) :")
            print(f"            d_min {d_min[ks]:.2f} mm / ref {d_ref:.2f} mm "
                  f"-> NASCET >= {100 * (1 - d_min[ks] / d_ref):.0f} %")
            print(f"          La stenose reelle est plus serree : son point le")
            print(f"          plus etroit tombe dans la zone non mesurable.")
        else:
            print(f"\n          Aucune section exploitable avec un voisinage")
            print(f"          propre : pas de borne basse defendable.")
    elif np.isfinite(d_ref) and d_ref > 0:
        nascet = 100 * (1 - d_min[k] / d_ref)
        # correction du biais calculee ici : elle sert au bloc NASCET ET au
        # bloc ECST qui suit, pour comparer la propagation dans les deux ratios
        d_corr = 100 * (1 - max(d_min[k] - DELTA_FWHM_MM, 1e-6)
                        / max(d_ref - DELTA_FWHM_MM, 1e-6))
        print(f"\n      >>> NASCET = {nascet:.0f} %  "
              f"(1 - {d_min[k]:.2f}/{d_ref:.2f})")
        if np.isfinite(ecst_interp):
            print(f"      >>> ECST ESTIME = {ecst_interp:.0f} %  "
                  f"(1 - {d_min[k]:.2f}/{d_bulbe:.2f})")
            print(f"          Seuil ECST equivalent a 70 % NASCET : ~82-84 %")
            # REPERE DE LECTURE, PAS CONTROLE. La relation de Rothwell (Stroke
            # 1994) est une regression empirique entre deux mesures faites sur
            # les memes arteriographies : elle decrit une tendance de
            # population, avec une dispersion residuelle autour de la droite.
            # Un ecart de quelques points entre l'ECST mesure et celui predit
            # par conversion n'est donc PAS un defaut de la chaine — il peut
            # tenir dans les limites de l'accord. Les deux valeurs sont
            # affichees cote a cote, aucune ne valide l'autre.
            print(f"          Repere de population (Rothwell 1994, "
                  f"ECST = 0,6 x NASCET + 40) : {0.6 * nascet + 40:.0f} % "
                  f"— tendance, pas attendu individuel")
            # Propagation du biais dans ECST. Numerateur et denominateur sont
            # ici deux diametres mesures AU MEME NIVEAU, et l'interpolation
            # reporte delta dans le denominateur aussi. Le rapport d/D est plus
            # proche de 1 que dans NASCET, donc la perte au seuil est plus
            # faible en valeur absolue.
            e_corr = 100 * (1 - max(d_min[k] - DELTA_FWHM_MM, 1e-6)
                            / max(d_bulbe - DELTA_FWHM_MM, 1e-6))
            # Propagation du biais : peu informative au voisinage du seuil
            # chirurgical, ou les deux criteres convergent (l'ecart NASCET/ECST
            # est maximal pour les stenoses moderees et se reduit quand la
            # lesion se serre). Le contraste entre les deux criteres se situe
            # donc en zone 40-60 %, la ou la decision clinique depend le moins
            # d'un point de pourcentage. Note secondaire, pas un resultat.
            print(f"          Correction du biais : {e_corr:.0f} % "
                  f"(perte {e_corr - ecst_interp:+.1f} pt, contre "
                  f"{d_corr - nascet:+.1f} pt pour NASCET)")
        print(f"          minimum fiable, voisinage +/-{args.voisinage_mm:.0f} mm "
              f"exploitable a {100 * frac_v:.0f} % "
              f"({int(fiable[voisin].sum())}/{int(voisin.sum())} sections)")
        # BIAIS SYSTEMATIQUE. Le FWHM surestime chaque diametre d'environ
        # +0,19 mm (mesure sur fantome, ecart-type 0,05). Un decalage constant
        # applique au numerateur ET au denominateur NE S'ANNULE PAS dans le
        # ratio : 1-(d_s+delta)/(d_r+delta) est toujours INFERIEUR a 1-d_s/d_r
        # des lors que d_r > d_s. La perte est de 2 a 3 points autour de 70 %.
        # Ce n'est donc pas de l'imprecision, c'est une sous-estimation
        # previsible — et 70 % est le seuil decisionnel.
        print(f"\n      /!\\ Le FWHM surestime les diametres d'environ "
              f"{DELTA_FWHM_MM:.2f} mm (fantome).")
        print(f"          Ce decalage ne s'annule PAS dans le ratio : il le tire")
        print(f"          vers le bas. Valeur ci-dessus a lire comme une BORNE")
        print(f"          BASSE ; apres correction indicative : {d_corr:.0f} %.")
        if min(nascet, d_corr) < 70 <= max(nascet, d_corr):
            print(f"          [!] La correction fait FRANCHIR le seuil de 70 %.")
            print(f"              Cas a faire relire en priorite.")
        if d_min[k] < 2.0:
            print(f"\n      /!\\ {d_min[k]:.2f} mm = "
                  f"{d_min[k] / vox_plan:.1f} voxels : sous le calibre validee sur")
            print(f"          fantome (1,5 mm). La position est sure, la valeur")
            print(f"          est au bord de la resolution — le ratio peut varier")
            print(f"          de plusieurs points. Confirmation visuelle requise.")
        if zones_ko:
            print(f"\n      /!\\ {len(zones_ko)} zone(s) NON EXPLOREE(S), a distance")
            print(f"          du minimum. Elles ne faussent pas la mesure ci-dessus")
            print(f"          mais pourraient masquer une seconde lesion :")
            for a, b in zones_ko:
                print(f"            coupes {z_vox[a]:.0f}-{z_vox[b]:.0f}")
        if np.isfinite(nascet_aire):
            print(f"\n      >>> STENOSE EN AIRE = {nascet_aire:.0f} %  "
                  f"(1 - ({d_eq[k_aire]:.2f}/{d_ref_aire:.2f})^2)")
            print(f"          NON RETENU COMME MESURE : le calibre au niveau "
                  f"de la lesion n'est pas")
            print(f"          identifiable a partir de l'image (paroi externe "
                  f"non discernable du")
            print(f"          tissu peri-arteriel). Valeur conservee pour "
                  f"tracabilite uniquement.")
            print(f"          Agrege les {args.n_angles} rayons au lieu d'un "
                  f"seul caliper : plus robuste sur lumen etroit.")
            print(f"          ATTENTION : une stenose en AIRE est toujours "
                  f"superieure a la meme")
            print(f"          lesion en DIAMETRE (50 % en diametre = 75 % en "
                  f"aire). Le seuil")
            print(f"          de 70 % ayant ete valide sur des diametres, ces "
                  f"deux valeurs ne")
            print(f"          se comparent PAS entre elles.")
            if k_aire != k:
                print(f"          [i] Minimum d'aire a s={s[k_aire]:.1f} mm "
                      f"(coupe {z_vox[k_aire]:.0f}), distinct du minimum de "
                      f"diametre a s={s[k]:.1f} mm.")
        if np.isfinite(d_min_strict[k]) and np.isfinite(d_ref) and d_ref > 0:
            n_str = 100 * (1 - d_min_strict[k] / d_ref)
            print(f"\n      Minimum STRICT (plus petit caliper, sans "
                  f"percentile) : {d_min_strict[k]:.2f} mm")
            print(f"          -> NASCET strict {n_str:.0f} % contre "
                  f"{nascet:.0f} % robuste, ecart {n_str - nascet:+.1f} pt.")
            print(f"          Un ecart faible atteste que la mesure ne repose "
                  f"pas sur un rayon isole.")
        print(f"\n      Mesure automatique, a confirmer par un radiologue.")

    # --- 4. Sorties --------------------------------------------------------
    print("\n[4/4] Ecriture des sorties")
    f_csv = sortie / "profil_fwhm.csv"
    with open(f_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["i", "s_mm", "z_voxel", "d_min_mm", "d_eq_mm", "d_max_mm",
                    "d_inscrit_mm", "n_rayons_ok", "n_rayons_calcium",
                    "fraction_exploitable", "fiable", "HU_lumen", "source"])
        for i in range(len(s)):
            w.writerow([i, round(float(s[i]), 2), round(float(z_vox[i]), 1),
                        "" if not np.isfinite(d_min[i]) else round(float(d_min[i]), 3),
                        "" if not np.isfinite(d_eq[i]) else round(float(d_eq[i]), 3),
                        "" if not np.isfinite(d_max[i]) else round(float(d_max[i]), 3),
                        round(float(d_ins[i]), 3), int(n_ok[i]), int(n_cal[i]),
                        round(float(frac_ok[i]), 3), "oui" if fiable[i] else "non",
                        round(float(i_lum[i]), 1), "segmente"])
    print(f"    {f_csv}")

    if args.csv:
        f_syn = Path(args.csv)
        neuf = not f_syn.exists()
        cols = ["patient", "cote", "nascet_pct", "verdict",
                "d_min_mm", "d_ref_mm", "d_bulbe_mm", "z_minimum",
                "n_sections", "n_retenues", "pct_retenues",
                "frac_vaisseau_pct", "frac_voisinage_pct",
                "n_zones_douteuses", "cause_dominante",
                "hu_lumen_median", "obliquite_mediane", "espacement_mm",

                "nascet_strict_pct", "d_min_strict_mm",
                "stenose_aire_pct", "d_eq_min_mm", "d_ref_aire_mm",
                # colonnes EXPLORATOIRES : correction d'un biais estime sur
                # fantome, dependant de la PSF et du rehaussement propres a
                # chaque acquisition. Ne pas les substituer aux colonnes
                # principales nascet_pct / ecst_interp_pct.
                "expl_nascet_corrige_biais", "expl_ecst_corrige_biais",
                # ECST : NON RETENU COMME MESURE. Trois strategies d'estimation
                # du calibre au niveau de la lesion ont ete evaluees ; le
                # garde-fou de plausibilite restait actif dans 43 % des cas,
                # au-dela du seuil de 20 % fixe a priori. La paroi externe
                # n'etant pas discernable du tissu peri-arteriel en
                # angioscanner, la position de reference n'est pas identifiable
                # a partir de l'image. Colonnes conservees pour la tracabilite
                # de l'analyse methodologique, PAS pour les conclusions.
                "expl_ecst_pct", "expl_ecst_borne",
                "ecart_rothwell_pt", "ecst_incoherent"]
        publie = ((bool(zones_ko) is False or minimum_propre
                   or minimum_incertain) and not pas_de_stenose)
        cause = ""
        if zones_ko and not minimum_propre:
            cause = max({n: int((m & dans_ko).sum())
                         for n, m in crit.items()}.items(),
                        key=lambda kv: kv[1])[0] if 'dans_ko' in dir() else ""
        ang_med = float(np.median(angle_axe)) if len(angle_axe) else ""
        lig = {
            "patient": patient, "cote": args.cote,
            "nascet_pct": round(100 * (1 - d_min[k] / d_ref), 1)
                          if (publie and np.isfinite(d_ref)) else "",
            "expl_ecst_pct": round(float(ecst_interp), 1)
                             if (publie and np.isfinite(ecst_interp)) else "",
            "expl_ecst_borne": "oui" if borne_bulbe_active else "non",
            # ORDRE DES TESTS. `publie` englobe les mesures incertaines pour
            # que les colonnes chiffrees soient remplies ; le verdict doit
            # donc tester l'incertitude AVANT le cas general, sinon la
            # categorie intermediaire n'est jamais atteinte et les cas
            # recuperes sont indiscernables des mesures fermes.
            "verdict": ("pas_de_stenose" if pas_de_stenose
                        else "mesure_incertaine" if minimum_incertain
                        else "mesure" if publie
                        else "non_calculable"),
            "frac_vaisseau_pct": round(100 * frac_vaisseau, 1),
            "frac_voisinage_pct": round(100 * frac_v, 1),
            "d_min_mm": round(float(d_min[k]), 3),
            "d_ref_mm": round(float(d_ref), 3) if np.isfinite(d_ref) else "",
            "d_bulbe_mm": round(float(d_bulbe), 3) if np.isfinite(d_bulbe) else "",
            "z_minimum": round(float(z_vox[k]), 1),
            "n_sections": len(s), "n_retenues": int(fiable.sum()),
            "pct_retenues": round(100 * fiable.mean(), 1),
            "n_zones_douteuses": len(zones_ko),
            "cause_dominante": cause,
            "hu_lumen_median": round(float(np.median(i_lum)), 0),
            "obliquite_mediane": round(ang_med, 1) if ang_med != "" else "",

            "espacement_mm": "/".join(f"{v:.4f}" for v in zooms_ct),
            "nascet_strict_pct": round(
                float(100 * (1 - d_min_strict[k] / d_ref)), 1)
                if (publie and np.isfinite(d_min_strict[k])
                    and np.isfinite(d_ref) and d_ref > 0) else "",
            "d_min_strict_mm": round(float(d_min_strict[k]), 3)
                               if np.isfinite(d_min_strict[k]) else "",
            "stenose_aire_pct": round(float(nascet_aire), 1)
                                if np.isfinite(nascet_aire) else "",
            "d_eq_min_mm": round(float(d_eq[k_aire]), 3)
                           if (k_aire is not None
                               and np.isfinite(d_eq[k_aire])) else "",
            "d_ref_aire_mm": round(float(d_ref_aire), 3)
                             if np.isfinite(d_ref_aire) else "",
            "expl_nascet_corrige_biais": round(
                100 * (1 - max(d_min[k] - DELTA_FWHM_MM, 1e-6)
                       / max(d_ref - DELTA_FWHM_MM, 1e-6)), 1)
                if (publie and np.isfinite(d_ref)) else "",
            "expl_ecst_corrige_biais": round(
                100 * (1 - max(d_min[k] - DELTA_FWHM_MM, 1e-6)
                       / max(d_bulbe - DELTA_FWHM_MM, 1e-6)), 1)
                if (publie and np.isfinite(ecst_interp)) else "",
            # CONTROLE DE COHERENCE INTERNE. NASCET et ECST sont mesures sur la
            # MEME section par la MEME chaine : leur couple doit s'aligner sur
            # la droite de Rothwell. Un point qui s'en ecarte franchement
            # signale que d_ref (distal) et le calibre interpole au niveau de
            # la lesion sont incoherents entre eux — presque toujours un
            # probleme de PLACEMENT DU POINT DE REFERENCE, qui est le maillon
            # le moins contraint de la chaine. Sur le nuage de la cohorte,
            # les points aberrants designent les cas a reinspecter.
            "ecart_rothwell_pt": round(
                float(ecst_interp - (0.6 * (100 * (1 - d_min[k] / d_ref)) + 40)), 1)
                if (publie and np.isfinite(ecst_interp)
                    and np.isfinite(d_ref)) else "",
            "ecst_incoherent": ("oui" if (publie and np.isfinite(ecst_interp)
                                and np.isfinite(d_ref)
                                and abs(ecst_interp - (0.6 * (100 * (1 - d_min[k] / d_ref)) + 40)) > 15)
                                else "non") if (publie and np.isfinite(ecst_interp)) else "",
        }
        with open(f_syn, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=";")
            if neuf:
                w.writeheader()
            w.writerow(lig)
        print(f"    ligne ajoutee a {f_syn}")
    if args.sans_figures:
        print()
        return

    titre = f"{patient} — CI {args.cote}"
    _fig_mpr(prof_all, r, angles, s, d_min, k, sortie, titre)
    _fig_sections(prof_all, r, angles, tous_rayons, s, z_vox, k, sortie, titre)
    _fig_comparaison(s, d_min, d_eq, d_max, d_ins, n_cal, k, d_ref, sortie, titre)
    _fig_stenose(prof_all, r, angles, tous_rayons, s, z_vox, d_min, d_max, k,
                 seuil_cal[k], sortie, titre)
    for n in ["30_mpr.png", "31_sections.png", "32_comparaison.png",
              "33_stenose.png"]:
        print(f"    {sortie / n}")
    print()


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _fig_mpr(prof, r, angles, s, d_min, k, dossier, titre):
    """MPR curvilignes : le vaisseau "deroule" le long de son axe.

    Pour un angle donne theta, on colle le rayon theta et le rayon oppose : on
    obtient une coupe longitudinale qui suit le vaisseau. C'est la vue dont se
    sert un radiologue pour juger une stenose, et le meilleur controle visuel de
    toute la chaine.
    """
    fig, axs = plt.subplots(2, 1, figsize=(13, 6))
    n_ang = len(angles)
    for ax, j in zip(axs, [0, n_ang // 4]):
        opp = (j + n_ang // 2) % n_ang
        img = np.concatenate([prof[:, opp, ::-1], prof[:, j, :]], axis=1).T
        etendue = [s[0], s[-1], -r[-1], r[-1]]
        ax.imshow(img, cmap="gray", vmin=-100, vmax=700, origin="lower",
                  extent=etendue, aspect="auto")
        ax.axvline(s[k], color="crimson", ls="--", lw=1)
        ax.set_ylabel("distance a l'axe (mm)")
        ax.set_title(f"MPR curviligne, angle {np.degrees(angles[j]):.0f} deg",
                     fontsize=9)
    axs[1].set_xlabel("abscisse curviligne le long de l'axe (mm)")
    fig.suptitle(f"{titre} — vaisseau deroule (trait rouge = section la plus serree)")
    fig.tight_layout()
    fig.savefig(dossier / "30_mpr.png", dpi=130)
    plt.close(fig)


def _polaire_vers_image(prof_i, r, angles, taille=121):
    """Reconstruit une image cartesienne de la section a partir du polaire."""
    lin = np.linspace(-r[-1], r[-1], taille)
    Xg, Yg = np.meshgrid(lin, lin)
    rad = np.hypot(Xg, Yg)
    th = np.mod(np.arctan2(Yg, Xg), 2 * np.pi)
    ir = rad / (r[1] - r[0])
    ia = th / (angles[1] - angles[0])
    return ndimage.map_coordinates(prof_i, [ia, ir], order=1, mode="nearest"), lin


def _fig_sections(prof, r, angles, rayons, s, z_vox, k, dossier, titre, n=6):
    idx = sorted(set(list(np.linspace(0, len(s) - 1, n - 1).astype(int)) + [k]))
    fig, axs = plt.subplots(2, (len(idx) + 1) // 2,
                            figsize=(2.8 * ((len(idx) + 1) // 2), 6))
    for ax, i in zip(np.atleast_1d(axs).ravel(), idx):
        img, lin = _polaire_vers_image(prof[i], r, angles)
        ax.imshow(img, cmap="gray", vmin=-100, vmax=700, origin="lower",
                  extent=[lin[0], lin[-1], lin[0], lin[-1]])
        ok = np.isfinite(rayons[i])
        if ok.any():
            a, rr = angles[ok], rayons[i][ok]
            ax.plot(np.append(rr * np.cos(a), rr[0] * np.cos(a[0])),
                    np.append(rr * np.sin(a), rr[0] * np.sin(a[0])),
                    "-", color="lime", lw=1.3)
        ax.plot(0, 0, "r+", ms=8, mew=1.5)
        ax.set_title(f"s={s[i]:.0f} mm (z={z_vox[i]:.0f})"
                     + ("  <-- min" if i == k else ""), fontsize=8,
                     color="crimson" if i == k else "black")
        ax.set_xticks([]); ax.set_yticks([])
    for ax in np.atleast_1d(axs).ravel()[len(idx):]:
        ax.axis("off")
    fig.suptitle(f"{titre} — sections PERPENDICULAIRES, bord FWHM en vert")
    fig.tight_layout()
    fig.savefig(dossier / "31_sections.png", dpi=130)
    plt.close(fig)


def _fig_comparaison(s, d_min, d_eq, d_max, d_ins, n_cal, k, d_ref, dossier, titre):
    fig, ax = plt.subplots(figsize=(12, 5))
    cal = n_cal > 0
    if cal.any():
        ax.fill_between(s, 0, 1, where=cal, transform=ax.get_xaxis_transform(),
                        color="gold", alpha=.20, label="calcium detecte")
    ax.plot(s, d_ins, "-", color="silver", lw=1.2, label="diametre inscrit (masque)")
    ax.plot(s, d_eq, "-", color="steelblue", lw=1.2, label="FWHM, equivalent")
    ax.plot(s, d_min, "-", color="seagreen", lw=2.0, label="FWHM, minimal (NASCET)")
    if np.isfinite(d_ref):
        ax.axhline(d_ref, ls=":", color="dimgray", lw=1.2,
                   label=f"reference distale {d_ref:.2f} mm")
    ax.plot(s[k], d_min[k], "v", color="crimson", ms=10)
    ax.annotate(f"{d_min[k]:.2f} mm", (s[k], d_min[k]), textcoords="offset points",
                xytext=(8, -12), color="crimson", fontsize=10)
    ax.set_xlabel("abscisse curviligne le long de l'axe (mm)")
    ax.set_ylabel("diametre (mm)")
    ax.grid(alpha=.3)
    ax.legend(fontsize=8, loc="upper right", ncol=2)
    fig.suptitle(f"{titre} — FWHM sur coupes perpendiculaires vs masque")
    fig.tight_layout()
    fig.savefig(dossier / "32_comparaison.png", dpi=130)
    plt.close(fig)


def _fig_stenose(prof, r, angles, rayons, s, z_vox, d_min, d_max, k, seuil_cal,
                 dossier, titre):
    fig, axs = plt.subplots(1, 3, figsize=(14, 4.6))
    img, lin = _polaire_vers_image(prof[k], r, angles)
    axs[0].imshow(img, cmap="gray", vmin=-100, vmax=900, origin="lower",
                  extent=[lin[0], lin[-1], lin[0], lin[-1]])
    ok = np.isfinite(rayons[k])
    a, rr = angles[ok], rayons[k][ok]
    axs[0].plot(np.append(rr * np.cos(a), rr[0] * np.cos(a[0])),
                np.append(rr * np.sin(a), rr[0] * np.sin(a[0])), "-",
                color="lime", lw=1.6)
    axs[0].plot(0, 0, "r+", ms=10, mew=2)
    axs[0].set_title(f"section la plus serree — z={z_vox[k]:.0f}\n"
                     f"d_min {d_min[k]:.2f} / d_max {d_max[k]:.2f} mm", fontsize=9)

    axs[1].imshow(prof[k], cmap="gray", vmin=-100, vmax=900, origin="lower",
                  aspect="auto", extent=[0, r[-1], 0, 360])
    axs[1].plot(rayons[k], np.degrees(angles), ".", color="lime", ms=2)
    axs[1].set_xlabel("rayon (mm)"); axs[1].set_ylabel("angle (deg)")
    axs[1].set_title("carte polaire (bord detecte en vert)", fontsize=9)

    for j in np.linspace(0, len(angles) - 1, 6).astype(int):
        axs[2].plot(r, prof[k][j], lw=1, alpha=.8,
                    label=f"{np.degrees(angles[j]):.0f} deg")
    axs[2].axhline(float(np.atleast_1d(seuil_cal)[0]), ls="--", color="orange",
                   lw=1, label="seuil calcium")
    axs[2].set_xlabel("rayon (mm)"); axs[2].set_ylabel("HU")
    axs[2].set_title("profils radiaux bruts", fontsize=9)
    axs[2].legend(fontsize=6, ncol=2)
    axs[2].grid(alpha=.3)

    fig.suptitle(f"{titre} — analyse de la section minimale")
    fig.tight_layout()
    fig.savefig(dossier / "33_stenose.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()