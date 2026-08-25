#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validation.py — DeepBridge : recevabilite d'un examen pour la mesure carotidienne.

DEUX CONTROLES, DEUX MOMENTS, DEUX COUTS
----------------------------------------
    prevol()           avant conversion, sur les en-tetes seules  (~2 s)
    controle_volume()  apres segmentation, sur les masques        (gratuit)

Le pre-vol economise les 12,5 minutes de segmentation ET donne un message
juste. Sans lui, un scanner de pied traverse toute la chaine : TotalSegmentator
tourne sans rien signaler, produit des masques vides, l'axe se construit sur du
bruit, et le radiologue lit « rehaussement insuffisant » — un message faux, la
vraie cause etant que ce n'est pas un examen cervical.

Le controle post-segmentation tranche pour de bon, parce que les en-tetes
mentent : BodyPartExamined est vide dans une grande part des exports PACS, et
SeriesDescription est du texte libre saisi par le manipulateur.

LISTE BLANCHE, PAS LISTE NOIRE
------------------------------
Une liste de regions a exclure ne peut pas etre exhaustive : elle refuse ce qui
est NOMME hors-sujet et accepte tout ce qui n'est nomme nulle part. Un scanner
abdominal exporte avec BodyPartExamined vide et SeriesDescription = "ANGIO 1.25"
passerait sans reserve.

On accepte donc explicitement, on exclut explicitement, et **l'inconnu passe en
reserve plutot qu'en refus** : refuser sur un silence bloquerait des examens
valides, et controle_volume() tranchera de toute facon.

TROIS ISSUES
------------
    RECEVABLE   rien ne s'oppose a l'analyse
    RESERVE     l'analyse continue, mais un doute est journalise et affiche
    REFUS       l'analyse ne peut pas aboutir : on ne depense pas le calcul
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Seuils. Repris de inventory_dicom.py pour que l'application applique les
# MEMES criteres que l'etude : un examen accepte ici doit etre comparable aux
# 292 axes de la cohorte de reference.
# --------------------------------------------------------------------------- #

from app.config import settings

MODALITE_ATTENDUE = settings.accepted_modality
EPAISSEUR_MAX_MM = settings.epaisseur_max_mm
COUPES_MIN = settings.coupes_min
ETENDUE_Z_MIN_MM = settings.etendue_z_min_mm
MATRICE_MIN = 512

# Region anatomique — liste blanche puis liste noire.
REGIONS_ACCEPTEES = {
    "HEAD", "NECK", "HEADNECK", "HEAD_NECK", "CAROTID", "TSA", "COU",
    "CERVICAL", "CSPINE", "SUPRAAORTIC", "NECKANGIO", "ANGIOTSA",
}
REGIONS_EXCLUES = {
    "FOOT", "ANKLE", "KNEE", "LEG", "HAND", "WRIST", "ELBOW", "ARM",
    "SHOULDER", "ABDOMEN", "PELVIS", "CHEST", "THORAX", "LUNG", "HEART",
    "LIVER", "KIDNEY", "SPINE", "LSPINE", "TSPINE", "HIP", "BREAST",
    "PIED", "GENOU", "JAMBE", "MAIN", "BASSIN", "ABDO", "THORAX",
}

# Motifs de description evoquant un examen cervical. Sert d'indice positif
# quand BodyPartExamined est vide, ce qui est frequent.
MOTIFS_CERVICAUX = re.compile(
    r"CAROTID|CERVIC|\bTSA\b|\bCOU\b|NECK|SUPRA.?AORT|POLYGONE|WILLIS",
    re.IGNORECASE)

# Series a ecarter : ce ne sont pas des acquisitions primaires.
MOTIFS_DERIVES = re.compile(
    r"SCOUT|TOPO|LOCALIZER|DOSE.?REPORT|\bMIP\b|\bMPR\b|\bVRT\b|"
    r"SUBTRACT|SOUSTRAC|PERFUSION|\bBONE\b|\bOS\b\s*RECON",
    re.IGNORECASE)


@dataclass
class Rapport:
    """Issue d'un controle. `verdict` est ce qui remonte a l'ecran."""
    issue: str                                    # recevable | reserve | refus
    verdict: str | None = None                    # code pour l'API
    message: str = ""
    bloquants: list[str] = field(default_factory=list)
    reserves: list[str] = field(default_factory=list)
    indices: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.issue != "refus"

    def dict(self) -> dict:
        return {"issue": self.issue, "verdict": self.verdict,
                "message": self.message, "bloquants": self.bloquants,
                "reserves": self.reserves, "indices": self.indices}


# --------------------------------------------------------------------------- #
# Pre-vol
# --------------------------------------------------------------------------- #

