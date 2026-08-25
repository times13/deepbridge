#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etape2b_sections.py — DeepBridge, etape 2 / increment 1.5 (diagnostic).

POURQUOI CE SCRIPT
------------------
L'increment 1 construit la centerline en prenant, sur chaque coupe axiale, le
centroide de la PLUS GROSSE region du masque. Cette regle casse des qu'une
coupe axiale traverse le vaisseau PLUSIEURS FOIS : le "plus gros" bascule d'une
section a l'autre d'une coupe a la suivante, et le centroide se teleporte de
plusieurs millimetres. L'axe part alors en zigzag, la longueur d'arc est
gonflee, et l'obliquite calculee devient fausse.

Le diagnostic 3D de batch_components.py ne peut PAS voir ce defaut : il compte
les composantes connexes en 3D. Une carotide qui fait une boucle reste UNE
seule composante 3D connectee — verdict PROPRE — alors qu'elle produit deux
sections dans la meme coupe axiale.

Ce script compte donc les regions coupe par coupe (2D), les regroupe en zones,
et classe chaque zone :

  CROSSE (boucle/plicature) : les sections se rejoignent en haut ET en bas.
      Le vaisseau part vers le haut, se replie, redescend, puis repart.
      C'est de l'anatomie reelle (coiling/kinking, frequent sur la CI).
      -> le centroide par coupe est structurellement inadapte : il faut un
         vrai chemin 3D (increment 1.5b, geodesique dans le masque).

  BRANCHE : les sections ne se rejoignent qu'en bas.
      Deux vaisseaux distincts dans le meme label (CI + CE typiquement),
      partant d'un tronc commun.
      -> il faut choisir la bonne branche avant toute mesure.

  ILOT : region isolee qui ne rejoint rien (bruit, ou structure parasite).
      -> a filtrer.

Sorties (dans <out>/<patient>_<cote>/) :
  sections.csv          une ligne par (coupe, region) : aire, centroide
  zones.csv             une ligne par zone multi-sections : classement
  10_sections.png       nb de regions et aires le long de Z
  11_zone_<z>.png       mosaique des coupes de la zone (CT + contours)
  12_projection.png     projection du masque, zones surlignees

Usage :
  python etape2b_sections.py --patient "C:\\Projetsss\\Resultats\\1359673019" ^
                             --cote gauche --out "C:\\Projetsss\\etape2"

