#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etape0_lot_segmentation.py — DeepBridge : preparation des patients restants.

Reprend EXACTEMENT la logique de conversion de carotid_test.py — selection de la
serie CT ayant le plus de coupes, conversion par SimpleITK — pour que les
patients ajoutes soient traites de facon identique aux cinquante premiers. Toute
difference de conversion rendrait les deux moities de la cohorte non
comparables.

Trois etapes par patient :
  1. DICOM -> ct.nii.gz              (SimpleITK, serie CT la plus fournie)
  2. TotalSegmentator headneck_bones_vessels -> seg/     (carotide interne)
  3. TotalSegmentator total --roi_subset     -> seg_total/  (carotide commune)

Le dossier de sortie porte le PatientID DICOM, comme les cinquante existants :
c'est lui qui fait le lien avec le fichier clinique via la table de cles.

REPRISE APRES INTERRUPTION. Chaque etape est sautee si son resultat existe
deja. Une nuit de calcul finit rarement sans incident : on peut relancer le
script autant de fois que necessaire sans refaire le travail accompli.

JOURNAL. Une ligne par patient dans un CSV : etat de chaque etape, duree,
message d'erreur le cas echeant. Sans lui, un echec au milieu de quatre-vingt-
dix-neuf patients passe inapercu — la sortie console defile trop vite.

Usage :
  python etape0_lot_segmentation.py --scans "E:\\dataset_chu_nice_2020_2021\\scan" ^
        --out "C:\\Projetsss\\Resultats" --journal "C:\\Projetsss\\journal_seg.csv"

Options utiles :
  --limite N        ne traiter que les N premiers patients restants (test)
  --seulement-ct    convertir sans segmenter (pour verifier la conversion)
  --device cpu|gpu
