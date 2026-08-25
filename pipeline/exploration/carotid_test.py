#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
carotid_test.py — Test go/no-go de TotalSegmentator sur un patient CHU Nice.

But : vérifier si TotalSegmentator segmente la carotide interne avec assez de
précision AU NIVEAU DE LA STENOSE pour alimenter le calcul NASCET/ECST.
Si oui -> "Chemin 1" (pas besoin d'entraîner). Si non/imprécis -> "Chemin 2"
(correction manuelle + fine-tuning justifiés).

La chaîne complète :
  1. DICOM (dossier d'un patient)  ->  ct.nii.gz  (via SimpleITK)
  2. TotalSegmentator, tâche headneck_bones_vessels  ->  masques carotide interne G/D
  3. Inspection : overlays axiaux + profil d'aire/diamètre le long du vaisseau

Prérequis (dans un venv) :
  pip install TotalSegmentator SimpleITK nibabel numpy scipy matplotlib
  (PyTorch est installé automatiquement avec TotalSegmentator ; GPU vivement conseillé)

Usage :
  python carotid_test.py --dicom /chemin/vers/dossier_patient --out ./resultats_patientX
  # options : --device gpu|cpu   --skip-run (si TotalSegmentator a déjà tourné)
"""

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np


# --------------------------------------------------------------------------- #
# Étape 1 — Conversion DICOM -> NIfTI (avec SimpleITK, aligné pour l'overlay)
# --------------------------------------------------------------------------- #
def _read_tags(one_file: str) -> dict:
    """Lit quelques tags DICOM d'UN fichier (via SimpleITK, sans charger le volume)."""
    import SimpleITK as sitk
    r = sitk.ImageFileReader()
    r.SetFileName(one_file)
    try:
        r.ReadImageInformation()
    except Exception:
        return {}
    def g(tag):  # renvoie "" si le tag est absent
        try:
            return r.GetMetaData(tag).strip()
        except Exception:
            return ""
    return {
        "modality": g("0008|0060"),          # CT, SR, ...
        "description": g("0008|103e"),        # SeriesDescription
        "thickness": g("0018|0050"),          # SliceThickness (mm)
        "rows": g("0028|0010"),
        "cols": g("0028|0011"),
        "bodypart": g("0018|0015"),
    }


def scan_series(root: Path):
    """Parcourt tout l'arbre sous 'root' et regroupe les .dcm en séries via leur
    SeriesInstanceUID (tag DICOM, donc INDÉPENDANT des noms de dossiers).
    Retourne une liste de dicts : {dir, uid, files, n, tags}."""
    import SimpleITK as sitk
    reader = sitk.ImageSeriesReader()
    dirs = [root] + [p for p in root.rglob("*") if p.is_dir()]
    found = []
    seen_uids = set()
    for d in dirs:
        try:
            uids = reader.GetGDCMSeriesIDs(str(d))
        except Exception:
            continue
        for uid in uids:
            if uid in seen_uids:
                continue
            files = reader.GetGDCMSeriesFileNames(str(d), uid)
            if not files:
                continue
            seen_uids.add(uid)
            found.append({"dir": d, "uid": uid, "files": files,
                          "n": len(files), "tags": _read_tags(files[0])})
    return found


def list_series(root: Path) -> None:
    """Mode audit : affiche toutes les séries d'un patient avec leurs tags."""
    series = scan_series(root)
    if not series:
        sys.exit(f"[ERREUR] Aucune série DICOM sous {root}")
    print(f"\n{len(series)} série(s) trouvée(s) sous {root} :\n")
    print(f"{'coupes':>6}  {'modal':5}  {'ep(mm)':>7}  {'dim':>10}  description")
    print("-" * 70)
    for s in sorted(series, key=lambda x: -x["n"]):
        t = s["tags"]
        dim = f"{t.get('rows','?')}x{t.get('cols','?')}"
        print(f"{s['n']:>6}  {t.get('modality',''):5}  {t.get('thickness',''):>7}  "
              f"{dim:>10}  {t.get('description','')}")
    print("\n-> Vérifie visuellement quelle série est le CTA axial fin (CT, "
          "512x512, épaisseur faible, beaucoup de coupes).")


def dicom_to_nifti(dicom_dir: Path, ct_path: Path) -> None:
    import SimpleITK as sitk

    # On sélectionne la série sur ses MÉTADONNÉES, pas sur son dossier :
    #   - on ignore tout ce qui n'est pas de la modalité CT (élimine SR, dose report) ;
    #   - parmi les séries CT, on prend celle qui a le plus de coupes (= CTA fin).
    # Cette logique est indépendante de la structure d'arborescence du patient.
    series = scan_series(dicom_dir)
    if not series:
        sys.exit(f"[ERREUR] Aucune série DICOM sous {dicom_dir} "
                 f"(pointes-tu bien sur un dossier patient contenant des .dcm ?)")

    ct_series = [s for s in series if s["tags"].get("modality", "").upper() == "CT"]
    pool = ct_series if ct_series else series  # repli si la modalité est absente
    chosen = max(pool, key=lambda s: s["n"])

    t = chosen["tags"]
    print(f"[1/3] Série retenue : {chosen['n']} coupes  "
          f"[{t.get('modality','?')}, {t.get('rows','?')}x{t.get('cols','?')}, "
          f"ep={t.get('thickness','?')}mm]  {t.get('description','')}")
    print(f"[1/3] Dossier série : {chosen['dir']}")
    if not ct_series:
        print("[!] Aucune série de modalité CT détectée : sélection par défaut, à vérifier.")
    if chosen["n"] < 40:
        print("[!] Peu de coupes (<40) : possible scout/localizer. Utilise --list pour vérifier.")

    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(chosen["files"])
    image = reader.Execute()
    sitk.WriteImage(image, str(ct_path))
    print(f"[1/3] CT écrit -> {ct_path}")


# --------------------------------------------------------------------------- #
# Étape 2 — Appel de TotalSegmentator (tâche tête-et-cou, carotides internes)
# --------------------------------------------------------------------------- #
def run_totalsegmentator(ct_path: Path, seg_dir: Path, device: str) -> None:
    # Vérifie d'abord que la tâche est dispo et libre sur CETTE installation.
    print("[2/3] Tâches disponibles (vérifie la colonne 'license' pour headneck) :")
    subprocess.run(["totalseg_info", "--list-tasks"], check=False)

    cmd = [
        "TotalSegmentator",
        "-i", str(ct_path),
        "-o", str(seg_dir),
        "-ta", "headneck_bones_vessels",
        "--device", device,
    ]
    print(f"[2/3] Lancement : {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    print(f"[2/3] Masques écrits -> {seg_dir}")


# --------------------------------------------------------------------------- #
# Étape 3 — Inspection : overlays + profil de diamètre
# --------------------------------------------------------------------------- #
def inspect(ct_path: Path, seg_dir: Path, out_dir: Path) -> None:
    import nibabel as nib
    import matplotlib
    matplotlib.use("Agg")  # pas d'affichage interactif, on sauvegarde des PNG
    import matplotlib.pyplot as plt

    ct_img = nib.load(str(ct_path))
    ct = ct_img.get_fdata()
    sx, sy, sz = ct_img.header.get_zooms()[:3]  # espacement voxel en mm
    print(f"[3/3] Volume CT {ct.shape}, spacing {sx:.3f} x {sy:.3f} x {sz:.3f} mm")

    masks = {}
    for side in ("right", "left"):
        f = seg_dir / f"internal_carotid_artery_{side}.nii.gz"
        if not f.exists():
            print(f"[!] Masque manquant : {f.name} -> carotide {side} NON trouvée par le modèle")
            continue
        masks[side] = nib.load(str(f)).get_fdata() > 0.5

    if not masks:
        sys.exit("[ERREUR] Aucun masque carotidien produit. Le modèle n'a rien trouvé.")

    # On travaille en coupes axiales = dernier axe (z). Adapter si l'orientation diffère.
    SLICE_AXIS = 2

    # --- Stats de base : le modèle a-t-il trouvé quelque chose de plausible ? ---
    print("\n=== STATISTIQUES ===")
    z_present = set()
    for side, m in masks.items():
        vox = int(m.sum())
        vol_mm3 = vox * sx * sy * sz
        zs = np.where(m.any(axis=(0, 1)))[0]
        if zs.size:
            z_present.update(range(int(zs.min()), int(zs.max()) + 1))
        print(f"  Carotide {side:5s}: {vox:7d} voxels  (~{vol_mm3/1000:.2f} cm3), "
              f"coupes z={zs.min() if zs.size else '-'}..{zs.max() if zs.size else '-'}")

    # --- Profil d'aire / diamètre équivalent le long du vaisseau (proxy) ---
    # NB : l'aire par coupe axiale est un PROXY grossier (le vaisseau n'est pas
    # aligné sur z). Une chute nette = candidat sténose. Ce n'est PAS la mesure
    # NASCET finale, juste un indicateur pour juger si le masque est exploitable.
    fig, ax = plt.subplots(figsize=(9, 4))
    pix_area = sx * sy
    for side, m in masks.items():
        counts = m.sum(axis=(0, 1))  # nb voxels par coupe z
        area = counts * pix_area
        diam = 2.0 * np.sqrt(area / np.pi)  # diamètre équivalent (mm)
        zs = np.where(counts > 0)[0]
        ax.plot(zs, diam[zs], marker=".", label=f"carotide {side}")
    ax.set_xlabel("coupe axiale (z)")
    ax.set_ylabel("diamètre équivalent (mm) — proxy")
    ax.set_title("Profil de diamètre le long de la carotide interne\n"
                 "(une chute = candidat sténose ; sinon masque douteux)")
    ax.legend()
    ax.grid(alpha=0.3)
    prof_path = out_dir / "profil_diametre.png"
    fig.tight_layout(); fig.savefig(prof_path, dpi=130); plt.close(fig)
    print(f"\n[3/3] Profil de diamètre -> {prof_path}")

    # --- Overlays axiaux : CT en niveaux de gris + masque en couleur ---
    ov_dir = out_dir / "overlays"
    ov_dir.mkdir(exist_ok=True)
    z_list = sorted(z_present)
    if not z_list:
        print("[!] Aucune coupe avec carotide à afficher.")
        return
    # On échantillonne ~16 coupes réparties sur toute la hauteur du vaisseau.
    sample = z_list if len(z_list) <= 16 else [z_list[i] for i in
             np.linspace(0, len(z_list) - 1, 16).astype(int)]

    # Fenêtrage type angio pour bien voir le lumen rehaussé
    lo, hi = -100, 400
    for z in sample:
        sl = np.clip(ct[:, :, z], lo, hi)
        sl = (sl - lo) / (hi - lo)
        fig, a = plt.subplots(figsize=(5, 5))
        a.imshow(sl.T, cmap="gray", origin="lower")
        for side, col in (("right", "red"), ("left", "cyan")):
            if side in masks:
                overlay = np.ma.masked_where(~masks[side][:, :, z], masks[side][:, :, z])
                a.imshow(overlay.T, cmap=matplotlib.colors.ListedColormap([col]),
                         origin="lower", alpha=0.5)
        a.set_title(f"coupe z={z}")
        a.axis("off")
        fig.tight_layout(); fig.savefig(ov_dir / f"z_{z:04d}.png", dpi=110); plt.close(fig)
    print(f"[3/3] {len(sample)} overlays -> {ov_dir}")

    # --- Crops ZOOMÉS centrés sur chaque carotide, autour de la chute ---
    # C'est ici qu'on juge la précision : le point devient un cercle inspectable.
    zoom_dir = out_dir / "zoom"
    zoom_dir.mkdir(exist_ok=True)
    HALF = 45  # demi-fenêtre en pixels (~45 px ≈ 22 mm autour du vaisseau)
    for side, m in masks.items():
        counts = m.sum(axis=(0, 1))
        zs = np.where(counts > 0)[0]
        if zs.size == 0:
            continue
        # coupe de la chute (aire minimale sur la portion centrale, hors bords)
        core = zs[(zs > zs.min() + 5) & (zs < zs.max() - 5)]
        if core.size == 0:
            core = zs
        z_sten = int(core[np.argmin(counts[core])])
        # coupe de référence = aire médiane (segment sain)
        z_ref = int(core[np.argmin(np.abs(counts[core] - np.median(counts[core])))])
        targets = [("stenose", z_sten), ("stenose", z_sten - 6), ("stenose", z_sten + 6),
                   ("reference", z_ref)]
        for tag, z in targets:
            if z < zs.min() or z > zs.max():
                continue
            xs, ys = np.where(m[:, :, z])  # indices (axe0, axe1) du masque sur cette coupe
            if xs.size == 0:
                cx, cy = ct.shape[0] // 2, ct.shape[1] // 2
            else:
                cx, cy = int(xs.mean()), int(ys.mean())  # centroïde
            x0, x1 = max(0, cx - HALF), min(ct.shape[0], cx + HALF)
            y0, y1 = max(0, cy - HALF), min(ct.shape[1], cy + HALF)
            sl = np.clip(ct[x0:x1, y0:y1, z], lo, hi); sl = (sl - lo) / (hi - lo)
            mm = m[x0:x1, y0:y1, z]
            fig, a = plt.subplots(figsize=(4, 4))
            a.imshow(sl.T, cmap="gray", origin="lower", interpolation="nearest")
            ov = np.ma.masked_where(~mm, mm)
            col = "red" if side == "right" else "cyan"
            a.imshow(ov.T, cmap=matplotlib.colors.ListedColormap([col]),
                     origin="lower", alpha=0.45, interpolation="nearest")
            a.set_title(f"{side} — {tag} — z={z}  (aire={int(counts[z])} vox)")
            a.axis("off")
            fig.tight_layout()
            fig.savefig(zoom_dir / f"{side}_{tag}_z{z:04d}.png", dpi=130); plt.close(fig)
        print(f"[3/3] carotide {side}: chute z={z_sten}, référence z={z_ref}")
    print(f"[3/3] Crops zoomés -> {zoom_dir}")

    print("\n=== QUOI REGARDER ===")
    print("  1) Ouvre profil_diametre.png : repère la coupe où le diamètre chute (= sténose).")
    print("  2) Ouvre les overlays autour de cette coupe z : le masque colle-t-il")
    print("     au lumen rehaussé, SANS déborder sur la veine jugulaire ni la paroi ?")
    print("  3) Si c'est net au niveau du rétrécissement -> Chemin 1 (pas d'entraînement).")
    print("     Si ça bave/saute juste là où ça compte -> Chemin 2 (correction + fine-tune).")
    print("  Pour une inspection fine : ouvre ct.nii.gz + les masques dans 3D Slicer.")


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Test go/no-go TotalSegmentator carotide")
    p.add_argument("--dicom", required=True, type=Path, help="dossier DICOM d'un patient")
    p.add_argument("--out", type=Path, help="dossier de sortie (inutile avec --list)")
    p.add_argument("--device", default="gpu", choices=["gpu", "cpu"])
    p.add_argument("--skip-run", action="store_true",
                   help="ne relance pas TotalSegmentator (masques déjà présents)")
    p.add_argument("--list", action="store_true",
                   help="audit : liste toutes les séries du patient avec leurs tags, puis quitte")
    args = p.parse_args()

    if args.list:
        list_series(args.dicom)
        return

    if args.out is None:
        sys.exit("[ERREUR] --out est requis (sauf en mode --list)")
    args.out.mkdir(parents=True, exist_ok=True)
    ct_path = args.out / "ct.nii.gz"
    seg_dir = args.out / "seg"
    seg_dir.mkdir(exist_ok=True)

    if not args.skip_run:
        if not ct_path.exists():
            dicom_to_nifti(args.dicom, ct_path)
        run_totalsegmentator(ct_path, seg_dir, args.device)
    else:
        print("[i] --skip-run : on saute conversion + segmentation")

    inspect(ct_path, seg_dir, args.out)
    print("\nTerminé.")


if __name__ == "__main__":
    main()