Prerequis : nibabel, numpy, scipy, matplotlib
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
    sys.exit("[ERREUR] Dependances : pip install nibabel numpy scipy matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


COTES = {"gauche": "left", "droite": "right"}
AIRE_MIN_VOXELS = 4      # en dessous : region 2D consideree comme bruit de bord


def axe_z(img) -> int:
    """Indice de l'axe tete-pieds, lu dans l'affine (voir increment 1)."""
    try:
        for i, c in enumerate(nib.aff2axcodes(img.affine)):
            if c in ("S", "I"):
                return i
    except Exception:
        pass
    return 2


def coupe_2d(dataobj, iz: int, z: int) -> np.ndarray:
    """Coupe perpendiculaire a l'axe iz, lue sans charger tout le volume."""
    sl = [slice(None)] * 3
    sl[iz] = int(z)
    return np.asarray(dataobj[tuple(sl)], dtype=np.float32)


def analyser_sections(masque, iz, mm_plan, aire_min):
    """Compte et mesure les regions 2D sur chaque coupe.

    Connectivite 4 (voisins orthogonaux) et non 8 : deux sections d'un vaisseau
    replie peuvent se toucher par un coin. La connectivite 8 les fusionnerait
    et masquerait justement le defaut qu'on cherche.
    """
    axes_plan = [a for a in range(3) if a != iz]
    zs = np.where(masque.any(axis=tuple(axes_plan)))[0]
    aire_voxel = mm_plan[0] * mm_plan[1]

    par_coupe = {}
    lignes = []
    for z in zs:
        c2d = coupe_2d(masque, iz, z) > 0.5
        et, n = ndimage.label(c2d)          # connectivite 4 par defaut
        regions = []
        for i in range(1, n + 1):
            r = et == i
            a = int(r.sum())
            if a < aire_min:
                continue
            idx = np.argwhere(r)
            regions.append({
                "aire_vox": a,
                "aire_mm2": a * aire_voxel,
                "d_eq_mm": 2.0 * np.sqrt(a * aire_voxel / np.pi),
                "cy": float(idx[:, 0].mean()),
                "cx": float(idx[:, 1].mean()),
                "masque2d": r,
            })
        if not regions:
            continue
        regions.sort(key=lambda r: -r["aire_vox"])
        par_coupe[int(z)] = regions
        for k, r in enumerate(regions):
            lignes.append({
                "z": int(z), "region": k + 1, "n_regions_coupe": len(regions),
                "aire_voxels": r["aire_vox"],
                "aire_mm2": round(r["aire_mm2"], 2),
                "diametre_eq_mm": round(r["d_eq_mm"], 2),
                "centroide_a": round(r["cy"], 2),
                "centroide_b": round(r["cx"], 2),
            })
    return par_coupe, lignes


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


def analyser_composantes(masque_brut, iz, mm_z, mm_plan, frac_min=0.02,
                         dist_fuite=4.0, rec_min=2.0):
    """Composantes 3D, leurs volumes et les GAPS qui les separent.

    L'etape 1 comptait la fragmentation a partir du nombre de composantes.
    Ce qui manque pour decider si un cas est exploitable, c'est la LONGUEUR du
    trou : un gap de 2 mm se franchit sans difficulte, un gap de 12 mm avec un
    ancrage de 3 mm ne se franchit pas de facon fiable (voir 1359663410 droite).
    """
    et, n = ndimage.label(masque_brut, structure=np.ones((3, 3, 3), bool))
    if n == 0:
        return [], [], 0.0
    tailles = ndimage.sum(masque_brut, et, range(1, n + 1))
    total = float(tailles.sum())
    axes_plan = tuple(a for a in range(3) if a != iz)
    gardees = []
    for i in range(1, n + 1):
        if tailles[i - 1] < frac_min * total:
            continue
        zz = np.where((et == i).any(axis=axes_plan))[0]
        gardees.append({"label": i, "z_min": int(zz[0]), "z_max": int(zz[-1]),
                        "voxels": int(tailles[i - 1]),
                        "pct": 100.0 * tailles[i - 1] / total})
    gardees.sort(key=lambda c: c["z_min"])
    # Un ecart NEGATIF signifie que deux composantes se CHEVAUCHENT en z :
    # elles sont cote a cote et non empilees. C'est la signature d'une fuite
    # inter-label (deux vaisseaux dans le meme masque), pas d'une fragmentation
    # axiale. Les melanger dans la meme colonne masquerait un vrai gap derriere
    # un maximum trompeur, et priverait du depistage gratuit des fuites.
    ecarts = [(b["z_min"] - a["z_max"] - 1) * mm_z
              for a, b in zip(gardees, gardees[1:])]
    gaps = [round(e, 2) for e in ecarts if e > 0]
    chevauchements = [round(-e, 2) for e in ecarts if e <= 0]

    # TERRITOIRE QUE L'ON PERDRAIT en ecartant les fuites, calcule avec la
    # meme regle que etape2c : on garde la composante qui monte le plus haut
    # (critere anatomique : la carotide interne atteint la base du crane), on
    # ecarte celles qui la chevauchent en z.
    #
    # Une fuite EMBOITEE dans l'etendue du principal ne coute rien. Une fuite
    # qui DEBORDE par le bas fait perdre le bulbe et la carotide interne
    # proximale — la ou siegent la plupart des stenoses. La distinction n'est
    # pas cosmetique : dans un cas la mesure reste complete, dans l'autre elle
    # ne porte plus que sur la portion distale.
    perdu_bas = 0.0
    fuites_emboitees = 0
    fuites_debordantes = 0
    raccords_obliques = 0      # recouvrement en z, mais MEME vaisseau
    if len(gardees) > 1:
        z_sommet = max(c["z_max"] for c in gardees)
        tol = max(1, int(round(10.0 / mm_z)))
        cands = [c for c in gardees if c["z_max"] >= z_sommet - tol]
        principal = max(cands, key=lambda c: c["z_max"] - c["z_min"])
        for c in gardees:
            if c is principal:
                continue
            dlat, nrec = distance_laterale(et, c["label"], principal["label"],
                                           iz, mm_plan)
            c["dist_laterale_mm"] = round(dlat, 2)
            c["recouvrement_coupes"] = nrec
            # DEUX conditions, pas une. Une fuite se recouvre SUBSTANTIELLEMENT
            # et est ecartee lateralement. Sur une ou deux coupes de raccord, un
            # vaisseau oblique decale ses extremites de plusieurs millimetres
            # sans qu'il s'agisse pour autant de deux vaisseaux : le seul ecart
            # lateral suffirait alors a jeter des dizaines de millimetres de
            # carotide.
            if nrec * mm_z >= rec_min and dlat >= dist_fuite:
                if c["z_min"] < principal["z_min"]:
                    fuites_debordantes += 1
                    perdu_bas = max(perdu_bas,
                                    (principal["z_min"] - c["z_min"]) * mm_z)
                else:
                    fuites_emboitees += 1
            elif nrec > 0:
                # Recouvrement en z sans separation laterale suffisante, ou
                # trop court : deux troncons du meme vaisseau dont le raccord
                # est oblique. Ce n'est PAS une fuite — les compter comme
                # telles surestimerait le taux de fuites de la cohorte.
                raccords_obliques += 1
    return (gardees, gaps, chevauchements, total,
            round(perdu_bas, 2), fuites_emboitees, fuites_debordantes,
            raccords_obliques)


def regrouper_zones(par_coupe, mm_z):
    """Regroupe en zones les suites de coupes portant plus d'une region."""
    zs = sorted(par_coupe)
    multi = [z for z in zs if len(par_coupe[z]) > 1]
    if not multi:
        return []
    zones, courante = [], [multi[0]]
    for z in multi[1:]:
        # une coupe isolee a une seule region ne coupe pas la zone : le vaisseau
        # replie peut se toucher sur une coupe puis se reseparer
        if z - courante[-1] <= 2:
            courante.append(z)
        else:
            zones.append(courante)
            courante = [z]
    zones.append(courante)
    return [{"z_min": zz[0], "z_max": zz[-1], "n_coupes": len(zz),
             "epaisseur_mm": round((zz[-1] - zz[0] + 1) * mm_z, 1)} for zz in zones]


def classer_zone(zone, par_coupe, mm_plan):
    """Classe une zone : CROSSE, BRANCHE ou ILOT.

    Critere : on regarde si le masque redevient une seule region JUSTE au-dessus
    et JUSTE en dessous de la zone.
      - fusion des deux cotes  -> le vaisseau se replie : CROSSE
      - fusion en bas seulement -> deux branches issues d'un tronc : BRANCHE
      - aucune fusion           -> structure independante : ILOT
    On mesure aussi l'ecart lateral maximal entre les deux plus grosses
    sections : c'est l'amplitude du saut que subit le centroide.
    """
    zs = sorted(par_coupe)
    z_bas = [z for z in zs if z < zone["z_min"]]
    z_haut = [z for z in zs if z > zone["z_max"]]

    def vraie_fusion(z_voisin, z_bord):
        """Le compte de regions ne suffit PAS a conclure a une fusion.

        Une coupe voisine a une seule region peut signifier deux choses :
          - les deux sections se sont REJOINTES (vraie fusion) ;
          - l'une des deux s'est simplement TERMINEE et l'autre continue.
        On tranche sur les aires : en cas de fusion, l'aire de la region unique
        vaut approximativement la SOMME des deux ; en cas de terminaison, elle
        vaut approximativement la PLUS GROSSE des deux.
        """
        if z_voisin is None:
            return False, ""
        rs_v, rs_b = par_coupe[z_voisin], par_coupe[z_bord]
        if len(rs_v) != 1 or len(rs_b) < 2:
            return False, ""
        a_v = rs_v[0]["aire_vox"]
        somme = sum(r["aire_vox"] for r in rs_b)
        plus_grosse = rs_b[0]["aire_vox"]
        # plus proche de la somme -> fusion ; plus proche de la plus grosse -> fin
        if abs(a_v - somme) <= abs(a_v - plus_grosse):
            return True, f"aire {a_v} ~ somme {somme}"
        return False, (f"aire {a_v} ~ plus grosse seule {plus_grosse} "
                       f"(et non la somme {somme}) -> une branche se termine")

    fusion_bas, note_bas = vraie_fusion(z_bas[-1] if z_bas else None, zone["z_min"])
    fusion_haut, note_haut = vraie_fusion(z_haut[0] if z_haut else None, zone["z_max"])

    ecarts, rapports = [], []
    for z in range(zone["z_min"], zone["z_max"] + 1):
        rs = par_coupe.get(z, [])
        if len(rs) < 2:
            continue
        a, b = rs[0], rs[1]
        ecarts.append(np.hypot((a["cy"] - b["cy"]) * mm_plan[0],
                               (a["cx"] - b["cx"]) * mm_plan[1]))
        rapports.append(b["aire_vox"] / a["aire_vox"])

    # Ce que la topologie 2D permet de conclure, et ce qu'elle ne permet PAS.
    #
    # Decidable : la zone existe, et le centroide par coupe y est invalide.
    # Decidable : les sections sortent-elles d'un tronc commun (fusion en bas) ?
    #
    # INDECIDABLE sur ce seul critere : bifurcation vraie (CI + CE) ou repli du
    # meme vaisseau (coiling). Dans les deux cas une branche "meurt" en haut —
    # soit parce qu'elle se termine, soit parce qu'elle atteint l'apex du repli.
    # Trancher demande de savoir QUELLE branche rejoint la base du crane, ce qui
    # se lit sur le chemin geodesique (etape2c), pas sur des coupes isolees.
    if fusion_bas:
        verdict = "SEPARATION"
        note = ("les sections sortent d'un tronc commun. Bifurcation (CI+CE) ou "
                "repli du meme vaisseau : indecidable ici, voir etape2c")
    else:
        verdict = "ILOT"
        note = "aucune continuite avec le vaisseau en dessous — structure a filtrer"

    zone.update({
        "verdict": verdict,
        "fusion_dessous": "oui" if fusion_bas else "non",
        "fusion_dessus": "oui" if fusion_haut else "non",
        "preuve_dessous": note_bas,
        "preuve_dessus": note_haut,
        "ecart_max_mm": round(max(ecarts), 2) if ecarts else "",
        "ecart_median_mm": round(float(np.median(ecarts)), 2) if ecarts else "",
        # rapport d'aire proche de 1 = les deux sections se disputent le titre de
        # "plus grosse" : c'est la que le centroide bascule d'une coupe a l'autre
        "rapport_aire_max": round(max(rapports), 2) if rapports else "",
        "note": note,
    })
    return zone


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def fig_sections(par_coupe, zones, mm_plan, dossier, titre):
    zs = np.array(sorted(par_coupe))
    n_reg = np.array([len(par_coupe[z]) for z in zs])
    aire_voxel = mm_plan[0] * mm_plan[1]
    d1 = np.array([2 * np.sqrt(par_coupe[z][0]["aire_vox"] * aire_voxel / np.pi)
                   for z in zs])
    d2 = np.array([2 * np.sqrt(par_coupe[z][1]["aire_vox"] * aire_voxel / np.pi)
                   if len(par_coupe[z]) > 1 else np.nan for z in zs])

    fig, axs = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    axs[0].step(zs, n_reg, where="mid", color="crimson")
    axs[0].set_ylabel("nb de regions\ndans la coupe")
    axs[0].set_yticks(range(0, int(n_reg.max()) + 2))
    axs[0].grid(alpha=.3)
    axs[1].plot(zs, d1, "-", color="steelblue", label="region principale")
    axs[1].plot(zs, d2, ".", ms=4, color="darkorange", label="2e region")
    axs[1].set_ylabel("diametre equivalent (mm)")
    axs[1].set_xlabel("coupe axiale (indice Z)")
    axs[1].grid(alpha=.3)
    axs[1].legend(fontsize=9)
    for zo in zones:
        for ax in axs:
            ax.axvspan(zo["z_min"], zo["z_max"], color="crimson", alpha=.12)
        axs[0].text((zo["z_min"] + zo["z_max"]) / 2, n_reg.max() + .3,
                    zo["verdict"], ha="center", fontsize=8, color="crimson")
    fig.suptitle(f"{titre} — sections par coupe (zones rouges = coupes multiples)")
    fig.tight_layout()
    fig.savefig(dossier / "10_sections.png", dpi=120)
    plt.close(fig)


def fig_zone(zone, par_coupe, ct_obj, masque, iz, dossier, titre, marge=4, maxi=15):
    """Mosaique de toutes les coupes de la zone, en gros plan."""
    z0, z1 = zone["z_min"] - marge, zone["z_max"] + marge
    zs = [z for z in range(z0, z1 + 1) if z in par_coupe]
    if len(zs) > maxi:
        zs = [zs[i] for i in np.linspace(0, len(zs) - 1, maxi).astype(int)]
    axes_plan = [a for a in range(3) if a != iz]

    # cadrage commun : englobe toutes les regions de la zone
    ys = [r["cy"] for z in zs for r in par_coupe[z]]
    xs = [r["cx"] for z in zs for r in par_coupe[z]]
    cy, cx = int(np.mean(ys)), int(np.mean(xs))
    demi = int(max(25, max(np.ptp(ys), np.ptp(xs)) / 2 + 18))

    cols = 5
    lignes = int(np.ceil(len(zs) / cols))
    fig, axs = plt.subplots(lignes, cols, figsize=(2.6 * cols, 2.8 * lignes))
    axs = np.atleast_1d(axs).ravel()
    for ax in axs:
        ax.axis("off")
    for ax, z in zip(axs, zs):
        ax.axis("on")
        y0, x0 = max(cy - demi, 0), max(cx - demi, 0)
        y1, x1 = y0 + 2 * demi, x0 + 2 * demi
        m = coupe_2d(masque, iz, z) > 0.5
        if ct_obj is not None:
            ax.imshow(coupe_2d(ct_obj, iz, z)[y0:y1, x0:x1], cmap="gray",
                      vmin=-100, vmax=700, origin="lower")
        else:
            ax.imshow(m[y0:y1, x0:x1], cmap="gray", origin="lower")
        ax.contour(m[y0:y1, x0:x1], levels=[0.5], colors="deepskyblue", linewidths=1)
        for k, r in enumerate(par_coupe[z]):
            couleur = "red" if k == 0 else "yellow"
            ax.plot(r["cx"] - x0, r["cy"] - y0, "+", color=couleur, ms=10, mew=2)
        n = len(par_coupe[z])
        ax.set_title(f"z={z}  ({n} region{'s' if n > 1 else ''})",
                     fontsize=8, color="crimson" if n > 1 else "black")
        ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(f"{titre} — zone {zone['z_min']}-{zone['z_max']} "
                 f"[{zone['verdict']}]  (rouge = plus grosse region, jaune = autres)")
    fig.tight_layout()
    f = dossier / f"11_zone_{zone['z_min']}.png"
    fig.savefig(f, dpi=120)
    plt.close(fig)
    return f


def fig_projection(masque, iz, zones, dossier, titre):
    axes_plan = [a for a in range(3) if a != iz]
    fig, axs = plt.subplots(1, 2, figsize=(11, 6))
    for k, ap in enumerate(axes_plan):
        proj = masque.max(axis=ap)
        restants = [a for a in range(3) if a != ap]
        if restants.index(iz) == 1:
            proj = proj.T
        axs[k].imshow(proj, cmap="gray", origin="lower", aspect="auto")
        for zo in zones:
            axs[k].axhspan(zo["z_min"], zo["z_max"], color="crimson", alpha=.30)
        abscisse = [a for a in axes_plan if a != ap][0]
        axs[k].set_xlabel(f"axe {abscisse} (voxels)")
        axs[k].set_ylabel(f"axe {iz} (coupes)")
        axs[k].set_title(f"projection le long de l'axe {ap}")
        # cadrage serre sur le vaisseau
        occup = np.where(proj.any(axis=0))[0]
        if occup.size:
            axs[k].set_xlim(occup.min() - 25, occup.max() + 25)
        occz = np.where(proj.any(axis=1))[0]
        if occz.size:
            axs[k].set_ylim(occz.min() - 10, occz.max() + 10)
    fig.suptitle(f"{titre} — zones multi-sections surlignees en rouge")
    fig.tight_layout()
    fig.savefig(dossier / "12_projection.png", dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="DeepBridge — diagnostic des sections")
    ap.add_argument("--patient", required=True)
    ap.add_argument("--cote", default="gauche", choices=list(COTES))
    ap.add_argument("--out", required=True)
    ap.add_argument("--aire-min", type=int, default=AIRE_MIN_VOXELS,
                    help=f"aire 2D minimale en voxels (defaut {AIRE_MIN_VOXELS})")
    ap.add_argument("--sans-ct", action="store_true")
    ap.add_argument("--csv", default=None,
                    help="fichier de synthese ; une ligne est AJOUTEE par "
                         "carotide traitee (cree l'en-tete si absent)")
    ap.add_argument("--sans-figures", action="store_true",
                    help="ne produit pas les PNG (utile pour un traitement en lot)")
    args = ap.parse_args()

    dp = Path(args.patient)
    patient = dp.name
    f_seg = dp / "seg" / f"internal_carotid_artery_{COTES[args.cote]}.nii.gz"
    f_ct = dp / "ct.nii.gz"
    if not f_seg.exists():
        sys.exit(f"[ERREUR] Masque introuvable : {f_seg}")

    sortie = Path(args.out) / f"{patient}_{args.cote}"
    sortie.mkdir(parents=True, exist_ok=True)

    print("\n=== DeepBridge — diagnostic des sections par coupe ===")
    print(f"Patient {patient}, carotide interne {args.cote}\n")

    img = nib.load(str(f_seg))
    iz = axe_z(img)
    zooms = np.array(img.header.get_zooms()[:3], float)
    axes_plan = [a for a in range(3) if a != iz]
    mm_plan = (zooms[axes_plan[0]], zooms[axes_plan[1]])
    mm_z = zooms[iz]

    masque_brut = np.asarray(img.dataobj, dtype=np.float32) > 0.5
    et, n3d = ndimage.label(masque_brut, structure=np.ones((3, 3, 3), bool))
    (comps, gaps, chevauch, vol_total, perdu_bas,
     n_emb, n_deb, n_obl) = analyser_composantes(masque_brut, iz, mm_z, mm_plan)
    # Le verdict "fuite" doit refleter la DECISION reelle, pas le simple
    # recouvrement en z. Une composante conservee parce qu'elle prolonge le
    # meme vaisseau n'est pas une fuite : c'est une fragmentation a raccord
    # oblique, et la compter en fuite fausserait les statistiques de cohorte.
    n_fuites = n_emb + n_deb
    masque = masque_brut
    if n3d > 1:
        tailles = ndimage.sum(masque_brut, et, range(1, n3d + 1))
        masque = et == int(np.argmax(tailles)) + 1
    print(f"[1/4] Masque : {int(masque_brut.sum())} voxels, {n3d} composante(s) 3D")
    if len(comps) > 1:
        print(f"      {len(comps)} composantes significatives (>= 2 % du volume) :")
        for c in comps:
            print(f"        coupes {c['z_min']}-{c['z_max']} "
                  f"({c['voxels']} voxels, {c['pct']:.1f} %)")
        if gaps:
            print(f"      gap(s) axial(aux) : {', '.join(f'{g} mm' for g in gaps)}")
        if chevauch:
            print(f"      CHEVAUCHEMENT(S) en z : "
                  f"{', '.join(f'{c} mm' for c in chevauch)}")
            print(f"      -> composantes cote a cote, pas empilees : "
                  f"signature d'une fuite inter-label")
            print(f"      {n_emb} emboitee(s), {n_deb} debordante(s), "
                  f"{n_obl} raccord(s) oblique(s) conserve(s)")
            if perdu_bas > 3.0:
                print(f"      [!] ecarter les fuites couterait {perdu_bas} mm "
                      f"de territoire proximal (bulbe et CI proximale)")

    img_ct = None
    if not args.sans_ct and f_ct.exists():
        ct = nib.load(str(f_ct))
        if ct.shape == img.shape:
            img_ct = ct.dataobj

    print("\n[2/4] Comptage des regions coupe par coupe")
    par_coupe, lignes = analyser_sections(masque, iz, mm_plan, args.aire_min)
    n_multi = sum(1 for z in par_coupe if len(par_coupe[z]) > 1)
    print(f"    {len(par_coupe)} coupes analysees")
    print(f"    {n_multi} coupe(s) portent plus d'une region "
          f"({100 * n_multi / max(len(par_coupe), 1):.1f} %)")

    print("\n[3/4] Regroupement et classement")
    zones = regrouper_zones(par_coupe, mm_z)
    zones = [classer_zone(z, par_coupe, mm_plan) for z in zones]

    if not zones:
        print("    Aucune zone multi-sections : le centroide par coupe est")
        print("    legitime sur tout le trajet. La centerline de l'increment 1")
        print("    est utilisable telle quelle.")
    for zo in zones:
        print(f"\n    Zone z {zo['z_min']}-{zo['z_max']} "
              f"({zo['n_coupes']} coupes, {zo['epaisseur_mm']} mm) "
              f"-> {zo['verdict']}")
        print(f"      fusion dessous : {zo['fusion_dessous']}"
              + (f"   [{zo['preuve_dessous']}]" if zo['preuve_dessous'] else ""))
        print(f"      fusion dessus  : {zo['fusion_dessus']}"
              + (f"   [{zo['preuve_dessus']}]" if zo['preuve_dessus'] else ""))
        print(f"      ecart entre sections : median {zo['ecart_median_mm']} mm, "
              f"max {zo['ecart_max_mm']} mm")
        print(f"      rapport d'aire max entre les 2 sections : "
              f"{zo['rapport_aire_max']}")
        print(f"      {zo['note']}")
        if zo["rapport_aire_max"] != "" and zo["rapport_aire_max"] > 0.7:
            print(f"      [!] les deux sections sont de taille comparable : la")
            print(f"          regle 'plus grosse region' bascule d'une coupe a")
            print(f"          l'autre et fait sauter le centroide de "
                  f"{zo['ecart_max_mm']} mm")

    print("\n[4/4] Ecriture des sorties")
    f1 = sortie / "sections.csv"
    with open(f1, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()), delimiter=";")
        w.writeheader(); w.writerows(lignes)
    print(f"    {f1}")

    if zones:
        f2 = sortie / "zones.csv"
        with open(f2, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(zones[0].keys()), delimiter=";")
            w.writeheader(); w.writerows(zones)
        print(f"    {f2}")

    titre = f"{patient} — CI {args.cote}"
    if args.sans_figures:
        pass
    else:
        fig_sections(par_coupe, zones, mm_plan, sortie, titre)
        print(f"    {sortie / '10_sections.png'}")
        for zo in sorted(zones, key=lambda z: -z["n_coupes"])[:3]:
            print(f"    {fig_zone(zo, par_coupe, img_ct, masque, iz, sortie, titre)}")
        fig_projection(masque, iz, zones, sortie, titre)
        print(f"    {sortie / '12_projection.png'}")

    if args.csv:
        f_syn = Path(args.csv)
        neuf = not f_syn.exists()
        colonnes = ["patient", "cote", "voxels_total", "n_composantes_3d",
                    "n_composantes_signif", "gap_max_mm", "gaps_mm",
                    "chevauchement_max_mm", "fuite_suspectee",
                    "n_fuites", "raccords_obliques",
                    "fuites_emboitees", "fuites_debordantes",
                    "territoire_perdu_bas_mm", "composantes_z",
                    "fragmente",
                    "n_coupes", "n_coupes_multi", "pct_coupes_multi",
                    "n_zones", "zones", "verdicts", "ecart_max_mm",
                    "exploitable_centroide", "espacement_mm"]
        ligne = {
            "patient": patient, "cote": args.cote,
            "voxels_total": int(masque_brut.sum()),
            "n_composantes_3d": n3d,
            "n_composantes_signif": len(comps),
            "gap_max_mm": max(gaps) if gaps else 0.0,
            "gaps_mm": "|".join(str(g) for g in gaps),
            "chevauchement_max_mm": max(chevauch) if chevauch else 0.0,
            "fuite_suspectee": "oui" if n_fuites else "non",
            "n_fuites": n_fuites, "raccords_obliques": n_obl,
            "fuites_emboitees": n_emb, "fuites_debordantes": n_deb,
            "territoire_perdu_bas_mm": perdu_bas,
            "composantes_z": "|".join(
                f"{c['z_min']}-{c['z_max']}:{c['voxels']}"
                + (f":lat{c['dist_laterale_mm']}mm/rec{c['recouvrement_coupes']}"
                   if "dist_laterale_mm" in c else "")
                for c in comps),
            "n_coupes": len(par_coupe),
            "n_coupes_multi": n_multi,
            "pct_coupes_multi": round(100 * n_multi / max(len(par_coupe), 1), 1),
            "n_zones": len(zones),
            "zones": "|".join(f"{z['z_min']}-{z['z_max']}" for z in zones),
            "verdicts": "|".join(z["verdict"] for z in zones),
            "ecart_max_mm": max([z["ecart_max_mm"] for z in zones
                                 if z["ecart_max_mm"] != ""], default=""),
            # Verdict synthetique : le centroide par coupe n'est legitime que si
            # le masque est d'un seul tenant ET ne porte jamais deux sections.
            "fragmente": "oui" if (gaps or n_obl) else "non",
            # Le comptage brut des composantes est un mauvais critere : deux
            # moities JOINTIVES d'un meme vaisseau (z_max de l'une = z_min de
            # l'autre - 1) sont etiquetees separement des que leur raccord est
            # trop etroit pour la connexite 26, sans qu'il y ait de rupture.
            # On teste donc l'absence effective de rupture et de fuite.
            "exploitable_centroide": "oui" if (not zones
                                               and not gaps
                                               and not n_fuites) else "non",
            "espacement_mm": "/".join(f"{v:.4f}" for v in zooms),
        }
        with open(f_syn, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=colonnes, delimiter=";")
            if neuf:
                w.writeheader()
            w.writerow(ligne)
        print(f"    ligne ajoutee a {f_syn}")

    if args.sans_figures:
        print()
        return

    print("\n  A regarder : la mosaique 11_zone_*.png. Sur chaque vignette,")
    print("  la croix ROUGE est la region retenue par l'increment 1. Si elle")
    print("  saute d'une section a l'autre entre deux vignettes voisines, le")
    print("  defaut est confirme visuellement.\n")


if __name__ == "__main__":
    main()