"""

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Lecture DICOM — logique identique a carotid_test.py
# ---------------------------------------------------------------------------

def _tags(fichier: str) -> dict:
    import SimpleITK as sitk
    r = sitk.ImageFileReader()
    r.SetFileName(fichier)
    try:
        r.ReadImageInformation()
    except Exception:
        return {}

    def g(tag):
        try:
            return r.GetMetaData(tag).strip()
        except Exception:
            return ""

    return {"modality": g("0008|0060"), "description": g("0008|103e"),
            "thickness": g("0018|0050"), "rows": g("0028|0010"),
            "cols": g("0028|0011"), "patient_id": g("0010|0020"),
            "study_date": g("0008|0020")}


def series_du_dossier(racine: Path):
    """Regroupe les fichiers en series via leur SeriesInstanceUID.

    Le regroupement se fait sur le tag DICOM et non sur les noms de dossiers :
    l'arborescence d'export varie d'un patient a l'autre.
    """
    import SimpleITK as sitk
    lecteur = sitk.ImageSeriesReader()
    dossiers = [racine] + [p for p in racine.rglob("*") if p.is_dir()]
    trouvees, vus = [], set()
    for d in dossiers:
        try:
            uids = lecteur.GetGDCMSeriesIDs(str(d))
        except Exception:
            continue
        for uid in uids:
            if uid in vus:
                continue
            fichiers = lecteur.GetGDCMSeriesFileNames(str(d), uid)
            if not fichiers:
                continue
            vus.add(uid)
            trouvees.append({"dir": d, "files": fichiers, "n": len(fichiers),
                             "tags": _tags(fichiers[0])})
    return trouvees


def convertir(dossier_dicom: Path, ct: Path):
    """DICOM -> NIfTI. Retourne (patient_id, study_date, n_coupes, epaisseur)."""
    import SimpleITK as sitk
    series = series_du_dossier(dossier_dicom)
    if not series:
        raise RuntimeError("aucune serie DICOM")

    # Filtrer sur la modalite CT ecarte les rapports de dose et les documents
    # structures, qui figurent dans les exports PACS et n'ont pas de volume.
    ct_series = [s for s in series if s["tags"].get("modality", "").upper() == "CT"]
    pool = ct_series or series
    choisie = max(pool, key=lambda s: s["n"])
    t = choisie["tags"]

    lecteur = sitk.ImageSeriesReader()
    lecteur.SetFileNames(choisie["files"])
    ct.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(lecteur.Execute(), str(ct))
    return (t.get("patient_id", ""), t.get("study_date", ""),
            choisie["n"], t.get("thickness", ""))


def identite(dossier_dicom: Path):
    """PatientID sans conversion, pour nommer le dossier de sortie."""
    import SimpleITK as sitk
    lecteur = sitk.ImageSeriesReader()
    for d in [dossier_dicom] + [p for p in dossier_dicom.rglob("*") if p.is_dir()]:
        try:
            uids = lecteur.GetGDCMSeriesIDs(str(d))
        except Exception:
            continue
        for uid in uids:
            f = lecteur.GetGDCMSeriesFileNames(str(d), uid)
            if f:
                t = _tags(f[0])
                if t.get("patient_id"):
                    return t["patient_id"], t.get("study_date", "")
    return "", ""


# ---------------------------------------------------------------------------

def lancer(cmd, timeout=7200, essais=3, attente=20):
    """Execute une commande, avec quelques tentatives en cas d'echec transitoire.

    Sur Windows, TotalSegmentator ecrit des fichiers temporaires sous le profil
    utilisateur. Un antivirus, l'indexeur ou une instance concurrente peuvent
    les verrouiller brievement, ce qui produit une PermissionError (WinError 32)
    sans que rien ne soit reellement en cause. Sur une centaine de patients,
    l'incident se reproduira : une seule tentative ferait perdre des cas pour
    une raison sans rapport avec les donnees.

    Les erreurs de fond — modele absent, image invalide — echouent de la meme
    facon a chaque essai et ne sont donc pas masquees par ce mecanisme.
    """
    dernier = ""
    for k in range(essais):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"depassement de {timeout} s"
        if r.returncode == 0:
            return True, ("" if k == 0 else f"reussi au {k + 1}e essai")
        # Le motif est cherche dans TOUT le message, pas seulement sa derniere
        # ligne : une exception Python s'imprime sur plusieurs lignes et la
        # ligne finale n'est pas toujours celle qui porte le code d'erreur.
        # Chercher uniquement dans la derniere ligne ferait manquer le
        # declenchement du reessai.
        texte = (r.stderr or r.stdout or "").strip()
        lignes = texte.splitlines()
        dernier = lignes[-1] if lignes else f"code {r.returncode}"
        transitoire = any(m in texte for m in
                          ("WinError 32", "PermissionError", "WinError 5",
                           "being used by another process"))
        # MANQUE DE MEMOIRE. Le modele headneck_bones_vessels est un
        # 3d_fullres_high, plus gourmand que la tache 'total' : sur seize
        # gigaoctets, certains volumes passent et d'autres non, selon la
        # matrice et l'espacement plus que selon le nombre de coupes. Reduire
        # le nombre de fils d'execution suffit a les faire passer, SANS
        # changer de modele — ce qui preserve la comparabilite entre les
        # patients traites en premier et ceux ajoutes ensuite. C'est la raison
        # pour laquelle on ne recourt pas a --fast, qui lui changerait le
        # modele et rendrait les deux moities de la cohorte non comparables.
        memoire = ("MemoryError" in texte
                   or "Unable to allocate" in texte
                   or "out of memory" in texte.lower())
        if memoire and "-ns" not in cmd:
            print(" [memoire : reprise a 1 fil]", end="", flush=True)
            cmd = list(cmd) + ["-ns", "1", "-nr", "1"]
            transitoire = True
        if not transitoire or k == essais - 1:
            return False, dernier
        print(f" [reessai {k + 2}/{essais}]", end="", flush=True)
        time.sleep(attente)
    return False, dernier


def main():
    ap = argparse.ArgumentParser(description="DeepBridge — segmentation en lot")
    ap.add_argument("--scans", required=True, help="dossier des exports DICOM")
    ap.add_argument("--out", required=True, help="dossier Resultats")
    ap.add_argument("--journal", default=None, help="CSV de suivi")
    ap.add_argument("--device", default="cpu", choices=["cpu", "gpu"])
    ap.add_argument("--limite", type=int, default=0,
                    help="ne traiter que les N premiers restants (0 = tous)")
    ap.add_argument("--seulement-ct", action="store_true",
                    help="convertir sans segmenter")
    ap.add_argument("--silencieux", action="store_true",
                    help="masque les avertissements GDCM, qui signalent "
                         "seulement les sous-dossiers sans serie DICOM")
    args = ap.parse_args()

    if args.silencieux:
        # Les avertissements GDCM sont emis par la couche C++ de SimpleITK a
        # chaque sous-dossier sans serie : ils sont normaux et noient la sortie.
        try:
            import SimpleITK as sitk
            sitk.ProcessObject_SetGlobalWarningDisplay(False)
        except Exception:
            pass

    racine = Path(args.scans)
    sortie = Path(args.out)
    sortie.mkdir(parents=True, exist_ok=True)
    journal = Path(args.journal) if args.journal else sortie.parent / "journal_seg.csv"

    dossiers = sorted(p for p in racine.iterdir() if p.is_dir())
    print(f"\n=== DeepBridge — segmentation en lot ===")
    print(f"{len(dossiers)} dossier(s) DICOM sous {racine}\n")

    colonnes = ["dossier_ct", "patient_id", "study_date", "n_coupes",
                "epaisseur_mm", "ct", "seg_interne", "seg_commune",
                "duree_s", "erreur"]
    neuf = not journal.exists()
    fj = open(journal, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(fj, fieldnames=colonnes, delimiter=";")
    if neuf:
        w.writeheader()

    traites = 0
    for i, d in enumerate(dossiers, 1):
        t0 = time.time()
        pid, sd = identite(d)
        if not pid:
            print(f"[{i:3d}/{len(dossiers)}] {d.name} : PAS DE PatientID -> ignore")
            w.writerow({"dossier_ct": d.name, "erreur": "pas de PatientID"})
            fj.flush()
            continue

        cible = sortie / pid
        f_ct = cible / "ct.nii.gz"
        f_int = cible / "seg" / "internal_carotid_artery_left.nii.gz"
        f_com = cible / "seg_total" / "common_carotid_artery_left.nii.gz"

        # Tout est deja fait : on saute sans rien recalculer.
        if f_ct.exists() and f_int.exists() and (f_com.exists() or args.seulement_ct):
            print(f"[{i:3d}/{len(dossiers)}] {pid} : deja complet")
            continue

        # Le test doit preceder TOUT travail sur ce patient, sinon le
        # (N+1)e commence sa conversion avant d'etre interrompu.
        if args.limite and traites >= args.limite:
            print(f"\n[i] Limite de {args.limite} patients atteinte "
                  f"({traites} traites). Relancer sans --limite pour "
                  f"poursuivre.")
            break
        traites += 1

        lig = {"dossier_ct": d.name, "patient_id": pid, "study_date": sd,
               "ct": "-", "seg_interne": "-", "seg_commune": "-", "erreur": ""}
        print(f"[{i:3d}/{len(dossiers)}] {pid}", end="", flush=True)

        # --- 1. conversion ---
        if f_ct.exists():
            lig["ct"] = "existant"
            print(" | ct existant", end="", flush=True)
        else:
            try:
                _pid, _sd, n, ep = convertir(d, f_ct)
                lig.update({"ct": "ok", "n_coupes": n, "epaisseur_mm": ep})
                print(f" | ct {n} coupes", end="", flush=True)
            except Exception as e:
                lig.update({"ct": "ECHEC", "erreur": str(e)[:1000]})
                print(f" | ECHEC conversion : {e}")
                w.writerow(lig); fj.flush()
                continue

        if args.seulement_ct:
            lig["duree_s"] = round(time.time() - t0, 1)
            w.writerow(lig); fj.flush(); print()
            continue

        # --- 2. carotide interne ---
        if f_int.exists():
            lig["seg_interne"] = "existant"
            print(" | interne existante", end="", flush=True)
        else:
            ok, msg = lancer(["TotalSegmentator", "-i", str(f_ct),
                              "-o", str(cible / "seg"),
                              "-ta", "headneck_bones_vessels",
                              "--device", args.device])
            lig["seg_interne"] = "ok" if ok else "ECHEC"
            if not ok:
                # 1000 caracteres et non 120 : un WinError 32 nomme le fichier
                # verrouille, information indispensable au diagnostic et
                # perdue par une troncature courte.
                lig["erreur"] = msg[:1000]
            print(" | interne " + ("ok" if ok else "ECHEC"), end="", flush=True)

        # --- 3. carotide commune ---
        # Sans elle, la mesure porte au-dessus du bulbe, donc au-dessus du site
        # ou siege la plupart des lesions.
        if f_com.exists():
            lig["seg_commune"] = "existant"
            print(" | commune existante", end="")
        else:
            ok, msg = lancer(["TotalSegmentator", "-i", str(f_ct),
                              "-o", str(cible / "seg_total"),
                              "-ta", "total", "--device", args.device,
                              "--roi_subset", "common_carotid_artery_left",
                              "common_carotid_artery_right"])
            lig["seg_commune"] = "ok" if ok else "ECHEC"
            if not ok and not lig["erreur"]:
                lig["erreur"] = msg[:1000]
            print(" | commune " + ("ok" if ok else "ECHEC"), end="")

        lig["duree_s"] = round(time.time() - t0, 1)
        print(f" | {lig['duree_s']:.0f} s")
        w.writerow(lig); fj.flush()

    fj.close()
    print(f"\nJournal : {journal}")
    print("Relancer la meme commande reprend la ou le traitement s'est arrete.\n")


if __name__ == "__main__":
    main()