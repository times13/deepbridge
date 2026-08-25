#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_sr.py — Identifie la nature des objets DICOM d'un dossier d'annotations.

But : trier les .dcm d'un dossier "_CT_SR" pour savoir lesquels sont
  - des images classiques,
  - des captures d'ecran (Secondary Capture / SC),
  - des Structured Reports (SR)  -> mesures exploitables par programme,
  - des Presentation States (PR / GSPS) -> annotations superposables.
Et, pour les SR, il extrait le contenu texte (donc les mesures si elles y sont).

Usage :
  pip install pydicom
  python inspect_sr.py --dir "E:\\...\\SF103E8_..._173228207_CT_SR"

Rien n'est modifie : lecture seule.
"""

import argparse
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError

# Familles de SOPClassUID utiles (prefixes)
SC_PREFIX = "1.2.840.10008.5.1.4.1.1.7"       # Secondary Capture (captures d'ecran)
SR_PREFIXES = ("1.2.840.10008.5.1.4.1.1.88",) # Structured Report (toutes variantes)
PR_PREFIXES = ("1.2.840.10008.5.1.4.1.1.11",) # Presentation State (GSPS...)


def kind_of(ds) -> str:
    modality = str(getattr(ds, "Modality", "")).upper()
    sop = str(getattr(ds, "SOPClassUID", ""))
    if modality == "SR" or sop.startswith(SR_PREFIXES):
        return "SR (mesures structurees)"
    if modality in ("PR", "GSPS") or sop.startswith(PR_PREFIXES):
        return "PR/GSPS (annotations superposables)"
    if modality == "SC" or sop.startswith(SC_PREFIX):
        return "SC (capture d'ecran)"
    if modality in ("CT", "MR", "XA"):
        return f"IMAGE {modality}"
    return f"autre (Modality={modality or '?'})"


def dump_sr(ds, indent="    "):
    """Parcourt recursivement l'arbre de contenu d'un SR et affiche texte + mesures."""
    def walk(seq, depth):
        for item in seq:
            vt = str(getattr(item, "ValueType", ""))
            # libelle du concept (ex. 'Diameter', 'Stenosis')
            name = ""
            if "ConceptNameCodeSequence" in item:
                cn = item.ConceptNameCodeSequence[0]
                name = str(getattr(cn, "CodeMeaning", ""))
            val = ""
            if vt == "TEXT":
                val = str(getattr(item, "TextValue", ""))
            elif vt == "NUM" and "MeasuredValueSequence" in item:
                mv = item.MeasuredValueSequence[0]
                num = getattr(mv, "NumericValue", "")
                unit = ""
                if "MeasurementUnitsCodeSequence" in mv:
                    unit = str(getattr(mv.MeasurementUnitsCodeSequence[0], "CodeValue", ""))
                val = f"{num} {unit}"
            elif vt == "CODE" and "ConceptCodeSequence" in item:
                val = str(getattr(item.ConceptCodeSequence[0], "CodeMeaning", ""))
            line = f"{indent}{'  '*depth}[{vt}] {name}" + (f" = {val}" if val else "")
            print(line)
            if "ContentSequence" in item:
                walk(item.ContentSequence, depth + 1)
    if "ContentSequence" in ds:
        walk(ds.ContentSequence, 0)
    else:
        print(f"{indent}(pas de ContentSequence)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, type=Path)
    args = ap.parse_args()

    files = sorted(args.dir.rglob("*"))
    files = [f for f in files if f.is_file()]
    print(f"{len(files)} fichier(s) sous {args.dir}\n")

    summary = {}
    sr_files = []
    for f in files:
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
        except (InvalidDicomError, Exception):
            summary["non-DICOM"] = summary.get("non-DICOM", 0) + 1
            continue
        k = kind_of(ds)
        summary[k] = summary.get(k, 0) + 1
        desc = str(getattr(ds, "SeriesDescription", ""))
        print(f"  {k:38s} | {desc[:30]:30s} | {f.name[:40]}")
        if k.startswith("SR"):
            sr_files.append((f, ds))

    print("\n=== RESUME ===")
    for k, n in sorted(summary.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {k}")

    if sr_files:
        print("\n=== CONTENU DES STRUCTURED REPORTS (mesures) ===")
        for f, ds in sr_files:
            print(f"\n--- {f.name} ---")
            dump_sr(ds)
    else:
        print("\n[i] Aucun SR trouve : les mesures ne sont probablement que dans les")
        print("    captures d'ecran (SC). Il faudra relever les mm a l'oeil sur ces images.")


if __name__ == "__main__":
    main()