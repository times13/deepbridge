#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
etape3_decision.py — DeepBridge : jointure clinique et aide a la decision.

Assemble trois sources, applique la regle de decision issue des essais
NASCET/ECST, et confronte la recommandation a la decision chirurgicale reelle.

  nascet.csv   mesures par carotide (etape2d)
  cles.csv     table de correspondance dossier DICOM <-> identifiant patient
  Excel        fichier clinique (colonne CODES = nom du dossier DICOM)

CHAINE DE JOINTURE

    Excel[CODES] --> cles[dossier_ct] --> cles[patient_id] --> nascet[patient]

Le maillon central est indispensable : le fichier clinique designe les examens
par leur nom d'export PACS, tandis que les mesures sont indexees par
l'identifiant patient DICOM. Aucune des deux sources ne porte les deux
identifiants.

REGLE DE DECISION

Les seuils d'indication chirurgicale ne sont pas les memes selon que le
patient est symptomatique ou non :

  symptomatique   (S+ = 1) : NASCET >= 50 %   (bénéfice net au-dela de 70 %)
  asymptomatique  (S+ = 0) : NASCET >= 70 %

La sortie comporte TROIS etats, et non deux. Une carotide dont la mesure n'est
pas exploitable ne doit pas etre classee en "surveillance" par defaut : ce
serait transformer une absence d'information en decision negative. Elle est
donc marquee "indecidable", avec le motif, ce qui correspond a la conduite
clinique reelle — completer par un echo-doppler.

CONTROLE DE COHERENCE

Tous les patients du fichier clinique ont ete operes. Chaque carotide pour
laquelle le systeme recommande la surveillance constitue donc un desaccord
avec la decision reelle, a examiner. Le cote opere n'etant pas renseigne dans
le fichier clinique, la comparaison se fait au niveau PATIENT : on retient le
cote le plus stenose, sous l'hypothese — verifiable et discutee dans la sortie
— que l'intervention porte sur celui-ci.

Cette hypothese ne vaut a priori que chez l'asymptomatique : chez un patient
symptomatique, on opere le cote RESPONSABLE des symptomes, meme s'il est moins
stenose que le controlateral. Le script separe donc les deux groupes.

Usage :
  python etape3_decision.py --mesures "C:\\Projetsss\\mesures_all\\nascet.csv" ^
        --cles "C:\\Projetsss\\cles.csv" ^
        --excel "C:\\Projetsss\\BaseCarotideAnonymisee.xlsx" ^
        --out "C:\\Projetsss\\decision"

Prerequis : pandas, openpyxl
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
except ImportError:
    sys.exit("[ERREUR] pip install pandas openpyxl")


SEUIL_SYMPTOMATIQUE = 50.0
SEUIL_ASYMPTOMATIQUE = 70.0
DELAI_MAX_JOURS = 365       # au-dela, la correspondance examen/intervention
DELAI_MIN_JOURS = -7        # est douteuse (patient reopere, code ambigu)


def charger_mesures(f):
    r = list(csv.DictReader(open(f, encoding="utf-8-sig"), delimiter=";"))
    if not r:
        sys.exit(f"[ERREUR] {f} est vide")
    d = pd.DataFrame(r)
    for c in ("nascet_pct", "d_min_mm", "d_ref_mm", "hu_lumen_median",
              "pct_retenues", "obliquite_mediane"):
        if c in d:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def charger_cles(f):
    d = pd.DataFrame(list(csv.DictReader(open(f, encoding="utf-8-sig"),
                                         delimiter=";")))
    d["dossier_ct"] = d["dossier_ct"].astype(str).str.strip()
    d["patient_id"] = d["patient_id"].astype(str).str.strip()
    return d


def charger_clinique(f):
    d = pd.read_excel(f)
    d["CODES"] = d["CODES"].astype(str).str.strip()
    d = d[d["CODES"].notna() & (d["CODES"] != "nan")].copy()
    return d


