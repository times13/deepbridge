#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etape2c_centerline_geodesique.py — DeepBridge, etape 2 / increment 1.5b.

Remplace le centroide-par-coupe de l'increment 1 par un CHEMIN GEODESIQUE
calcule dans le volume du masque.

POURQUOI
--------
Le centroide par coupe suppose qu'une coupe axiale ne traverse le vaisseau
qu'une fois. Des que ce n'est plus vrai — bifurcation, boucle, plicature — la
regle "plus grosse region" bascule d'une section a l'autre et l'axe se
teleporte. Aucun reglage ne corrige ca : c'est l'hypothese de depart qui est
fausse.

Un chemin geodesique ne fait aucune hypothese sur l'orientation. On cherche le
plus court chemin entre deux extremites, A TRAVERS le masque, avec un cout qui
penalise les voxels proches de la paroi. Le chemin obtenu longe naturellement
le centre du vaisseau, suit les replis, et — point decisif — IGNORE LES CULS-DE-
SAC : une branche qui ne mene pas a l'arrivee n'est jamais empruntee. Le
moignon de carotide externe present dans le label est donc ecarte tout seul.

METHODE
-------
1. Transformee de distance (en mm) : pour chaque voxel du masque, distance a la
   paroi la plus proche. Le maximum local = le centre du vaisseau.
2. Cout d'un pas = longueur du pas (mm) x (dt_max / dt)^alpha. Plus on s'ecarte
   du centre, plus c'est cher. alpha regle la fermete du recentrage.
3. Dijkstra en connectivite 26 entre le voxel le plus central de la coupe de
   depart et celui de la coupe d'arrivee.
4. Lissage Savitzky-Golay, reechantillonnage a pas constant, tangentes.

BONUS : diametre inscrit = 2 x dt le long de l'axe. C'est le diametre de la
plus grosse sphere centree sur l'axe qui tient dans le masque. Contrairement au
diametre equivalent d'une coupe axiale, il est INSENSIBLE A L'OBLIQUITE, parce
qu'il est calcule en 3D. Ce n'est pas encore la mesure FWHM sur le CT (il reste
tributaire du masque), mais c'est deja une estimation honnete.

Sorties (dans <out>/<patient>_<cote>/) :
  centerline_geo.csv    meme format que l'increment 1, + diametre inscrit
  20_projection.png     masque projete + axe geodesique
  21_lissage.png        chemin brut (escalier) vs lisse
  22_profil.png         diametre inscrit + obliquite, zones de branche grisees
  23_coupes.png         coupes de controle avec le point d'axe

Usage :
  python etape2c_centerline_geodesique.py --patient "C:\\Projetsss\\Resultats\\1359673019" ^
        --cote gauche --out "C:\\Projetsss\\etape2"

