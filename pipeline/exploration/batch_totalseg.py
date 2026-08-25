#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_totalseg.py — Lance TotalSegmentator en serie sur un echantillon
representatif de patients, avec reprise apres interruption.

Concu pour tourner plusieurs heures sans surveillance :
  - tirage aleatoire STRATIFIE (par protocole et par taille de serie), seed fixe
  - reprise : les cas deja traites sont sautes automatiquement
  - journal CSV mis a jour APRES CHAQUE CAS (rien n'est perdu si ca coupe)
  - budget temps : s'arrete proprement avant l'heure limite que tu fixes
  - nettoyage optionnel des ct.nii.gz intermediaires (500 Mo - 1 Go chacun)

Entree : le CSV produit par inventory_dicom.py (inventaire_patients.csv)

Usage typique (10 h de budget, 20 cas vises) :
  python batch_totalseg.py ^
      --inventaire "C:\\Projetsss\\inventaire\\inventaire_patients.csv" ^
      --out "C:\\Projetsss\\Resultats" ^
      --n 20 --budget-h 9.5 --device cpu --supprimer-ct

Reprise apres coupure : relance EXACTEMENT la meme commande.

Voir d'abord ce qui serait traite, sans rien lancer :
  ... --dry-run

Prerequis : TotalSegmentator, SimpleITK installes dans l'environnement courant.
"""

import argparse
import csv
import random
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# Labels dont la presence signale qu'un cas est reellement termine.
# On ne se fie PAS a l'existence du dossier seg : un cas interrompu en plein
# milieu laisse un dossier partiel qui serait pris pour un succes.
LABELS_ATTENDUS = [
    "internal_carotid_artery_left.nii.gz",
    "internal_carotid_artery_right.nii.gz",
    "internal_jugular_vein_left.nii.gz",
    "internal_jugular_vein_right.nii.gz",
]

TACHE = "headneck_bones_vessels"


# --------------------------------------------------------------------------- #
# Lecture de l'inventaire et tirage stratifie
# --------------------------------------------------------------------------- #
# Descriptions qui signalent une serie hors cible malgre le filtre de
# l'inventaire : autre region anatomique, ou reconstruction epaisse.
# L'inventaire filtre sur des criteres techniques ; ici on filtre sur le
# CONTENU anatomique, que seule la description revele.
DESC_HORS_CIBLE = (
    "mbres", "membre", "abdo", "thorax", "pelvis", "rachis", "lombaire",
    "genou", "hanche", "epaule", "pied", "main", "coeur", "cardiaque",
    "thick", "epais",
)

EPAISSEUR_MAX_ECHANTILLON = 1.25  # mm — plus strict que l'inventaire


def charger_inventaire(chemin: Path, verbeux: bool = True) -> list:
    """Lit inventaire_patients.csv et ne garde que les cas exploitables ET
    pertinents pour la carotide.

    L'inventaire valide la qualite technique ; ce second filtre valide la
    pertinence anatomique. Un CTA des membres inferieurs est techniquement
    impeccable et totalement inutile ici.
    """
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.DictReader(f, delimiter=";"))

    retenus, ecartes = [], []
    for r in lignes:
        if r.get("statut") != "EXPLOITABLE":
            continue
        serie = r.get("serie_retenue", "").strip()
        if not serie:
            continue

        desc = r.get("serie_description", "").strip()
        desc_bas = desc.lower()
        pid = r.get("patient_id", "").strip()

        motif = None
        for mot in DESC_HORS_CIBLE:
            if mot in desc_bas:
                motif = f"description contient '{mot}'"
                break

        if motif is None:
            try:
                ep = float(r.get("serie_epaisseur", "") or 0)
                if ep > EPAISSEUR_MAX_ECHANTILLON:
                    motif = f"epaisseur {ep} mm"
            except ValueError:
                pass

        if motif:
            ecartes.append((pid, desc, motif))
            continue

        retenus.append({
            "patient_id": pid,
            "serie": serie,
            "coupes": int(r["serie_coupes"]) if r.get("serie_coupes", "").isdigit() else 0,
            "epaisseur": r.get("serie_epaisseur", ""),
            "description": desc,
        })

    if ecartes and verbeux:
        print(f"\n{len(ecartes)} cas ecarte(s) comme hors cible carotidienne :")
        for pid, desc, motif in ecartes:
            print(f"  {pid:14s} {desc[:32]:34s} ({motif})")

    return retenus


def _strate(cas: dict) -> tuple:
    """Definit la strate d'un cas : (famille de protocole, classe de taille).

    On stratifie sur ces deux axes parce que ce sont les seules variables de
    l'inventaire susceptibles de changer le comportement de la segmentation :
    le protocole (champ de vue, injection) et le nombre de coupes (couverture).
    """
    desc = cas["description"].upper().strip()
    if not desc:
        proto = "SANS_DESC"
    elif "ANGIO" in desc:
        proto = "ANGIO"
    elif "CAROTID" in desc:
        proto = "CAROTIDES"
    elif "TSAO" in desc:
        proto = "TSAO"
    elif "TSA" in desc:
        proto = "TSA"
    else:
        proto = "AUTRE"

    n = cas["coupes"]
    if n < 600:
        taille = "S"
    elif n < 1000:
        taille = "M"
    else:
        taille = "L"

    return (proto, taille)


def tirer_echantillon(cas: list, n: int, seed: int) -> list:
    """Tirage stratifie : chaque strate est representee proportionnellement.

    Methode : on alloue a chaque strate un quota proportionnel a son poids,
    en garantissant au moins 1 cas par strate non vide (pour ne perdre aucun
    protocole rare), puis on complete au hasard.
    """
    rng = random.Random(seed)

    strates = {}
    for c in cas:
        strates.setdefault(_strate(c), []).append(c)

    for lst in strates.values():
        rng.shuffle(lst)

    total = len(cas)
    n = min(n, total)

    # Allocation initiale : 1 par strate (dans l'ordre de taille decroissante,
    # pour que si n < nombre de strates on garde les plus representatives)
    ordre = sorted(strates.items(), key=lambda kv: -len(kv[1]))
    quotas = {}
    restant = n
    for cle, lst in ordre:
        if restant <= 0:
            quotas[cle] = 0
        else:
            quotas[cle] = 1
            restant -= 1

    # Repartition proportionnelle du reste
    while restant > 0:
        # strate la plus sous-representee par rapport a son poids theorique
        meilleur, ecart_max = None, None
        for cle, lst in strates.items():
            if quotas[cle] >= len(lst):
                continue  # strate epuisee
            theorique = n * len(lst) / total
            ecart = theorique - quotas[cle]
            if ecart_max is None or ecart > ecart_max:
                meilleur, ecart_max = cle, ecart
        if meilleur is None:
            break
        quotas[meilleur] += 1
        restant -= 1

    echantillon = []
    for cle, q in quotas.items():
        echantillon.extend(strates[cle][:q])

    # Ordre de traitement : les petites series d'abord. Si la session est
    # coupee, on aura traite un maximum de cas plutot qu'un seul gros.
    echantillon.sort(key=lambda c: c["coupes"])
    return echantillon


# --------------------------------------------------------------------------- #
# Etat d'un cas (pour la reprise)
# --------------------------------------------------------------------------- #
def dossier_cas(racine_out: Path, cas: dict) -> Path:
    """Dossier de sortie d'un cas. Le PatientID est utilise tel quel : il est
    deja pseudonymise dans l'inventaire."""
    pid = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                  for ch in cas["patient_id"]) or "INCONNU"
    return racine_out / pid