def _tags(chemin: Path) -> dict:
    """Lit les en-tetes d'un fichier DICOM sans charger les pixels."""
    import pydicom
    ds = pydicom.dcmread(str(chemin), stop_before_pixels=True, force=True)

    def g(nom, defaut=""):
        v = getattr(ds, nom, None)
        return str(v).strip() if v is not None else defaut

    def f(nom):
        try:
            return float(getattr(ds, nom))
        except (TypeError, ValueError, AttributeError):
            return None

    pos = getattr(ds, "ImagePositionPatient", None)
    return {
        "modalite": g("Modality").upper(),
        "region": g("BodyPartExamined").upper(),
        "serie": g("SeriesDescription"),
        "etude": g("StudyDescription"),
        "protocole": g("ProtocolName"),
        "epaisseur": f("SliceThickness"),
        "lignes": f("Rows"),
        "colonnes": f("Columns"),
        "contraste": g("ContrastBolusAgent"),
        "patient_id": g("PatientID"),
        "date": g("StudyDate"),
        "z": float(pos[2]) if pos is not None and len(pos) > 2 else None,
    }


def prevol(fichiers: list[Path]) -> Rapport:
    """Recevabilite d'une serie a partir de ses en-tetes.

    `fichiers` est la liste des DICOM d'UNE serie. On lit le premier et le
    dernier : le premier porte les tags descriptifs, les deux ensemble donnent
    l'etendue en Z.
    """
    if not fichiers:
        return Rapport("refus", "dossier_vide",
                       "Aucun fichier DICOM exploitable dans ce dossier.")

    try:
        t = _tags(fichiers[0])
    except Exception as e:                                     # noqa: BLE001
        return Rapport("refus", "dicom_illisible",
                       f"En-tetes DICOM illisibles : {e}")

    bloquants, reserves, indices = [], [], {}

    # -- modalite ---------------------------------------------------------- #
    if t["modalite"] and t["modalite"] != MODALITE_ATTENDUE:
        bloquants.append(
            f"Modalite {t['modalite']} : seul le scanner ({MODALITE_ATTENDUE}) "
            f"permet une mesure NASCET par densitometrie.")
    elif not t["modalite"]:
        reserves.append("Modalite absente des en-tetes.")

    # -- nombre de coupes -------------------------------------------------- #
    n = len(fichiers)
    indices["coupes"] = n
    if n < COUPES_MIN:
        bloquants.append(
            f"{n} coupes : en deca de {COUPES_MIN}, il s'agit probablement "
            f"d'un localisateur ou d'une reconstruction epaisse.")

    # -- epaisseur --------------------------------------------------------- #
    indices["epaisseur_mm"] = t["epaisseur"]
    if t["epaisseur"] is None:
        reserves.append("Epaisseur de coupe absente des en-tetes.")
    elif t["epaisseur"] > EPAISSEUR_MAX_MM:
        bloquants.append(
            f"Epaisseur de coupe {t['epaisseur']:.2f} mm, au-dela de "
            f"{EPAISSEUR_MAX_MM} mm : la continuite du vaisseau en Z se degrade "
            f"trop pour une mesure fiable.")

    # -- matrice ----------------------------------------------------------- #
    if t["lignes"] and t["colonnes"]:
        indices["matrice"] = f"{int(t['lignes'])}x{int(t['colonnes'])}"
        if min(t["lignes"], t["colonnes"]) < MATRICE_MIN:
            reserves.append(
                f"Matrice {indices['matrice']} : resolution dans le plan "
                f"inferieure a l'habitude ({MATRICE_MIN}).")

    # -- etendue en Z ------------------------------------------------------ #
    # Deux points suffisent : la premiere et la derniere coupe de la serie.
    try:
        z0, z1 = t["z"], _tags(fichiers[-1])["z"]
        if z0 is not None and z1 is not None:
            etendue = abs(z1 - z0)
            indices["etendue_z_mm"] = round(etendue, 1)
            if etendue < ETENDUE_Z_MIN_MM:
                bloquants.append(
                    f"Couverture de {etendue:.0f} mm en Z : un axe carotidien "
                    f"exploitable en fait 150 a 250.")
    except Exception:                                          # noqa: BLE001
        pass

    # -- region anatomique : blanche, puis noire, puis silence ------------- #
    texte = " ".join(filter(None, (t["region"], t["serie"], t["etude"],
                                   t["protocole"]))).upper()
    indices["region"] = t["region"] or None
    indices["serie"] = t["serie"] or None

    exclue = next((r for r in REGIONS_EXCLUES
                   if re.search(rf"\b{r}\b", texte)), None)
    acceptee = (t["region"] in REGIONS_ACCEPTEES
                or bool(MOTIFS_CERVICAUX.search(texte)))

    if exclue and not acceptee:
        bloquants.append(
            f"Region « {exclue} » : les carotides se mesurent sur un examen "
            f"cervical.")
    elif not acceptee:
        # Le silence n'est pas un refus : les descriptions de serie varient
        # trop d'un centre a l'autre. controle_volume() tranchera.
        reserves.append(
            "Aucun indice de region cervicale dans les en-tetes. La region "
            "sera confirmee apres segmentation.")

    # -- serie derivee ----------------------------------------------------- #
    if MOTIFS_DERIVES.search(texte):
        bloquants.append(
            "Serie derivee (reconstruction, MIP, scout ou rapport de dose) : "
            "la mesure exige l'acquisition axiale primaire.")

    # -- produit de contraste ---------------------------------------------- #
    # 51 % des refus de la cohorte tiennent a un rehaussement insuffisant.
    # Quand le tag est vide, autant le dire AVANT de depenser le calcul.
    indices["contraste"] = t["contraste"] or None
    if not t["contraste"]:
        reserves.append(
            "Aucun produit de contraste renseigne. Sans opacification, le "
            "profil d'intensite ne presente pas de plateau luminal et la "
            "mesure du bord echouera.")

    indices["patient_id"] = t["patient_id"] or None
    indices["date_examen"] = t["date"] or None

    if bloquants:
        return Rapport("refus", "examen_non_recevable",
                       bloquants[0], bloquants, reserves, indices)
    if reserves:
        return Rapport("reserve", None,
                       f"{len(reserves)} reserve(s) — l'analyse se poursuit.",
                       [], reserves, indices)
    return Rapport("recevable", None, "Examen recevable.", [], [], indices)