Prerequis : nibabel, numpy, scipy, matplotlib
"""

import argparse
import csv
import heapq
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
matplotlib.use("Agg")
import matplotlib.pyplot as plt


COTES = {"gauche": "left", "droite": "right"}


class _CommuneVide(Exception):
    """Le label de carotide commune existe mais ne contient aucun voxel."""


def axe_z(img) -> int:
    try:
        for i, c in enumerate(nib.aff2axcodes(img.affine)):
            if c in ("S", "I"):
                return i
    except Exception:
        pass
    return 2


def coupe_2d(dataobj, iz, z):
    sl = [slice(None)] * 3
    sl[iz] = int(z)
    return np.asarray(dataobj[tuple(sl)], dtype=np.float32)


# ---------------------------------------------------------------------------
# Chemin geodesique
# ---------------------------------------------------------------------------

def boite(masque, marge=8):
    """Boite englobante du masque, elargie d'une marge de securite.

    distance_transform_edt alloue 3 tableaux float64 de la taille du VOLUME
    ENTIER, meme si le masque n'en occupe qu'un millieme : sur un volume de
    512x512x1622 cela represente 9,5 Go. Or la carotide tient dans une boite
    de quelques centimetres de cote. On recadre donc avant, et on replace les
    coordonnees dans le repere d'origine ensuite.

    La marge evite que la paroi de la boite soit prise pour une paroi du
    vaisseau par la transformee de distance.
    """
    idx = np.argwhere(masque)
    lo = np.maximum(idx.min(axis=0) - marge, 0)
    hi = np.minimum(idx.max(axis=0) + marge + 1, np.array(masque.shape))
    return tuple(slice(int(a), int(b)) for a, b in zip(lo, hi)), lo


def dt_locale(masque, zooms, marge=8):
    """Transformee de distance calculee sur la boite englobante seulement.

    Retourne un tableau de la taille du volume d'origine (rempli de zeros hors
    boite), pour que le reste du code n'ait pas a connaitre le recadrage.
    """
    sl, _ = boite(masque, marge)
    dt = np.zeros(masque.shape, dtype=np.float32)
    dt[sl] = ndimage.distance_transform_edt(masque[sl],
                                            sampling=zooms).astype(np.float32)
    return dt


def graine_centrale(dt, iz, z, jitter=0, rng=None):
    """Voxel le plus central de la coupe z (max de la transformee de distance).

    On prend le maximum de dt et NON le centroide : sur une section en croissant
    ou en haltere, le centroide peut tomber hors du masque, ce qui rendrait la
    graine inutilisable.
    """
    sl = [slice(None)] * 3
    sl[iz] = int(z)
    tranche = dt[tuple(sl)]
    if tranche.max() <= 0:
        return None
    if jitter > 0 and rng is not None:
        # PERTURBATION DE LA GRAINE. Le choix du voxel de depart est de
        # l'arbitraire d'implementation pur : un autre auteur aurait pris le
        # centroide, ou le maximum d'un dt lisse. Deplacer la graine de
        # quelques voxels et relancer donne donc une dispersion qui repond a
        # "un autre operateur aurait-il trouve la meme chose ?", sans toucher
        # au rapport signal/bruit de l'image.
        cand = np.argwhere(tranche > 0.5 * tranche.max())
        plat0 = np.unravel_index(int(np.argmax(tranche)), tranche.shape)
        d = np.linalg.norm(cand - np.array(plat0), axis=1)
        proches = cand[d <= jitter]
        if len(proches):
            a, b = proches[rng.integers(len(proches))]
        else:
            a, b = plat0
    else:
        plat = int(np.argmax(tranche))
        a, b = np.unravel_index(plat, tranche.shape)
    p = [0, 0, 0]
    p[iz] = int(z)
    autres = [k for k in range(3) if k != iz]
    p[autres[0]], p[autres[1]] = int(a), int(b)
    return tuple(p)


def dijkstra(masque, dt, zooms, depart, arrivee, alpha=3.0, marge=8):
    """Enveloppe : recadre sur la boite englobante, puis appelle le coeur.

    Dijkstra alloue trois tableaux de la taille du VOLUME (poids, cout,
    parent), soit une dizaine de gigaoctets sur un volume de 512x512x1622 dont
    le masque n'occupe qu'un dix-millieme. On recadre, on calcule, et on
    replace les coordonnees dans le repere d'origine.
    """
    sl, lo = boite(masque, marge)
    dep = tuple(int(depart[i] - lo[i]) for i in range(3))
    arr = tuple(int(arrivee[i] - lo[i]) for i in range(3))
    chemin = _dijkstra_coeur(masque[sl], dt[sl], zooms, dep, arr, alpha)
    return chemin + lo


def _dijkstra_coeur(masque, dt, zooms, depart, arrivee, alpha=3.0):
    """Plus court chemin dans le masque, cout penalisant la proximite a la paroi.

    Connectivite 26 : les 26 voisins du cube 3x3x3. La longueur reelle de chaque
    pas est calculee en millimetres a partir de l'espacement, sinon un pas
    diagonal serait compte comme un pas droit et le chemin prendrait des
    raccourcis en escalier.
    """
    forme = masque.shape
    # Table des deplacements et de leur longueur en mm
    voisins = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == dy == dz == 0:
                    continue
                lg = np.sqrt((dx * zooms[0]) ** 2 + (dy * zooms[1]) ** 2
                             + (dz * zooms[2]) ** 2)
                voisins.append((dx, dy, dz, lg))

    dt_max = float(dt.max())
    eps = 1e-3
    # Poids par voxel, precalcule : 1 au centre du plus gros vaisseau, >1 ailleurs
    poids = np.where(masque, (dt_max / np.maximum(dt, eps)) ** alpha, np.inf)

    idx = lambda p: (p[0] * forme[1] + p[1]) * forme[2] + p[2]
    cout = np.full(forme, np.inf, dtype=np.float64)
    parent = np.full(int(np.prod(forme)), -1, dtype=np.int64)
    vu = np.zeros(forme, dtype=bool)

    cout[depart] = 0.0
    tas = [(0.0, depart)]
    while tas:
        c, p = heapq.heappop(tas)
        if vu[p]:
            continue
        vu[p] = True
        if p == arrivee:
            break
        x, y, z = p
        for dx, dy, dz, lg in voisins:
            q = (x + dx, y + dy, z + dz)
            if not (0 <= q[0] < forme[0] and 0 <= q[1] < forme[1]
                    and 0 <= q[2] < forme[2]):
                continue
            if not masque[q] or vu[q]:
                continue
            # cout du pas : longueur x poids moyen des deux extremites
            nc = c + lg * 0.5 * (poids[p] + poids[q])
            if nc < cout[q]:
                cout[q] = nc
                parent[idx(q)] = idx(p)
                heapq.heappush(tas, (nc, q))

    if not np.isfinite(cout[arrivee]):
        sys.exit("[ERREUR] Aucun chemin entre les deux extremites dans le masque.")

    # Remontee du chemin
    chemin = []
    cur = idx(arrivee)
    d_ = idx(depart)
    while cur != -1:
        z = cur % forme[2]
        y = (cur // forme[2]) % forme[1]
        x = cur // (forme[2] * forme[1])
        chemin.append((x, y, z))
        if cur == d_:
            break
        cur = parent[cur]
    return np.array(chemin[::-1], dtype=float)


# ---------------------------------------------------------------------------
# Lissage / reechantillonnage (identique a l'increment 1)
# ---------------------------------------------------------------------------

def uniformiser(points_mm, pas_mm):
    d = np.linalg.norm(np.diff(points_mm, axis=0), axis=1)
    garde = np.concatenate([[True], d > 1e-9])
    points_mm = points_mm[garde]
    d = np.linalg.norm(np.diff(points_mm, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(d)])
    s_cible = np.arange(0.0, s[-1] + 1e-9, pas_mm)
    return np.column_stack([interp1d(s, points_mm[:, k])(s_cible) for k in range(3)])


def lisser_reechantillonner(points_mm, pas_mm, fenetre_mm):
    """Uniformise, lisse, puis reparametrise par la vraie longueur d'arc.

    Le chemin issu de Dijkstra est en escalier : il saute de voxel en voxel. Le
    lissage doit donc etre un peu plus ferme qu'a l'increment 1, mais pas trop :
    une fenetre trop large arrondirait la sortie de stenose.
    """
    p = uniformiser(points_mm, pas_mm)
    f = int(round(fenetre_mm / pas_mm))
    f = f if f % 2 == 1 else f + 1
    if f > len(p):
        f = len(p) if len(p) % 2 == 1 else len(p) - 1
    if f > 3:
        p = np.column_stack([savgol_filter(p[:, k], f, 2) for k in range(3)])

    d = np.linalg.norm(np.diff(p, axis=0), axis=1)
    t = np.concatenate([[0.0], np.cumsum(d)])
    spl = CubicSpline(t, p, axis=0)
    t_fin = np.linspace(t[0], t[-1], max(2000, 10 * len(p)))
    p_fin = spl(t_fin)
    s_fin = np.concatenate([[0.0],
                            np.cumsum(np.linalg.norm(np.diff(p_fin, axis=0), axis=1))])
    s_cible = np.arange(0.0, s_fin[-1] + 1e-9, pas_mm)
    t_cible = interp1d(s_fin, t_fin)(s_cible)
    pts = spl(t_cible)
    tan = spl(t_cible, 1)
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    return pts, tan, s_cible


def echantillonner_dt(dt, zooms, points_vox):
    """Lit la transformee de distance aux positions (sous-voxel) de l'axe.

    map_coordinates fait une interpolation trilineaire : sans elle, le profil
    de diametre serait en marches d'escalier au pas du voxel.
    """
    return ndimage.map_coordinates(dt, points_vox.T, order=1, mode="nearest")


def distance_laterale(et, i, j, iz, mm_plan):
    """Distance entre deux composantes DANS leur plage de z commune.

    Le recouvrement en z ne suffit pas a conclure a une fuite. Deux troncons
    d'un MEME vaisseau, places bout a bout, ont des plages de z qui se
    chevauchent des que le raccord est oblique : le bas de l'un et le haut de
    l'autre occupent alors les memes coupes tout en etant au meme endroit.
    Une vraie fuite, elle, met deux vaisseaux COTE A COTE : leurs centres sont
    separes de plusieurs millimetres dans le plan.

    C'est donc la distance laterale, et non le recouvrement, qui tranche.
    Retourne (distance_mm, n_coupes_communes) ; distance nulle si pas de
    recouvrement.
    """
    axes_plan = tuple(a for a in range(3) if a != iz)
    zi = np.where((et == i).any(axis=axes_plan))[0]
    zj = np.where((et == j).any(axis=axes_plan))[0]
    z0, z1 = max(zi[0], zj[0]), min(zi[-1], zj[-1])
    if z1 < z0:
        return 0.0, 0
    sl = [slice(None)] * 3
    d = []
    for z in range(int(z0), int(z1) + 1):
        sl[iz] = z
        a = np.argwhere(et[tuple(sl)] == i)
        b = np.argwhere(et[tuple(sl)] == j)
        if len(a) and len(b):
            ca, cb = a.mean(axis=0), b.mean(axis=0)
            d.append(np.hypot((ca[0] - cb[0]) * mm_plan[0],
                              (ca[1] - cb[1]) * mm_plan[1]))
    return (float(np.median(d)) if d else 0.0), int(z1 - z0 + 1)


def composantes_ordonnees(masque, iz, mm_z, mm_plan, frac_min=0.02,
                          tol_sommet=10.0, dist_fuite=4.0, rec_min=2.0):
    """Composantes 3D significatives, ordonnees le long de l'axe tete-pieds.

    Quand le masque decroche au point de stenose, TotalSegmentator produit deux
    blocs disjoints. Les garder tous les deux est le point de depart : jeter le
    plus petit revient a amputer le vaisseau juste la ou se trouve la lesion.
    """
    et, n = ndimage.label(masque, structure=np.ones((3, 3, 3), bool))
    if n <= 1:
        return [masque]
    tailles = ndimage.sum(masque, et, range(1, n + 1))
    total = tailles.sum()
    gardees = [i + 1 for i in range(n) if tailles[i] >= frac_min * total]
    axes_plan = tuple(a for a in range(3) if a != iz)
    def z_min(i):
        return int(np.where((et == i).any(axis=axes_plan))[0][0])
    def etendue(i):
        zz = np.where((et == i).any(axis=axes_plan))[0]
        return int(zz[0]), int(zz[-1])

    # SEPARER LES FRAGMENTS DES FUITES. Un pont suppose que deux composantes
    # sont EMPILEES le long du vaisseau. Si elles se CHEVAUCHENT en z, elles
    # sont cote a cote : c'est un second vaisseau capture dans le meme label
    # (carotide externe, jugulaire), pas un morceau du meme. Les relier ferait
    # redescendre l'axe dans la fuite apres etre monte jusqu'en haut — un
    # trajet deux fois trop long, et une mesure faite sur le mauvais vaisseau.
    # CRITERE COMPOSITE. "Celle qui monte le plus haut" seul est piegeux : un
    # petit fragment segmente pres de la base du crane le remporterait sur la
    # carotide interne entiere, qu'on ecarterait alors comme une fuite. Sur la
    # cohorte, cinq carotides perdaient ainsi de 46 a 79 mm de territoire.
    #
    # On procede en deux temps : on ne retient comme candidates que les
    # composantes qui atteignent le sommet a `tol_sommet` millimetres pres —
    # condition anatomique, la carotide interne entre dans le canal carotidien
    # alors que l'externe s'arrete a la mandibule — puis, parmi elles, on garde
    # LA PLUS ETENDUE. Une interne complete bat ainsi un fragment distal.
    z_sommet = max(etendue(i)[1] for i in gardees)
    tol = max(1, int(round(tol_sommet / mm_z)))
    candidates = [i for i in gardees if etendue(i)[1] >= z_sommet - tol]
    principal = max(candidates, key=lambda i: etendue(i)[1] - etendue(i)[0])
    plus_haute = max(gardees, key=lambda i: etendue(i)[1])
    if principal != plus_haute:
        zp = etendue(principal); zh = etendue(plus_haute)
        print(f"    [i] composante retenue {zp[0]}-{zp[1]} ({zp[1]-zp[0]+1} coupes)")
        print(f"        plutot que {zh[0]}-{zh[1]} ({zh[1]-zh[0]+1} coupes), qui monte")
        print(f"        plus haut mais est bien plus courte — a verifier.")
    zp0, zp1 = etendue(principal)
    fuites, retenues = [], []
    for i in gardees:
        z0, z1 = etendue(i)
        if i == principal:
            retenues.append(i)
        else:
            dlat, nrec = distance_laterale(et, i, principal, iz, mm_plan)
            # DEUX conditions (voir etape2b) : recouvrement substantiel ET
            # ecart lateral. Un raccord oblique entre deux troncons d'un meme
            # vaisseau produit un fort ecart lateral sur une ou deux coupes.
            if nrec * mm_z >= rec_min and dlat >= dist_fuite:
                fuites.append((i, z0, z1, nrec, dlat))
            else:
                retenues.append(i)
                if nrec > 0:
                    print(f"      [i] coupes {z0}-{z1} : {nrec} coupe(s) "
                          f"commune(s) ({nrec * mm_z:.1f} mm) a {dlat:.1f} mm "
                          f"lateralement -> troncons du meme vaisseau, CONSERVEE")
    gardees = sorted(retenues, key=z_min)

    # TERRITOIRE PERDU. Ecarter une fuite fait perdre les coupes qu'elle seule
    # couvrait. Or une sténose carotidienne siege le plus souvent au bulbe et
    # sur la CI proximale, c'est-a-dire en BAS. Perdre plusieurs centimetres de
    # territoire inferieur peut donc faire manquer la lesion, sans que rien ne
    # le signale dans le resultat.
    if fuites:
        z_ret0 = min(etendue(i)[0] for i in gardees)
        z_ret1 = max(etendue(i)[1] for i in gardees)
        z_tot0 = min(min(etendue(i)[0] for i in gardees),
                     min(x[1] for x in fuites))
        perdu_bas = (z_ret0 - z_tot0) * mm_z
        if perdu_bas > 3.0:
            print(f"    [!] TERRITOIRE PERDU EN BAS : {perdu_bas:.1f} mm "
                  f"(coupes {z_tot0}-{z_ret0}).")
            print(f"        Le bulbe et la CI proximale ne sont plus couverts.")
            print(f"        C'est la que siegent la plupart des stenoses : la")
            print(f"        mesure qui suit ne porte que sur la portion distale.")

    print(f"    {n} composantes 3D, {len(gardees)} retenue(s) "
          f"(seuil {100 * frac_min:.0f} % du volume) :")
    for i, z0, z1, rec, dlat in fuites:
        print(f"      [FUITE] coupes {z0}-{z1} ({int(tailles[i - 1])} voxels) : "
              f"{rec} coupes communes a {dlat:.1f} mm de distance laterale "
              f"-> vaisseau distinct, ECARTEE")
    for i in gardees:
        zz = np.where((et == i).any(axis=axes_plan))[0]
        print(f"      coupes {zz[0]}-{zz[-1]} ({int(tailles[i - 1])} voxels, "
              f"{100 * tailles[i - 1] / total:.1f} %)")
    for i in range(1, n + 1):
        if i not in gardees and i not in [x[0] for x in fuites] and tailles[i - 1] > 0:
            print(f"      [i] composante de {int(tailles[i - 1])} voxels ignoree "
                  f"(< {100 * frac_min:.0f} %)")
    return [et == i for i in gardees]


def pont_hermite(P0, T0, P1, T1, pas_mm, raideur=0.35):
    """Relie deux extremites par une spline cubique d'Hermite.

    On impose les positions ET les tangentes aux deux bouts : le raccord est
    donc lisse en direction, pas seulement en position. Une simple droite
    creerait un coude a chaque extremite, et les coupes perpendiculaires
    calculees juste apres seraient de travers precisement dans la zone qui
    porte la stenose.

    L'amplitude des tangentes est prise egale a la longueur du saut : c'est le
    reglage classique qui evite a la fois le segment trop droit et la boucle.
    """
    L = float(np.linalg.norm(P1 - P0))
    n = max(3, int(np.ceil(L / pas_mm)) + 1)
    u = np.linspace(0, 1, n)[:, None]
    h00 = 2 * u ** 3 - 3 * u ** 2 + 1
    h10 = u ** 3 - 2 * u ** 2 + u
    h01 = -2 * u ** 3 + 3 * u ** 2
    h11 = u ** 3 - u ** 2
    # L'amplitude des tangentes est volontairement inferieure a la longueur du
    # saut : sur quelques millimetres une carotide est quasi rectiligne, et une
    # amplitude trop forte transforme une petite erreur de direction en
    # excursion hors du vaisseau. Mieux vaut pecher par exces de droiture.
    m = raideur * L
    return h00 * P0 + h10 * (m * T0) + h01 * P1 + h11 * (m * T1), L


def tangente_bout(P, longueur_mm=4.0, fin=True):
    """Direction moyenne d'un bout de chemin, par ajustement de droite.

    Prendre la difference entre deux points voisins du chemin brut donnerait la
    direction d'une marche d'escalier de voxels, pas celle du vaisseau. On
    ajuste donc une droite (premiere composante principale) sur les derniers
    millimetres, ce qui moyenne le bruit de discretisation.
    """
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    sel = (d >= d[-1] - longueur_mm) if fin else (d <= longueur_mm)
    Q = P[sel] if sel.sum() >= 3 else P
    Q = Q - Q.mean(axis=0)
    T = np.linalg.svd(Q, full_matrices=False)[2][0]
    ref = (P[-1] - P[0])
    if np.dot(T, ref) < 0:
        T = -T
    return T / np.linalg.norm(T)


def recentrer_sur_ct(P, tan, a_recaler, ct, affine_inv, seuil_hu,
                     rayon=3.0, pas=0.25, n_iter=3, depuis_debut=False):
    """Recale les points interpoles sur le centre de gravite du lumen.

    Le pont d'Hermite n'est qu'une premiere estimation : il ignore l'image. Or
    dans un gap le vaisseau reste parfaitement visible sur le CT — c'est tout
    l'interet de la methode. On ramene donc chaque point interpole au barycentre
    des intensites du lumen dans son plan perpendiculaire, pondere par
    l'exces d'intensite au-dessus du seuil. Quelques iterations suffisent.

    Sans ce recalage, une erreur de tangente de quelques degres a l'entree du
    pont, multipliee par la longueur du saut, fait sortir l'axe du vaisseau —
    et toute mesure faite ensuite est sans objet.
    """
    idx = np.where(a_recaler)[0]
    if idx.size == 0:
        return P, 0.0
    lin = np.arange(-rayon, rayon + 1e-9, pas)
    DU, DV = np.meshgrid(lin, lin)
    dedans = (DU ** 2 + DV ** 2) <= rayon ** 2
    DU, DV = DU[dedans], DV[dedans]
    Q = P.copy()
    # Propagation depuis le bout ADJACENT AU PLUS GROS TRONCON. Recaler chaque
    # point independamment de son voisin fonctionne sur un saut court, mais sur
    # 10 mm l'estimation initiale peut deriver assez pour que le barycentre
    # accroche une structure voisine (jugulaire, carotide externe). En
    # propageant, chaque point part de la position DEJA corrigee du precedent :
    # l'erreur ne s'accumule pas, elle se rattrape.
    ordre = idx if depuis_debut else idx[::-1]
    for _ in range(n_iter):
        for rang, i in enumerate(ordre):
            if rang > 0:
                prec = ordre[rang - 1]
                # on repart du point precedent corrige, translate le long de l'axe
                Q[i] = Q[prec] + (P[i] - P[prec])
            t = tan[i]
            aide = np.array([0.0, 0.0, 1.0])
            if abs(float(np.dot(t, aide))) > 0.9:
                aide = np.array([1.0, 0.0, 0.0])
            u = np.cross(t, aide); u /= np.linalg.norm(u)
            v = np.cross(t, u)
            pts = Q[i] + DU[:, None] * u + DV[:, None] * v
            vox = nib.affines.apply_affine(affine_inv, pts)
            val = ndimage.map_coordinates(ct, vox.T, order=1, mode="constant",
                                          cval=-1000.0)
            w = np.clip(val - seuil_hu, 0, None)
            tot = w.sum()
            if tot <= 1e-6:
                continue
            cand = Q[i] + (float((w * DU).sum() / tot) * u
                           + float((w * DV).sum() / tot) * v)
            # On n'accepte le deplacement que s'il AMENE sur du lumen. Sans ce
            # garde-fou, un barycentre calcule dans un voisinage ou le vaisseau
            # est excentre peut deposer le point dans les tissus mous, et le
            # suivant repart de la mauvaise position.
            vc = nib.affines.apply_affine(affine_inv, cand[None, :])
            hu = float(ndimage.map_coordinates(ct, vc.T, order=1,
                                               mode="constant", cval=-1000.0)[0])
            if hu >= seuil_hu:
                Q[i] = cand
        # Lissage des corrections le long du pont : le trajet corrige doit
        # rester une courbe reguliere. Sans cela le suivi produit des boucles,
        # chaque point corrigeant independamment dans une direction differente.
        if len(idx) >= 5:
            for k in range(3):
                Q[idx, k] = ndimage.uniform_filter1d(Q[idx, k], size=5,
                                                     mode="nearest")
    dep = np.linalg.norm(Q[idx] - P[idx], axis=1)
    return Q, float(dep.max())


def zones_branches(masque, iz, aire_min=4):
    """Coupes portant plus d'une region 2D (bifurcation, repli, moignon)."""
    axes_plan = [a for a in range(3) if a != iz]
    zs = np.where(masque.any(axis=tuple(axes_plan)))[0]
    multi = []
    for z in zs:
        et, n = ndimage.label(coupe_2d(masque, iz, z) > 0.5)
        if n < 2:
            continue
        tailles = ndimage.sum(np.ones_like(et), et, range(1, n + 1))
        if sum(1 for t in tailles if t >= aire_min) > 1:
            multi.append(int(z))
    if not multi:
        return []
    zones, cur = [], [multi[0]]
    for z in multi[1:]:
        if z - cur[-1] <= 2:
            cur.append(z)
        else:
            zones.append((cur[0], cur[-1])); cur = [z]
    zones.append((cur[0], cur[-1]))
    return zones


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def fig_projection(masque, iz, cl_vox, brut_vox, zones, dossier, titre):
    axes_plan = [a for a in range(3) if a != iz]
    fig, axs = plt.subplots(1, 2, figsize=(11, 6))
    for k, ap in enumerate(axes_plan):
        proj = masque.max(axis=ap)
        restants = [a for a in range(3) if a != ap]
        if restants.index(iz) == 1:
            proj = proj.T
        axs[k].imshow(proj, cmap="gray", origin="lower", aspect="auto")
        for z0, z1 in zones:
            axs[k].axhspan(z0, z1, color="orange", alpha=.18)
        abscisse = [a for a in axes_plan if a != ap][0]
        axs[k].plot(brut_vox[:, abscisse], brut_vox[:, iz], "-", color="deepskyblue",
                    lw=.8, alpha=.7, label="chemin brut (Dijkstra)")
        axs[k].plot(cl_vox[:, abscisse], cl_vox[:, iz], "r-", lw=1.6,
                    label="axe lisse")
        axs[k].set_xlabel(f"axe {abscisse} (voxels)")
        axs[k].set_ylabel(f"axe {iz} (coupes)")
        axs[k].legend(fontsize=8, loc="upper right")
        occ = np.where(proj.any(axis=0))[0]
        if occ.size:
            axs[k].set_xlim(occ.min() - 20, occ.max() + 20)
        occz = np.where(proj.any(axis=1))[0]
        if occz.size:
            axs[k].set_ylim(occz.min() - 8, occz.max() + 8)
    fig.suptitle(f"{titre} — axe geodesique (orange = coupes multi-sections)")
    fig.tight_layout()
    fig.savefig(dossier / "20_projection.png", dpi=120)
    plt.close(fig)