def est_termine(dcas: Path) -> bool:
    """Un cas est termine si TOUS les labels attendus existent et sont non vides.

    Verifier la taille evite de considerer comme valide un fichier tronque par
    une interruption en pleine ecriture.
    """
    seg = dcas / "seg"
    if not seg.is_dir():
        return False
    for nom in LABELS_ATTENDUS:
        f = seg / nom
        if not f.exists() or f.stat().st_size < 1024:
            return False
    return True


# --------------------------------------------------------------------------- #
# Traitement d'un cas
# --------------------------------------------------------------------------- #
def convertir_dicom(serie_dir: Path, ct_path: Path) -> tuple:
    """Convertit une serie DICOM en NIfTI. Retourne (ok, message).

    On ecrit d'abord dans un fichier temporaire puis on renomme : si la
    conversion est interrompue, on ne laisse pas un ct.nii.gz tronque qui
    serait pris pour valide au prochain lancement.
    """
    import SimpleITK as sitk

    reader = sitk.ImageSeriesReader()
    uids = reader.GetGDCMSeriesIDs(str(serie_dir))
    if not uids:
        return False, "aucune serie DICOM dans le dossier"

    # Le dossier pointe par l'inventaire correspond a UNE serie : on prend
    # celle qui a le plus de fichiers si jamais il y en avait plusieurs.
    meilleur_uid, meilleur_n, fichiers = None, -1, None
    for uid in uids:
        fs = reader.GetGDCMSeriesFileNames(str(serie_dir), uid)
        if len(fs) > meilleur_n:
            meilleur_uid, meilleur_n, fichiers = uid, len(fs), fs

    if not fichiers:
        return False, "serie vide"

    tmp = ct_path.with_suffix(".tmp.nii.gz")
    reader.SetFileNames(fichiers)
    image = reader.Execute()
    sitk.WriteImage(image, str(tmp))
    if ct_path.exists():
        ct_path.unlink()
    tmp.rename(ct_path)
    return True, f"{meilleur_n} coupes"