def decision(nascet, symptomatique, verdict):
    """Trois etats : recommande, surveillance, indecidable.

    L'etat 'indecidable' n'est pas un echec mais une information : il indique
    que l'image ne permet pas de trancher, et appelle une autre modalite.
    Le confondre avec 'surveillance' reviendrait a conclure a l'absence de
    lesion severe alors qu'on n'a rien pu mesurer — l'erreur la plus grave
    que puisse commettre un outil d'aide a la decision.
    """
    if verdict == "non_calculable" or not np.isfinite(nascet):
        return "indecidable", np.nan
    seuil = SEUIL_SYMPTOMATIQUE if symptomatique == 1 else SEUIL_ASYMPTOMATIQUE
    return ("intervention" if nascet >= seuil else "surveillance"), seuil


def main():
    ap = argparse.ArgumentParser(description="DeepBridge — jointure et decision")
    ap.add_argument("--mesures", required=True)
    ap.add_argument("--cles", required=True)
    ap.add_argument("--excel", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--inclure-incertaines", action="store_true",
                    help="traiter les mesures incertaines comme des mesures "
                         "(par defaut elles sont analysees a part)")
    args = ap.parse_args()

    sortie = Path(args.out)
    sortie.mkdir(parents=True, exist_ok=True)

    print("\n=== DeepBridge — jointure clinique et decision ===\n")

    mes = charger_mesures(args.mesures)
    cle = charger_cles(args.cles)
    cli = charger_clinique(args.excel)
    print(f"[1/4] Sources")
    print(f"      mesures  : {len(mes)} carotides, "
          f"{mes['patient'].nunique()} patients")
    print(f"      cles     : {len(cle)} dossiers DICOM")
    print(f"      clinique : {len(cli)} lignes avec un code d'examen")

    # --- 2. jointure ------------------------------------------------------
    j = cli.merge(cle, left_on="CODES", right_on="dossier_ct", how="inner")
    print(f"\n[2/4] Jointure")
    print(f"      {len(j)}/{len(cli)} lignes cliniques appariees a un dossier")

    # Controle par les dates : l'angioscanner motive l'intervention, il doit
    # donc la preceder de quelques jours a quelques semaines. Un delai
    # aberrant signale un code renvoyant a une autre intervention du meme
    # patient — cas des reoperations.
    j["date_examen"] = pd.to_datetime(j["study_date"], format="%Y%m%d",
                                      errors="coerce")
    j["delai_jours"] = (j["DI"] - j["date_examen"]).dt.days
    j["jointure_fiable"] = ((j["delai_jours"] >= DELAI_MIN_JOURS)
                            & (j["delai_jours"] <= DELAI_MAX_JOURS))
    n_ko = int((~j["jointure_fiable"]).sum())
    print(f"      delai examen -> intervention : median "
          f"{j['delai_jours'].median():.0f} j "
          f"(q1 {j['delai_jours'].quantile(.25):.0f}, "
          f"q3 {j['delai_jours'].quantile(.75):.0f})")
    if n_ko:
        print(f"      [!] {n_ko} correspondance(s) hors de "
              f"[{DELAI_MIN_JOURS}, {DELAI_MAX_JOURS}] jours -> marquees non "
              f"fiables")
        print(f"          (patient probablement reopere : le code renvoie a "
              f"une autre intervention)")

    j["S+"] = pd.to_numeric(j["S+"], errors="coerce")
    garder = ["patient_id", "CODES", "delai_jours", "jointure_fiable",
              "Age arrondi", "femme/homme", "S+", "DI",
              "AIT/AVC", "cplction N (stroke + periph)", "cplication J30",
              "patch = 1, eversion = 2", "shunt", "re inter"]
    garder = [c for c in garder if c in j.columns]
    j = j[garder].drop_duplicates(subset=["patient_id"], keep="first")
    print(f"      {len(j)} patients uniques avec donnees cliniques")

    # --- 3. decision par carotide ----------------------------------------
    f = mes.merge(j, left_on="patient", right_on="patient_id", how="left")
    f["clinique_disponible"] = f["patient_id"].notna()

    if not args.inclure_incertaines:
        # Une mesure incertaine n'a pas la meme valeur qu'une mesure ferme :
        # elle est produite lorsque le voisinage du minimum est degrade. On ne
        # la fond donc pas dans les mesures, on la traite comme un etat propre.
        f.loc[f["verdict"] == "mesure_incertaine", "nascet_pct"] = np.nan

    res = f.apply(lambda r: decision(r.get("nascet_pct", np.nan),
                                     r.get("S+", np.nan),
                                     r.get("verdict", "")), axis=1)
    f["recommandation"] = [x[0] for x in res]
    f["seuil_applique"] = [x[1] for x in res]
    f.loc[~f["clinique_disponible"], "recommandation"] = "clinique_absente"

    print(f"\n[3/4] Recommandation par carotide")
    for k, v in f["recommandation"].value_counts().items():
        print(f"      {k:20s} {v:4d}")

    # --- 4. confrontation a la decision reelle ---------------------------
    # Tous ces patients ont ete operes. Le cote n'etant pas renseigne, on
    # raisonne au niveau patient sur le cote le plus stenose.
    print(f"\n[4/4] Confrontation a la decision chirurgicale reelle")
    ok = f[f["clinique_disponible"] & f["jointure_fiable"].fillna(False)]
    par_pat = []
    for pid, g in ok.groupby("patient_id"):
        n = g["nascet_pct"].dropna()
        symp = g["S+"].dropna()
        symp = int(symp.iloc[0]) if len(symp) else np.nan
        seuil = (SEUIL_SYMPTOMATIQUE if symp == 1 else SEUIL_ASYMPTOMATIQUE)
        par_pat.append({
            "patient_id": pid, "symptomatique": symp,
            "n_carotides_mesurees": int(len(n)),
            "nascet_max": float(n.max()) if len(n) else np.nan,
            "nascet_min": float(n.min()) if len(n) else np.nan,
            "asymetrie_pt": float(n.max() - n.min()) if len(n) > 1 else np.nan,
            "seuil": seuil,
            "accord": ("oui" if len(n) and n.max() >= seuil
                       else "non" if len(n) else "indecidable"),
        })
    pp = pd.DataFrame(par_pat)
    if len(pp):
        for grp, lib in ((1, "symptomatiques"), (0, "asymptomatiques")):
            s = pp[pp["symptomatique"] == grp]
            if not len(s):
                continue
            a = (s["accord"] == "oui").sum()
            n_ = (s["accord"] == "non").sum()
            i_ = (s["accord"] == "indecidable").sum()
            seuil = SEUIL_SYMPTOMATIQUE if grp == 1 else SEUIL_ASYMPTOMATIQUE
            print(f"      {lib} (seuil {seuil:.0f} %) : {len(s)} patients")
            print(f"        {a:3d} avec au moins un cote au-dessus du seuil "
                  f"(accord avec la chirurgie)")
            print(f"        {n_:3d} sans aucun cote au-dessus "
                  f"(desaccord, a examiner)")
            print(f"        {i_:3d} sans mesure exploitable")

        deux = pp[pp["n_carotides_mesurees"] == 2]
        if len(deux):
            print(f"\n      Asymetrie entre les deux cotes "
                  f"({len(deux)} patients mesures bilateralement) :")
            print(f"        median {deux['asymetrie_pt'].median():.1f} pt | "
                  f"q3 {deux['asymetrie_pt'].quantile(.75):.1f} pt | "
                  f"max {deux['asymetrie_pt'].max():.1f} pt")
            print(f"        Une asymetrie faible signifie que le degre de "
                  f"stenose ne suffit pas")
            print(f"        a designer le cote opere : d'autres criteres "
                  f"interviennent.")

    f_car = sortie / "decision_par_carotide.csv"
    f_pat = sortie / "decision_par_patient.csv"
    f.to_csv(f_car, sep=";", index=False, encoding="utf-8-sig")
    pp.to_csv(f_pat, sep=";", index=False, encoding="utf-8-sig")
    print(f"\n      {f_car}")
    print(f"      {f_pat}")
    print("\n      Les desaccords sont la partie la plus informative : chaque")
    print("      patient opere sans cote au-dessus du seuil interroge soit la")
    print("      mesure, soit le critere, soit l'indication elle-meme.\n")


if __name__ == "__main__":
    main()