def fig_lissage(brut_mm, cl_mm, dossier, titre):
    fig, axs = plt.subplots(1, 3, figsize=(13, 4))
    sb = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(brut_mm, axis=0), axis=1))])
    sc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(cl_mm, axis=0), axis=1))])
    for k, nom in enumerate("XYZ"):
        axs[k].plot(sb, brut_mm[:, k], ".", ms=2, alpha=.4, label="brut")
        axs[k].plot(sc, cl_mm[:, k], "-", lw=1.5, color="darkorange", label="lisse")
        axs[k].set_title(f"coordonnee monde {nom} (mm)")
        axs[k].set_xlabel("abscisse curviligne (mm)")
        axs[k].legend(fontsize=8)
    fig.suptitle(f"{titre} — lissage du chemin geodesique")
    fig.tight_layout()
    fig.savefig(dossier / "21_lissage.png", dpi=120)
    plt.close(fig)


def fig_profil(s, d_inscrit, angles, z_axe, zones, dossier, titre):
    fig, ax = plt.subplots(figsize=(12, 5))
    for z0, z1 in zones:
        m = (z_axe >= z0) & (z_axe <= z1)
        if m.any():
            ax.axvspan(s[m].min(), s[m].max(), color="orange", alpha=.15)
    ax.plot(s, d_inscrit, "-", color="seagreen", lw=1.8,
            label="diametre inscrit (2 x distance a la paroi)")
    k = int(np.argmin(d_inscrit))
    ax.plot(s[k], d_inscrit[k], "v", color="crimson", ms=9)
    ax.annotate(f"min {d_inscrit[k]:.2f} mm", (s[k], d_inscrit[k]),
                textcoords="offset points", xytext=(6, -14),
                color="crimson", fontsize=9)
    ax.set_xlabel("abscisse curviligne le long de l'axe (mm)")
    ax.set_ylabel("diametre (mm)")
    ax.grid(alpha=.3)
    ax.legend(loc="upper left", fontsize=9)
    ax2 = ax.twinx()
    ax2.plot(s, angles, ":", color="gray", lw=1)
    ax2.set_ylabel("obliquite (deg)", color="gray")
    ax2.set_ylim(0, 90)
    fig.suptitle(f"{titre} — diametre inscrit (insensible a l'obliquite)")
    fig.tight_layout()
    fig.savefig(dossier / "22_profil.png", dpi=120)
    plt.close(fig)


