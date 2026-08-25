"""
Lecture DICOM bas niveau (stateless).

Responsabilité unique : lire des fichiers DICOM et en extraire des données
brutes — validation de fichier, métadonnées, pixels HU.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne choisit pas la série à mesurer et n'ordonne pas les coupes. Ces deux
décisions appartiennent à `pipeline/etape0_lot_segmentation.py`, qui regroupe
les fichiers par SeriesInstanceUID et les trie par position spatiale. Les
dupliquer ici ferait mesurer à l'application autre chose que ce que l'étude a
validé sur 292 axes.
"""
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────
# Validation de fichier DICOM
# ────────────────────────────────────────────────────────────────────────


def is_dicom_bytes(content: bytes) -> bool:
    """
    Vérifie que les bytes d'un upload sont un DICOM valide.
    DICOM a un préambule de 128 octets suivi du marqueur magique "DICM".
    """
    return len(content) >= 132 and content[128:132] == b"DICM"


def is_dicom_file(path: Path) -> bool:
    """Même vérification qu'`is_dicom_bytes` mais sur un fichier disque."""
    if not path.is_file() or path.name.startswith("."):
        return False
    try:
        if path.stat().st_size < 132:
            return False
        with open(path, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


# ────────────────────────────────────────────────────────────────────────
# Extraction de métadonnées
# ────────────────────────────────────────────────────────────────────────


def extract_dicom_metadata(dicom_path: Path) -> dict:
    """
    Extrait les métadonnées patient/study du premier DICOM uploadé.

    Les champs sont OPTIONNELS et valent None quand le tag est absent. Aucune
    valeur n'est devinée : l'âge, le sexe et le statut symptomatique entrent
    dans le calcul du risque de complication, et une valeur par défaut y
    passerait pour une donnée mesurée.
    """
    try:
        ds = pydicom.dcmread(dicom_path, stop_before_pixels=True)
    except (InvalidDicomError, OSError) as e:
        logger.warning("Lecture impossible de %s : %s", dicom_path, e)
        return {}

    metadata: dict = {}

    # Âge — DICOM le stocke en chaîne type "072Y"
    age_str = str(getattr(ds, "PatientAge", "") or "").strip()
    if age_str.endswith("Y"):
        try:
            metadata["age"] = int(age_str[:-1])
        except ValueError:
            pass
    if "age" not in metadata:
        bd = str(getattr(ds, "PatientBirthDate", "") or "")
        sd = str(getattr(ds, "StudyDate", "") or "")
        if len(bd) == 8 and len(sd) == 8:
            try:
                bd_d = date(int(bd[:4]), int(bd[4:6]), int(bd[6:8]))
                sd_d = date(int(sd[:4]), int(sd[4:6]), int(sd[6:8]))
                # 365.25 et non 365 : sur un patient de 75 ans, l'écart
                # atteint plus de six mois.
                metadata["age"] = int((sd_d - bd_d).days / 365.25)
            except (ValueError, IndexError):
                pass
    metadata.setdefault("age", None)

    # Sexe — None si absent ou illisible, JAMAIS une valeur par défaut.
    # Un sexe deviné deviendrait un prédicteur du modèle de risque sans que
    # personne ne sache qu'il a été inventé. None force l'appelant à demander
    # l'information, ce que l'écran doit faire de toute façon pour le statut
    # symptomatique.
    sex = str(getattr(ds, "PatientSex", "") or "").upper().strip()
    metadata["sex"] = sex if sex in ("M", "F") else None

    # Date d'examen
    sd = str(getattr(ds, "StudyDate", "") or "")
    metadata["scan_date"] = None
    if len(sd) == 8:
        try:
            metadata["scan_date"] = date(int(sd[:4]), int(sd[4:6]), int(sd[6:8]))
        except ValueError:
            pass

    metadata["patient_id_dicom"] = str(getattr(ds, "PatientID", "") or "") or None
    metadata["modality"] = str(getattr(ds, "Modality", "") or "") or None
    metadata["series_description"] = (
        str(getattr(ds, "SeriesDescription", "") or "") or None)
    return metadata


def champs_manquants(metadata: dict) -> list[str]:
    """Champs indispensables au calcul du risque et absents des en-têtes.

    L'écran de résultat s'en sert pour demander au clinicien ce que le DICOM
    ne porte pas, plutôt que de produire une estimation sur des valeurs
    inventées.
    """
    return [c for c in ("age", "sex") if not metadata.get(c)]


# ────────────────────────────────────────────────────────────────────────
# Lecture de pixels (HU)
# ────────────────────────────────────────────────────────────────────────


def read_slice_pixels(slice_path: Path) -> np.ndarray:
    """
    Lit le tableau de pixels d'une coupe avec rescale appliqué (HU pour CT).

    Sert à prévisualiser un dépôt AVANT analyse, quand le ct.nii.gz n'existe
    pas encore. Une fois l'analyse faite, les coupes sont servies depuis le
    NIfTI : `z_minimum` y est un index, donc la coupe affichée au radiologue
    est celle que la chaîne a mesurée, par construction.
    """
    ds = pydicom.dcmread(slice_path)
    arr = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    return arr * slope + intercept