def lancer_totalseg(ct_path: Path, seg_dir: Path, device: str,
                    timeout_s: int, thr_saving: int, thr_resamp: int) -> tuple:
    """Lance TotalSegmentator. Retourne (ok, message).

    thr_saving / thr_resamp : nombre de threads pour la sauvegarde des masques
    et le reechantillonnage. Les mettre a 1 serialise ces etapes et divise
    fortement le pic memoire — indispensable sur une machine a 16 Go, ou
    l'ecriture parallele des 12 masques provoque un MemoryError.
    """
    cmd = [
        "TotalSegmentator",
        "-i", str(ct_path),
        "-o", str(seg_dir),
        "-ta", TACHE,
        "--device", device,
        "--nr_thr_saving", str(thr_saving),
        "--nr_thr_resamp", str(thr_resamp),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, f"timeout apres {timeout_s//60} min"
    except FileNotFoundError:
        return False, "commande TotalSegmentator introuvable (env. active ?)"

    if r.returncode != 0:
        return False, _resumer_erreur(r.stderr)
    return True, "ok"


def _resumer_erreur(stderr: str) -> str:
    """Extrait la cause reelle d'une sortie d'erreur TotalSegmentator.

    Le traceback Python enterre la vraie cause : la derniere ligne est souvent
    un rouage interne (pool.py) sans interet. On cherche d'abord les exceptions
    connues et parlantes, puis a defaut la derniere ligne de type 'XxxError'.
    """
    if not stderr:
        return "echec sans message (verifier la console)"

    lignes = [l.strip() for l in stderr.strip().splitlines() if l.strip()]

    # Exceptions explicites, par ordre de priorite diagnostique
    connues = {
        "MemoryError": "MemoryError — RAM insuffisante (baisser les threads, "
                       "fermer les autres applis)",
        "CUDA out of memory": "GPU sature — passer en --device cpu",
        "out of memory": "memoire saturee",
        "No such file": "fichier introuvable (chemin ?)",
        "not a valid": "NIfTI invalide (conversion DICOM douteuse)",
        "FileNotFoundError": "fichier ou modele introuvable",
    }
    texte = "\n".join(lignes)
    for motif, message in connues.items():
        if motif in texte:
            return message

    # A defaut : la derniere ligne ressemblant a une exception
    for l in reversed(lignes):
        if "Error" in l or "Exception" in l:
            return l[:250]

    return lignes[-1][:250]


def traiter_cas(cas: dict, racine_out: Path, device: str, timeout_s: int,
                supprimer_ct: bool, thr_saving: int, thr_resamp: int) -> dict:
    """Traite un cas de bout en bout. Retourne une ligne de journal."""
    debut = time.time()
    dcas = dossier_cas(racine_out, cas)
    seg = dcas / "seg"
    dcas.mkdir(parents=True, exist_ok=True)
    seg.mkdir(exist_ok=True)
    ct = dcas / "ct.nii.gz"

    ligne = {
        "patient_id": cas["patient_id"],
        "description": cas["description"],
        "coupes": cas["coupes"],
        "dossier": str(dcas),
        "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "statut": "",
        "duree_s": 0,
        "duree_min": 0.0,
        "taille_ct_mo": "",
        "message": "",
    }

    serie_dir = Path(cas["serie"])
    if not serie_dir.is_dir():
        ligne["statut"] = "ERREUR"
        ligne["message"] = f"dossier serie introuvable : {serie_dir}"
        return ligne

    # --- Conversion (sautee si le NIfTI existe deja et est plausible) -------
    try:
        if ct.exists() and ct.stat().st_size > 1_000_000:
            msg_conv = "ct.nii.gz deja present"
        else:
            ok, msg_conv = convertir_dicom(serie_dir, ct)
            if not ok:
                ligne["statut"] = "ERREUR_CONVERSION"
                ligne["message"] = msg_conv
                return ligne
    except Exception as e:
        ligne["statut"] = "ERREUR_CONVERSION"
        ligne["message"] = str(e)[:300]
        return ligne

    ligne["taille_ct_mo"] = round(ct.stat().st_size / 1e6, 1)

    # --- Segmentation ------------------------------------------------------
    ok, msg = lancer_totalseg(ct, seg, device, timeout_s, thr_saving, thr_resamp)
    ligne["duree_s"] = int(time.time() - debut)
    ligne["duree_min"] = round(ligne["duree_s"] / 60, 1)

    if not ok:
        ligne["statut"] = "ERREUR_SEGMENTATION"
        ligne["message"] = msg
        return ligne

    if not est_termine(dcas):
        ligne["statut"] = "INCOMPLET"
        manquants = [n for n in LABELS_ATTENDUS
                     if not (seg / n).exists() or (seg / n).stat().st_size < 1024]
        ligne["message"] = "labels manquants : " + ", ".join(manquants)
        return ligne

    ligne["statut"] = "OK"
    ligne["message"] = msg_conv

    if supprimer_ct and ct.exists():
        try:
            taille = ct.stat().st_size / 1e6
            ct.unlink()
            ligne["message"] += f" | ct.nii.gz supprime ({taille:.0f} Mo)"
        except OSError as e:
            ligne["message"] += f" | suppression ct impossible : {e}"

    return ligne


# --------------------------------------------------------------------------- #
# Journal
# --------------------------------------------------------------------------- #
COLONNES_JOURNAL = ["patient_id", "description", "coupes", "dossier",
                    "horodatage", "statut", "duree_s", "duree_min",
                    "taille_ct_mo", "message"]


def ecrire_journal(chemin: Path, lignes: list) -> None:
    """Reecrit le journal complet. Appele apres CHAQUE cas : si la session est
    tuee brutalement, le journal reflete toujours l'etat reel."""
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES_JOURNAL, delimiter=";")
        w.writeheader()
        w.writerows(lignes)