def fig_coupes(ct_obj, masque, iz, cl_vox, dossier, titre, n=6):
    choix = np.linspace(0, len(cl_vox) - 1, n).astype(int)
    axes_plan = [a for a in range(3) if a != iz]
    fig, axs = plt.subplots(2, (n + 1) // 2, figsize=(2.7 * ((n + 1) // 2), 5.8))
    for ax, k in zip(np.atleast_1d(axs).ravel(), choix):
        z = int(round(cl_vox[k, iz]))
        cy, cx = cl_vox[k, axes_plan[0]], cl_vox[k, axes_plan[1]]
        demi = 32
        y0, x0 = max(int(cy) - demi, 0), max(int(cx) - demi, 0)
        y1, x1 = y0 + 2 * demi, x0 + 2 * demi
        m = coupe_2d(masque, iz, z) > 0.5
        if ct_obj is not None:
            ax.imshow(coupe_2d(ct_obj, iz, z)[y0:y1, x0:x1], cmap="gray",
                      vmin=-100, vmax=700, origin="lower")
        else:
            ax.imshow(m[y0:y1, x0:x1], cmap="gray", origin="lower")
        ax.contour(m[y0:y1, x0:x1], levels=[0.5], colors="deepskyblue", linewidths=1)
        ax.plot(cx - x0, cy - y0, "r+", ms=11, mew=2)
        ax.set_title(f"z={z}", fontsize=8)
        ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(f"{titre} — axe geodesique sur les coupes")
    fig.tight_layout()
    fig.savefig(dossier / "23_coupes.png", dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="DeepBridge — centerline geodesique")
    ap.add_argument("--patient", required=True)
    ap.add_argument("--cote", default="gauche", choices=list(COTES))
    ap.add_argument("--out", required=True)
    ap.add_argument("--pas-mm", type=float, default=0.5)
    ap.add_argument("--fenetre-mm", type=float, default=5.0,
                    help="fenetre de lissage en mm (defaut 5)")
    ap.add_argument("--alpha", type=float, default=3.0,
                    help="fermete du recentrage sur l'axe (defaut 3)")
    ap.add_argument("--z-depart", type=int, default=None,
                    help="coupe de depart (defaut : la plus basse du masque)")
    ap.add_argument("--z-arrivee", type=int, default=None,
                    help="coupe d'arrivee (defaut : la plus haute du masque)")
    ap.add_argument("--rogner", type=int, default=2)
    ap.add_argument("--tangente-mm", type=float, default=4.0,
                    help="longueur d'ajustement des tangentes aux bouts (mm)")
    ap.add_argument("--raideur", type=float, default=0.35,
                    help="amplitude des tangentes du pont, en fraction du saut")
    ap.add_argument("--marge-pont", type=float, default=2.0,
                    help="marge (mm) de part et d'autre d'un pont ou le calibre "
                         "du masque est juge non fiable")
    ap.add_argument("--sans-recalage", action="store_true",
                    help="ne pas recaler les ponts sur le CT")
    ap.add_argument("--avec-commune", action="store_true",
                    help="fusionne la carotide commune (seg_total/) au masque "
                         "de l'interne, pour couvrir le bulbe et la "
                         "bifurcation ou siege la plupart des lesions")
    ap.add_argument("--dossier-total", default="seg_total",
                    help="sous-dossier contenant les labels TotalSegmentator "
                         "de la tache 'total' (defaut : seg_total)")
    ap.add_argument("--rec-min", type=float, default=2.0,
                    help="recouvrement minimal (mm) en z pour qu'une "
                         "composante puisse etre jugee vaisseau distinct")
    ap.add_argument("--dist-fuite", type=float, default=4.0,
                    help="distance laterale (mm) au-dela de laquelle deux "
                         "composantes qui se recouvrent en z sont jugees etre "
                         "deux vaisseaux distincts")
    ap.add_argument("--tol-sommet", type=float, default=10.0,
                    help="tolerance (mm) sous le point le plus haut du masque "
                         "pour qu'une composante soit candidate au titre de "
                         "vaisseau principal")
    ap.add_argument("--frac-composante", type=float, default=0.02,
                    help="taille minimale d'une composante, en fraction du "
                         "volume total (defaut 0.02)")
    ap.add_argument("--jitter-graine", type=int, default=0,
                    help="deplace la graine de Dijkstra de N voxels au hasard "
                         "(pour une etude de repetabilite)")
    ap.add_argument("--graine-seed", type=int, default=0,
                    help="graine du generateur aleatoire du jitter")
    ap.add_argument("--sans-ct", action="store_true")
    args = ap.parse_args()

    dp = Path(args.patient)
    patient = dp.name
    f_seg = dp / "seg" / f"internal_carotid_artery_{COTES[args.cote]}.nii.gz"
    f_ct = dp / "ct.nii.gz"
    if not f_seg.exists():
        sys.exit(f"[ERREUR] Masque introuvable : {f_seg}")
    sortie = Path(args.out) / f"{patient}_{args.cote}"
    sortie.mkdir(parents=True, exist_ok=True)

    print("\n=== DeepBridge — centerline geodesique (increment 1.5b) ===")
    print(f"Patient {patient}, carotide interne {args.cote}\n")

    img = nib.load(str(f_seg))
    iz = axe_z(img)
    zooms = np.array(img.header.get_zooms()[:3], float)
    axes_plan = [a for a in range(3) if a != iz]
    mm_plan = (zooms[axes_plan[0]], zooms[axes_plan[1]])
    masque = np.asarray(img.dataobj, dtype=np.float32) > 0.5
    # Un fichier de label peut exister tout en ne contenant AUCUN voxel :
    # TotalSegmentator ecrit le volume meme lorsqu'il ne detecte pas la
    # structure. Sans ce controle, la boite englobante est calculee sur un
    # tableau vide et le programme s'interrompt sur une erreur numpy peu
    # parlante, en plein milieu d'un traitement en lot.
    if not masque.any():
        print(f"[!] Le masque de carotide interne {args.cote} est VIDE "
              f"(aucun voxel segmente).")
        print(f"    TotalSegmentator n'a pas detecte la structure sur cet "
              f"examen. Rien a mesurer.")
        sys.exit(0)

    # FUSION AVEC LA CAROTIDE COMMUNE.
    #
    # Le label internal_carotid_artery commence, par definition, APRES la
    # bifurcation. Or la plaque d'atherome carotidienne siege tres
    # majoritairement au BULBE et a la bifurcation — c'est le site de
    # predilection, du fait des turbulences. Mesurer sur la seule interne
    # revient donc a mesurer systematiquement AU-DESSUS de la lesion, et
    # NASCET perd son sens : il est defini par rapport a la stenose du bulbe.
    #
    # Les deux labels se CHEVAUCHENT en z (verifie : 14,4 mm sur un cas), mais
    # il s'agit du meme vaisseau doublement etiquete, pas de deux vaisseaux
    # cote a cote : le contour de l'interne est inclus dans celui de la
    # commune. Une simple union suffit donc, sans logique de raccord.
    if args.avec_commune:
      try:
        f_cc = dp / args.dossier_total / f"common_carotid_artery_{COTES[args.cote]}.nii.gz"
        if not f_cc.exists():
            print(f"    [!] {f_cc.name} introuvable dans {args.dossier_total}/ "
                  f"-> mesure sur la seule carotide interne")
        else:
            img_cc = nib.load(str(f_cc))
            if img_cc.shape != img.shape:
                print(f"    [!] commune de dimensions {img_cc.shape} != "
                      f"{img.shape} -> fusion impossible")
            else:
                cc = np.asarray(img_cc.dataobj, dtype=np.float32) > 0.5
                ap_ = tuple(a for a in range(3) if a != iz)
                zi = np.where(masque.any(axis=ap_))[0]
                zc = np.where(cc.any(axis=ap_))[0]
                # Un fichier de label peut exister tout en etant VIDE :
                # TotalSegmentator ecrit le volume meme lorsqu'il ne detecte
                # pas la structure. Tester l'existence du fichier ne suffit
                # donc pas, il faut tester son contenu.
                if zc.size == 0:
                    print(f"    [!] {f_cc.name} est vide (aucun voxel segmente)")
                    print(f"        -> mesure sur la seule carotide interne")
                    raise _CommuneVide
                if zi.size == 0:
                    sys.exit("[ERREUR] Masque de carotide interne vide.")
                rec = min(zi[-1], zc[-1]) - max(zi[0], zc[0]) + 1
                avant = int(masque.sum())
                masque = masque | cc
                zt = np.where(masque.any(axis=tuple(a for a in range(3) if a != iz)))[0]
                print(f"    FUSION avec la carotide commune :")
                print(f"      interne  coupes {zi[0]}-{zi[-1]} ({avant} voxels)")
                print(f"      commune  coupes {zc[0]}-{zc[-1]} ({int(cc.sum())} voxels)")
                print(f"      recouvrement d'etiquetage : "
                      f"{max(rec, 0)} coupes ({max(rec, 0) * zooms[iz]:.1f} mm)")
                print(f"      -> union : coupes {zt[0]}-{zt[-1]}, "
                      f"{int(masque.sum())} voxels "
                      f"({(zt[-1] - zt[0] + 1) * zooms[iz]:.0f} mm de trajet)")
                print(f"      Le bulbe et la bifurcation entrent dans le "
                      f"territoire mesure.")
      except _CommuneVide:
        pass
    print(f"[1/5] Masque : {int(masque.sum())} voxels, espacement "
          f"{zooms[0]:.4f}/{zooms[1]:.4f}/{zooms[2]:.4f} mm")
    morceaux = composantes_ordonnees(masque, iz, zooms[iz], mm_plan,
                                     args.frac_composante, args.tol_sommet,
                                     args.dist_fuite, args.rec_min)
    masque = np.zeros_like(morceaux[0])
    for c in morceaux:
        masque |= c

    img_ct = None
    if not args.sans_ct and f_ct.exists():
        ct = nib.load(str(f_ct))
        # Verifier la SHAPE ne suffit pas : deux volumes de memes dimensions
        # peuvent avoir des origines ou des orientations differentes. Or
        # l'affine du MASQUE sert ensuite a lire le CT lors du recalage des
        # ponts ; si les grilles different, la lecture se fait au mauvais
        # endroit sans qu'aucune erreur ne soit levee.
        if ct.shape != img.shape:
            print(f"    [!] CT {ct.shape} et masque {img.shape} de dimensions "
                  f"differentes -> recalage des ponts desactive")
        elif not np.allclose(ct.affine, img.affine, atol=1e-3):
            print(f"    [!] CT et masque de memes dimensions mais d'affines "
                  f"differentes -> grilles non superposables,")
            print(f"        recalage des ponts desactive (un reechantillonnage "
                  f"prealable serait necessaire)")
        else:
            img_ct = ct.dataobj

    # --- 2. Transformee de distance ---------------------------------------
    print("\n[2/5] Transformee de distance (en mm)")
    dt = dt_locale(masque, zooms)
    print(f"    distance a la paroi : max {dt.max():.2f} mm "
          f"-> plus gros calibre local {2 * dt.max():.2f} mm")

    axes_plan = [a for a in range(3) if a != iz]
    zs = np.where(masque.any(axis=tuple(axes_plan)))[0]
    z_dep = args.z_depart if args.z_depart is not None else int(zs[0]) + args.rogner
    z_arr = args.z_arrivee if args.z_arrivee is not None else int(zs[-1]) - args.rogner
    # --- 3. Chemin geodesique, morceau par morceau ------------------------
    print(f"\n[3/5] Dijkstra (connectivite 26, alpha={args.alpha})")
    troncons = []
    for num, c in enumerate(morceaux, 1):
        dtc = dt_locale(c, zooms)
        zc = np.where(c.any(axis=tuple(axes_plan)))[0]
        rog = args.rogner if len(zc) > 2 * args.rogner + 6 else 0
        a = args.z_depart if (num == 1 and args.z_depart is not None) else int(zc[0]) + rog
        b = args.z_arrivee if (num == len(morceaux) and args.z_arrivee is not None) else int(zc[-1]) - rog
        rng = np.random.default_rng(args.graine_seed) if args.jitter_graine else None
        g0 = graine_centrale(dtc, iz, a, args.jitter_graine, rng)
        g1 = graine_centrale(dtc, iz, b, args.jitter_graine, rng)
        if g0 is None or g1 is None:
            sys.exit(f"[ERREUR] Coupe vide sur la composante {num}.")
        ch = dijkstra(c, dtc, zooms, g0, g1, args.alpha)
        troncons.append(nib.affines.apply_affine(img.affine, ch))
        print(f"    troncon {num} : coupes {a}-{b}, {len(ch)} voxels")

    # Raccords : spline d'Hermite entre la fin d'un troncon et le debut du suivant
    # Le recalage se propage depuis le troncon le plus long, qui est le plus sur
    lg = [float(np.linalg.norm(np.diff(t, axis=0), axis=1).sum()) for t in troncons]
    depuis_debut = int(np.argmax(lg)) == 0
    morceaux_mm, source_brut, ponts = [troncons[0]], [np.zeros(len(troncons[0]), bool)], []
    for num in range(1, len(troncons)):
        A, B = morceaux_mm[-1], troncons[num]
        lg_A = float(np.linalg.norm(np.diff(A, axis=0), axis=1).sum())
        lg_B = float(np.linalg.norm(np.diff(B, axis=0), axis=1).sum())
        T0 = tangente_bout(A, args.tangente_mm, fin=True)
        T1 = tangente_bout(B, args.tangente_mm, fin=False)
        # Un troncon plus court que la fenetre d'ajustement ne peut pas fournir
        # une direction fiable : on redresse alors le pont vers la droite plutot
        # que de propager une tangente devinee sur trois voxels.
        raideur = args.raideur
        court = min(lg_A, lg_B) < args.tangente_mm
        if court:
            raideur = min(args.raideur, 0.10)
            print(f"    [!] troncon d'ancrage court ({min(lg_A, lg_B):.1f} mm "
                  f"< {args.tangente_mm:.0f} mm) : tangente peu fiable, pont "
                  f"redresse (raideur {raideur:.2f})")
        pont, L = pont_hermite(A[-1], T0, B[0], T1, args.pas_mm, raideur)
        ponts.append(L)
        print(f"    pont {num} : {L:.1f} mm interpoles entre les troncons "
              f"{num} et {num + 1}")
        morceaux_mm.append(pont[1:-1]); source_brut.append(np.ones(len(pont) - 2, bool))
        morceaux_mm.append(B); source_brut.append(np.zeros(len(B), bool))
    brut_mm = np.vstack(morceaux_mm)
    interp_brut = np.concatenate(source_brut)
    brut_vox = nib.affines.apply_affine(np.linalg.inv(img.affine), brut_mm)
    print(f"    chemin total : {len(brut_mm)} points, "
          f"{len(ponts)} pont(s), {sum(ponts):.1f} mm interpoles")

    zones = zones_branches(masque, iz)
    if zones:
        print(f"    {len(zones)} zone(s) multi-sections dans le masque :")
        for z0, z1 in zones:
            n_dedans = int(((brut_vox[:, iz] >= z0) & (brut_vox[:, iz] <= z1)).sum())
            print(f"      coupes {z0}-{z1} ({(z1 - z0 + 1) * zooms[iz]:.1f} mm) "
                  f"— l'axe y passe par {n_dedans} voxels, dans UNE seule branche")
        print("    Les branches en cul-de-sac ne sont pas empruntees : le chemin")
        print("    doit relier depart et arrivee.")

    # --- 4. Lissage --------------------------------------------------------
    print("\n[4/5] Lissage et reechantillonnage")
    cl_mm, tan, s = lisser_reechantillonner(brut_mm, args.pas_mm, args.fenetre_mm)
    cl_vox = nib.affines.apply_affine(np.linalg.inv(img.affine), cl_mm)
    print(f"    longueur de l'axe : {s[-1]:.1f} mm -> {len(s)} points "
          f"a {args.pas_mm} mm")
    # Garde-fou de coherence : un axe ne peut pas mesurer beaucoup plus que
    # l'etendue du masque en Z. Un rapport proche de 2 signale un trajet qui
    # monte puis redescend, donc un pont construit a contresens.
    zs_tot = np.where(masque.any(axis=tuple(axes_plan)))[0]
    etendue_mm = (zs_tot[-1] - zs_tot[0] + 1) * zooms[iz]
    rapport = s[-1] / max(etendue_mm, 1e-6)
    print(f"    etendue du masque en Z : {etendue_mm:.1f} mm "
          f"-> tortuosite apparente {rapport:.2f}")
    if rapport > 2.0:
        print(f"    [!] RAPPORT ANORMAL. Un axe deux fois plus long que")
        print(f"        l'etendue du vaisseau signale un trajet qui monte puis")
        print(f"        redescend. Verifier 20_projection.png : les mesures qui")
        print(f"        suivent sont probablement faites sur deux vaisseaux.")

    angles = np.degrees(np.arccos(np.clip(np.abs(tan[:, 2]), 0, 1)))
    print(f"    obliquite : mediane {np.median(angles):.1f} deg, "
          f"max {angles.max():.1f} deg")

    # Report du drapeau "interpole" sur l'axe reechantillonne : on projette par
    # abscisse curviligne du chemin brut vers celle de l'axe lisse.
    s_brut = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(brut_mm, axis=0), axis=1))])
    interp = interp1d(s_brut / max(s_brut[-1], 1e-9), interp_brut.astype(float),
                      kind="nearest", bounds_error=False,
                      fill_value=(0.0, 0.0))(s / max(s[-1], 1e-9)) > 0.5

    # Recalage des ponts sur l'image, puis relissage
    if interp.any() and img_ct is not None and not args.sans_recalage:
        ct_arr = np.asarray(img_ct, dtype=np.float32)
        seg = ~interp
        vox_seg = cl_vox[seg]
        hu_seg = ndimage.map_coordinates(ct_arr, vox_seg.T, order=1,
                                         mode="nearest")
        hu_lum = float(np.median(hu_seg))
        hu_fond = float(np.percentile(ct_arr[ct_arr > -200], 40))
        seuil_hu = 0.5 * (hu_lum + hu_fond)
        print(f"    recalage des ponts sur le CT : lumen {hu_lum:.0f} HU, "
              f"fond {hu_fond:.0f} HU, seuil {seuil_hu:.0f} HU")
        s_av = s.copy()
        cl_mm, dep_max = recentrer_sur_ct(cl_mm, tan, interp, ct_arr,
                                          np.linalg.inv(img.affine), seuil_hu,
                                          depuis_debut=depuis_debut)
        print(f"    deplacement max applique : {dep_max:.2f} mm")
        if dep_max > 2.5:
            print(f"    [!] deplacement important : le pont initial etait loin du")
            print(f"        vaisseau. Verifier 20_projection.png avant d'exploiter")
            print(f"        les mesures dans la zone interpolee.")
        cl_mm, tan, s = lisser_reechantillonner(cl_mm, args.pas_mm,
                                                args.fenetre_mm)
        cl_vox = nib.affines.apply_affine(np.linalg.inv(img.affine), cl_mm)
        angles = np.degrees(np.arccos(np.clip(np.abs(tan[:, 2]), 0, 1)))
        pass  # le drapeau est recalcule plus bas a partir du masque

    # DRAPEAU DEDUIT DU MASQUE, et non reporte depuis le chemin brut. Reporter
    # par indice ou par fraction d'abscisse decale le pont apres relissage :
    # le recalage change la longueur du trajet, donc la correspondance. Tester
    # directement l'appartenance au masque ne peut pas deriver — un point est
    # interpole si, et seulement si, il n'y a pas de masque sous lui.
    dedans = ndimage.map_coordinates(masque.astype(np.uint8), cl_vox.T,
                                     order=0, mode="constant", cval=0) > 0
    interp = ~dedans

    d_ins = 2.0 * echantillonner_dt(dt, zooms, cl_vox)
    if interp.any():
        # Dans un pont il n'y a pas de masque, donc pas de distance a la paroi.
        # On interpole le calibre entre les deux bords : ce n'est PAS une mesure,
        # seulement un ordre de grandeur qui servira a borner la portee des
        # rayons a l'etape suivante. La vraie mesure s'y fera sur le CT.
        # On elargit la zone d'interpolation de quelques millimetres de chaque
        # cote du pont : au bord d'un gap le masque est coupe net, et la
        # transformee de distance prend cette coupure pour une paroi. Le calibre
        # y chute artificiellement, ce qui ferait rejeter a tort les sections
        # voisines a l'etape de mesure.
        n_marge = max(1, int(round(args.marge_pont / args.pas_mm)))
        large = ndimage.binary_dilation(interp, np.ones(2 * n_marge + 1, bool))
        seg = ~large
        if seg.sum() > 2:
            d_ins = np.interp(s, s[seg], d_ins[seg])
        print(f"    {int(interp.sum())} point(s) d'axe interpoles "
              f"({100 * interp.mean():.0f} % du trajet) — calibre du masque "
              f"indisponible, estime par interpolation")
    k = int(np.argmin(d_ins))
    print(f"\n    Diametre inscrit (insensible a l'obliquite) :")
    print(f"      minimum {d_ins[k]:.2f} mm a s={s[k]:.1f} mm "
          f"(coupe {cl_vox[k, iz]:.0f})")
    print(f"      median  {np.median(d_ins):.2f} mm | max {d_ins.max():.2f} mm")
    # reference NASCET provisoire : portion distale, hors zones multi-sections
    masque_dist = s > 0.65 * s[-1]
    for z0, z1 in zones:
        masque_dist &= ~((cl_vox[:, iz] >= z0) & (cl_vox[:, iz] <= z1))
    if masque_dist.sum() > 10:
        dref = float(np.median(d_ins[masque_dist]))
        print(f"      reference distale provisoire : {dref:.2f} mm")
        print(f"      -> NASCET INDICATIF {100 * (1 - d_ins[k] / dref):.0f} % "
              f"(sur le masque, PAS une mesure clinique)")

    # --- 5. Sorties --------------------------------------------------------
    print("\n[5/5] Ecriture des sorties")
    f_csv = sortie / "centerline_geo.csv"
    with open(f_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["i", "s_mm", "x_mm", "y_mm", "z_mm", "tx", "ty", "tz",
                    "angle_deg", "vox_0", "vox_1", "vox_2",
                    "diametre_inscrit_mm", "source"])
        for i in range(len(s)):
            w.writerow([i, round(float(s[i]), 3)]
                       + [round(float(v), 4) for v in cl_mm[i]]
                       + [round(float(v), 5) for v in tan[i]]
                       + [round(float(angles[i]), 2)]
                       + [round(float(v), 3) for v in cl_vox[i]]
                       + [round(float(d_ins[i]), 3),
                          "interpole" if interp[i] else "segmente"])
    print(f"    {f_csv}")

    titre = f"{patient} — CI {args.cote}"
    fig_projection(masque, iz, cl_vox, brut_vox, zones, sortie, titre)
    fig_lissage(brut_mm, cl_mm, sortie, titre)
    fig_profil(s, d_ins, angles, cl_vox[:, iz], zones, sortie, titre)
    fig_coupes(img_ct, masque, iz, cl_vox, sortie, titre)
    for n in ["20_projection.png", "21_lissage.png", "22_profil.png",
              "23_coupes.png"]:
        print(f"    {sortie / n}")
    print()


if __name__ == "__main__":
    main()