"""
Validation de l'examen — défense en couches (stateless).

Responsabilité : décider si un examen est bien un CT du cou
exploitable pour les carotides, et écarter le hors-sujet (pied, IRM…).
Deux niveaux :
  - validate_examination()  : PRÉ-inférence (modalité, région anatomique)
  - sanity_check_stack()    : POST-inférence (continuité du signal sur la pile)

"""
import logging

import numpy as np
import pydicom

from app.config import settings

logger = logging.getLogger(__name__)


def validate_examination(slice_path) -> tuple[bool, str]:
    """
    Validation PRÉ-inférence sur une coupe représentative de la série.
    Couches 1-2 : modalité + région anatomique. Retourne (ok, raison).
    """
    try:
        ds = pydicom.dcmread(slice_path, stop_before_pixels=True)
    except Exception as e:  # noqa: BLE001
        return False, f"DICOM illisible : {e}"

    # Couche 1 — modalité
    modality = str(getattr(ds, "Modality", "") or "").upper()
    if modality != settings.accepted_modality:
        return False, (
            f"Modalité '{modality or '?'}' non supportée "
            f"({settings.accepted_modality} attendu)"
        )

    # Couche 2 — région anatomique (tag dédié, si renseigné)
    body_part = str(getattr(ds, "BodyPartExamined", "") or "").upper()
    if body_part and any(x in body_part for x in settings.excluded_body_parts):
        return False, f"Région '{body_part}' hors-sujet (carotides = cou)"

    # Couche 2bis — description (texte libre, garde-fou)
    desc = str(getattr(ds, "SeriesDescription", "") or "").upper()
    if any(x in desc for x in settings.excluded_body_parts):
        return False, f"Série '{desc}' hors-sujet"

    return True, "Validation pré-inférence OK"


def sanity_check_stack(slice_masks: list[np.ndarray]) -> tuple[bool, str]:
    """
    Validation POST-inférence sur la pile entière de masques prédits.

    Le signal fiable n'est pas une coupe isolée mais la CONTINUITÉ : un vrai
    cou présente ~2 carotides sur de nombreuses coupes ; un examen hors-sujet
    ne produit que du bruit sporadique. Retourne (ok, raison).
    """
    if not slice_masks:
        return False, "Aucune coupe analysée"

    n_total = len(slice_masks)
    n_with_signal = sum(
        1 for m in slice_masks
        if settings.mask_min_pixels <= int(m.sum()) <= settings.mask_max_pixels
    )

    if n_with_signal == 0:
        return False, "Aucune carotide détectée — examen probablement hors-sujet"

    fraction = n_with_signal / n_total
    if fraction < settings.min_fraction_slices_with_signal:
        return False, (
            f"Signal carotidien trop rare ({n_with_signal}/{n_total} coupes, "
            f"{fraction:.1%}) — probablement pas un examen du cou"
        )

    return True, f"Carotides détectées sur {n_with_signal}/{n_total} coupes ({fraction:.1%})"