def charger_journal(chemin: Path) -> list:
    if not chemin.exists():
        return []
    try:
        with open(chemin, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f, delimiter=";"))
    except Exception:
        return []


def fmt_duree(secondes: float) -> str:
    return str(timedelta(seconds=int(secondes)))


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(
        description="TotalSegmentator en serie sur un echantillon representatif")
    p.add_argument("--inventaire", required=True, type=Path,
                   help="chemin de inventaire_patients.csv")
    p.add_argument("--out", required=True, type=Path,
                   help="racine des dossiers de resultats")
    p.add_argument("--n", type=int, default=20,
                   help="nombre de cas a traiter (defaut 20)")
    p.add_argument("--seed", type=int, default=42,
                   help="graine du tirage (defaut 42, garder la meme pour reprendre)")
    p.add_argument("--device", default="cpu", choices=["cpu", "gpu"])
    p.add_argument("--budget-h", type=float, default=0,
                   help="heures disponibles ; le script s'arrete proprement avant "
                        "(0 = pas de limite)")
    p.add_argument("--timeout-min", type=int, default=90,
                   help="temps max par cas avant abandon (defaut 90 min)")
    p.add_argument("--thr-saving", type=int, default=1,
                   help="threads pour la sauvegarde des masques (defaut 1 : "
                        "evite le MemoryError sur machine a RAM limitee ; "
                        "augmenter a 6 si beaucoup de RAM disponible)")
    p.add_argument("--thr-resamp", type=int, default=1,
                   help="threads pour le reechantillonnage (defaut 1)")
    p.add_argument("--supprimer-ct", action="store_true",
                   help="supprime ct.nii.gz apres succes (economise ~1 Go par cas)")
    p.add_argument("--dry-run", action="store_true",
                   help="affiche l'echantillon tire et quitte, sans rien lancer")
    p.add_argument("--refaire-erreurs", action="store_true",
                   help="retente les cas en erreur des sessions precedentes")
    args = p.parse_args()

    if not args.inventaire.exists():
        sys.exit(f"[ERREUR] Inventaire introuvable : {args.inventaire}")
    args.out.mkdir(parents=True, exist_ok=True)
    journal_path = args.out / "journal_totalseg.csv"

    # --- Echantillon -------------------------------------------------------
    cas_dispo = charger_inventaire(args.inventaire)
    if not cas_dispo:
        sys.exit("[ERREUR] Aucun cas EXPLOITABLE dans l'inventaire.")

    echantillon = tirer_echantillon(cas_dispo, args.n, args.seed)

    print(f"\n{len(cas_dispo)} cas exploitables -> echantillon de {len(echantillon)} "
          f"(seed={args.seed})")
    print("\nRepartition par strate :")
    rep_tot = Counter(_strate(c) for c in cas_dispo)
    rep_ech = Counter(_strate(c) for c in echantillon)
    print(f"  {'strate':22s} {'dispo':>7s} {'tire':>6s}")
    for cle in sorted(rep_tot, key=lambda k: -rep_tot[k]):
        nom = f"{cle[0]}/{cle[1]}"
        print(f"  {nom:22s} {rep_tot[cle]:>7d} {rep_ech.get(cle, 0):>6d}")

    # --- Etat de reprise ---------------------------------------------------
    journal = charger_journal(journal_path)
    deja = {l["patient_id"]: l.get("statut", "") for l in journal}

    a_faire, sautes = [], []
    for c in echantillon:
        dcas = dossier_cas(args.out, c)
        if est_termine(dcas):
            sautes.append(c)
            continue
        st = deja.get(c["patient_id"], "")
        if st.startswith("ERREUR") and not args.refaire_erreurs:
            sautes.append(c)
            continue
        a_faire.append(c)

    print(f"\n  Deja traites (ou en erreur) : {len(sautes)}")
    print(f"  A traiter maintenant        : {len(a_faire)}")

    if sautes and not args.refaire_erreurs:
        n_err = sum(1 for c in sautes
                    if deja.get(c["patient_id"], "").startswith("ERREUR"))
        if n_err:
            print(f"    dont {n_err} en erreur -> --refaire-erreurs pour retenter")

    # --- Estimation --------------------------------------------------------
    # Base sur les durees reelles deja mesurees si disponibles, sinon sur une
    # estimation grossiere calee sur le nombre de coupes.
    durees_ok = [float(l["duree_s"]) for l in journal
                 if l.get("statut") == "OK" and l.get("duree_s", "").isdigit()]
    if durees_ok:
        moy = sum(durees_ok) / len(durees_ok)
        source = f"mesure sur {len(durees_ok)} cas"
    else:
        moy = 1800 if args.device == "cpu" else 180
        source = "estimation a priori"
    estim = moy * len(a_faire)
    print(f"\n  Duree moyenne par cas : {fmt_duree(moy)} ({source})")
    print(f"  Estimation totale     : {fmt_duree(estim)}")
    if args.budget_h:
        print(f"  Budget alloue         : {fmt_duree(args.budget_h * 3600)}")
        fin = datetime.now() + timedelta(hours=args.budget_h)
        print(f"  Arret prevu vers      : {fin.strftime('%H:%M')}")

    if args.dry_run:
        print("\n--- DRY RUN : liste des cas qui seraient traites ---")
        for i, c in enumerate(a_faire, 1):
            print(f"  {i:3d}. {c['patient_id']:14s} {c['coupes']:>5d} coupes  "
                  f"{c['description'][:34]}")
        print("\nRelance sans --dry-run pour executer.")
        return

    if not a_faire:
        print("\nRien a faire. Tout l'echantillon est deja traite.")
        return

    # --- Boucle principale -------------------------------------------------
    t0 = time.time()
    limite = args.budget_h * 3600 if args.budget_h else None
    timeout_s = args.timeout_min * 60

    print("\n" + "=" * 66)
    print(f"DEMARRAGE  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
          f"device={args.device}")
    print("=" * 66)

    compteurs = Counter()
    interrompu = False

    for i, cas in enumerate(a_faire, 1):
        ecoule = time.time() - t0

        # Garde-fou budget : on ne demarre un cas que si le temps restant
        # permet raisonnablement de le finir (on prend la moyenne observee).
        if limite is not None:
            restant = limite - ecoule
            if restant <= 0:
                print(f"\n[BUDGET] Temps epuise. Arret apres {i-1} cas.")
                interrompu = True
                break
            if durees_ok and restant < moy * 0.8:
                print(f"\n[BUDGET] Il reste {fmt_duree(restant)}, insuffisant pour "
                      f"un cas de plus ({fmt_duree(moy)} en moyenne). Arret propre.")
                interrompu = True
                break

        print(f"\n[{i}/{len(a_faire)}] {cas['patient_id']}  "
              f"({cas['coupes']} coupes, {cas['description'][:30]})")
        print(f"        demarre a {datetime.now().strftime('%H:%M:%S')}, "
              f"ecoule {fmt_duree(ecoule)}", flush=True)

        try:
            ligne = traiter_cas(cas, args.out, args.device, timeout_s,
                                args.supprimer_ct, args.thr_saving,
                                args.thr_resamp)
        except KeyboardInterrupt:
            print("\n[INTERRUPTION] Ctrl-C recu. Journal sauvegarde, "
                  "relance la meme commande pour reprendre.")
            interrompu = True
            break
        except Exception as e:
            ligne = {
                "patient_id": cas["patient_id"], "description": cas["description"],
                "coupes": cas["coupes"], "dossier": str(dossier_cas(args.out, cas)),
                "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "statut": "ERREUR", "duree_s": 0, "duree_min": 0.0,
                "taille_ct_mo": "", "message": str(e)[:300],
            }

        # On retire l'eventuelle ligne precedente pour ce patient, puis on
        # ajoute la nouvelle : le journal garde un etat par patient.
        journal = [l for l in journal if l["patient_id"] != ligne["patient_id"]]
        journal.append(ligne)
        ecrire_journal(journal_path, journal)

        compteurs[ligne["statut"]] += 1
        marque = "OK  " if ligne["statut"] == "OK" else "ECHEC"
        print(f"        {marque} en {ligne['duree_min']} min — {ligne['message'][:70]}")

        # Reestimation de la moyenne au fil de l'eau
        if ligne["statut"] == "OK":
            durees_ok.append(ligne["duree_s"])
            moy = sum(durees_ok) / len(durees_ok)
            reste = len(a_faire) - i
            if reste:
                print(f"        moyenne {fmt_duree(moy)}/cas, "
                      f"reste ~{fmt_duree(moy * reste)} pour {reste} cas")

    # --- Bilan -------------------------------------------------------------
    total = time.time() - t0
    print("\n" + "=" * 66)
    print(f"BILAN  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  "
          f"duree totale {fmt_duree(total)}")
    print("=" * 66)
    for st, n in compteurs.most_common():
        print(f"  {st:22s} {n}")

    n_ok_total = sum(1 for l in journal if l.get("statut") == "OK")
    print(f"\n  Cas OK dans le journal (cumul) : {n_ok_total}")
    print(f"  Journal : {journal_path}")

    if interrompu:
        print("\n  Session interrompue. Relance la MEME commande pour continuer :")
        print(f"    python {Path(sys.argv[0]).name} --inventaire ... --out ... "
              f"--n {args.n} --seed {args.seed}")

    if n_ok_total:
        print("\n  Etape suivante — analyse des composantes :")
        print(f"    python batch_components.py --root \"{args.out}\" "
              f"--out \"{args.out.parent / 'analyse'}\" --figures")


if __name__ == "__main__":
    main()