# --------------------------------------------------------------------------- #
# Controle post-segmentation
# --------------------------------------------------------------------------- #

# Calibre sur la cohorte de reference. A ajuster depuis composantes.csv :
# prendre le minimum de la colonne 'voxels' des composantes SIGNIFICATIVES des
# cas valides, et descendre nettement en dessous. Un seuil devine produirait
# des refus sur des cas exploitables — c'est-a-dire le biais du § 5.3, aggrave.
VOXELS_MIN = settings.voxels_carotide_min
ETENDUE_CAROTIDE_MIN_MM = settings.etendue_carotide_min_mm


def controle_volume(seg: Path) -> Rapport:
    """Confirme la region a partir des masques produits par TotalSegmentator.

    C'est le controle qui tranche : il ne depend d'aucun tag et voit
    directement ce que le modele a trouve.
    """
    import nibabel as nib
    import numpy as np

    masques, manquants = [], []
    for cote in ("left", "right"):
        f = seg / f"internal_carotid_artery_{cote}.nii.gz"
        if not f.exists():
            manquants.append(f.name)
            continue
        masques.append(nib.load(str(f)))

    if not masques:
        return Rapport("refus", "region_incompatible",
                       "Aucun masque carotidien produit par la segmentation.",
                       manquants)

    espacement = masques[0].header.get_zooms()[:3]
    volumes = [m.get_fdata() > 0.5 for m in masques]
    union = volumes[0]
    for v in volumes[1:]:
        union = union | v

    voxels = int(sum(int(v.sum()) for v in volumes))
    indices = {"voxels_carotide": voxels,
               "espacement_mm": [round(float(e), 3) for e in espacement]}

    if voxels < VOXELS_MIN:
        return Rapport(
            "refus", "region_incompatible",
            "Aucune carotide interne detectee dans ce volume. L'examen ne "
            "couvre probablement pas la region cervicale.",
            [f"{voxels} voxels carotidiens, seuil {VOXELS_MIN}"],
            [], indices)

    # La continuite compte plus que la masse : un vrai axe carotidien s'etend
    # sur plusieurs centimetres, du bruit reste sporadique.
    z = np.where(union.any(axis=(0, 1)))[0]
    etendue = (z.max() - z.min()) * float(espacement[2]) if z.size else 0.0
    # float natif et non np.float64 : ce dictionnaire part en JSON.
    indices["etendue_carotide_mm"] = round(float(etendue), 1)

    if etendue < ETENDUE_CAROTIDE_MIN_MM:
        return Rapport(
            "refus", "couverture_insuffisante",
            f"Carotides detectees sur {etendue:.0f} mm seulement. La mesure "
            f"NASCET exige un segment distal sain en aval de la lesion.",
            [f"etendue {etendue:.0f} mm, seuil {ETENDUE_CAROTIDE_MIN_MM:.0f}"],
            [], indices)

    reserves = []
    if manquants:
        reserves.append(
            f"Masque absent d'un cote ({', '.join(manquants)}) : seul le cote "
            f"oppose sera mesure.")
    return Rapport("reserve" if reserves else "recevable", None,
                   f"Carotides sur {etendue:.0f} mm.", [], reserves, indices)
