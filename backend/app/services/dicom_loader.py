"""
Lecture DICOM bas niveau (stateless).

Responsabilité unique : lire des fichiers DICOM et en extraire des données
brutes — validation de fichier, tri des coupes, métadonnées, pixels HU.
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
# Tri des coupes par InstanceNumber
# ────────────────────────────────────────────────────────────────────────


def _get_instance_number(path: Path) -> int:
    """Lit le tag InstanceNumber sans charger les pixels."""
    try:
        ds = pydicom.dcmread(path, stop_before_pixels=True)
        return int(getattr(ds, "InstanceNumber", 0) or 0)
    except (InvalidDicomError, AttributeError, ValueError, OSError):
        return 0


def sort_dicom_files(files: list[Path]) -> list[Path]:
    """
    Trie les coupes DICOM par InstanceNumber (séquence anatomique correcte).
    Fallback sur le tri alphabétique si InstanceNumber est absent ou bruité.
    """
    if not files:
        return []
    indexed = [(_get_instance_number(f), f) for f in files]
    nonzero = sum(1 for n, _ in indexed if n > 0)
    if nonzero < len(indexed) // 2:
        return sorted(files)
    return [f for _, f in sorted(indexed, key=lambda x: x[0])]


# ────────────────────────────────────────────────────────────────────────
# Extraction de métadonnées
# ────────────────────────────────────────────────────────────────────────


def extract_dicom_metadata(dicom_path: Path) -> dict:
    """
    Extrait les métadonnées patient/study du premier DICOM uploadé.
    Tous les champs sont optionnels — on remplit ce qu'on trouve.
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
                metadata["age"] = (sd_d - bd_d).days // 365
            except (ValueError, IndexError):
                pass

    # Sexe (M/F, sinon défaut M)
    sex = str(getattr(ds, "PatientSex", "") or "").upper().strip()
    metadata["sex"] = sex if sex in ("M", "F") else "M"

    # Date d'examen
    sd = str(getattr(ds, "StudyDate", "") or "")
    if len(sd) == 8:
        try:
            metadata["scan_date"] = date(int(sd[:4]), int(sd[4:6]), int(sd[6:8]))
        except ValueError:
            pass

    metadata["patient_id_dicom"] = str(getattr(ds, "PatientID", "") or "")
    metadata["modality"] = str(getattr(ds, "Modality", "") or "")
    metadata["series_description"] = str(getattr(ds, "SeriesDescription", "") or "")
    return metadata


# ────────────────────────────────────────────────────────────────────────
# Lecture de pixels (HU)
# ────────────────────────────────────────────────────────────────────────


def read_slice_pixels(slice_path: Path) -> np.ndarray:
    """
    Lit le tableau de pixels d'une coupe avec rescale appliqué (HU pour CT).
    """
    ds = pydicom.dcmread(slice_path)
    arr = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    return arr * slope + intercept