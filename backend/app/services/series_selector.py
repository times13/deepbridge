"""
Sélection de la série carotidienne pertinente (stateless).

Responsabilité unique : parmi toutes les séries d'un dossier patient,
choisir celle des coupes axiales du cou. S'appuie sur deux critères fiables
(orientation axiale + nombre de coupes) plutôt que sur le texte libre.
"""
import logging
from pathlib import Path

import pydicom

from app.config import settings
from app.services.dicom_loader import is_dicom_file, sort_dicom_files

logger = logging.getLogger(__name__)


def _is_axial(ds) -> bool:
    """
    Vrai si la coupe est axiale (transversale).
    Une axiale a ImageOrientationPatient ≈ [1,0,0,0,1,0].
    Un scout sagittal/coronal a d'autres valeurs → rejeté.
    """
    iop = getattr(ds, "ImageOrientationPatient", None)
    if iop is None or len(iop) != 6:
        return False
    rounded = [round(float(v)) for v in iop]
    return rounded == [1, 0, 0, 0, 1, 0]


def _series_is_relevant(ds) -> bool:
    """
    On EXCLUT seulement ce qui est manifestement hors-sujet (crâne, scout…).
    On n'EXIGE jamais de mot-clé positif : l'orientation axiale et le nombre
    de coupes font le vrai tri.
    """
    desc = str(getattr(ds, "SeriesDescription", "") or "").lower()
    return not any(bad in desc for bad in settings.excluded_series_keywords)


def select_carotid_series(patient_dir: Path) -> list[Path]:
    """
    Sélectionne la série axiale du cou la plus fournie.
    Heuristique :
      1. parcourir les sous-dossiers (= séries)
      2. ne garder que les séries axiales et non exclues
      3. choisir celle qui contient le plus de coupes (acquisition fine)

    Retourne la liste triée des .dcm de la série retenue, ou [] si rien.
    """
    candidates: list[tuple[int, list[Path]]] = []

    subdirs = [d for d in patient_dir.iterdir() if d.is_dir()]
    search_dirs = subdirs if subdirs else [patient_dir]

    for serie_dir in search_dirs:
        dcm_files = [f for f in serie_dir.iterdir() if is_dicom_file(f)]
        if not dcm_files:
            continue
        try:
            ds = pydicom.dcmread(dcm_files[0], stop_before_pixels=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("Série illisible %s : %s", serie_dir.name, e)
            continue

        if not _is_axial(ds):
            continue
        if not _series_is_relevant(ds):
            continue

        candidates.append((len(dcm_files), dcm_files))

    if not candidates:
        logger.warning("Aucune série carotidienne axiale trouvée dans %s", patient_dir)
        return []

    _, best = max(candidates, key=lambda c: c[0])
    return sort_dicom_files(best)