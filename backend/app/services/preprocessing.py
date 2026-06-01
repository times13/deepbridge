"""
Prétraitement DICOM → entrée U-Net (stateless).

Responsabilité : transformer une coupe DICOM en tenseur normalisé
prêt pour le modèle (HU → fenêtrage → normalisation → redimensionnement).
"""
import numpy as np
import pydicom

from app.config import settings


def _apply_window(hu: np.ndarray, center: float, width: float) -> np.ndarray:
    """Applique un fenêtrage window/level et renvoie une image normalisée 0..1."""
    lo, hi = center - width / 2.0, center + width / 2.0
    return np.clip((hu - lo) / (hi - lo), 0.0, 1.0)


def _resolve_window(ds) -> tuple[float, float]:
    """
    Détermine (center, width) : valeurs inscrites dans le DICOM si présentes,
    sinon valeurs de configuration. Gère le cas multi-fenêtre (liste).
    """
    wc = ds.WindowCenter if "WindowCenter" in ds else settings.default_window_center
    ww = ds.WindowWidth if "WindowWidth" in ds else settings.default_window_width
    if isinstance(wc, pydicom.multival.MultiValue):
        wc = wc[0]
    if isinstance(ww, pydicom.multival.MultiValue):
        ww = ww[0]
    return float(wc), float(ww)


def preprocess_for_unet(slice_path) -> np.ndarray:
    """
    Transforme une coupe DICOM en tenseur (1, S, S, 1) prêt pour le modèle.

    Note : on relit le dataset ici (plutôt que de réutiliser
    dicom_loader.read_slice_pixels) car on a besoin des tags de fenêtrage
    du même objet `ds`. C'est un compromis assumé lisibilité/performance.
    """
    # import local pour éviter un import cv2 au chargement du module
    import cv2

    ds = pydicom.dcmread(slice_path)
    arr = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    hu = arr * slope + intercept

    wc, ww = _resolve_window(ds)
    windowed = _apply_window(hu, wc, ww)
    img8 = (windowed * 255).astype(np.uint8)
    resized = cv2.resize(img8, (settings.img_size, settings.img_size))
    x = (resized / 255.0).reshape(1, settings.img_size, settings.img_size, 1)
    return x.astype(np.float32)