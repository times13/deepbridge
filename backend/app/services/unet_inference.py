"""
Service d'inférence U-Net — segmentation des carotides.

Charge le modèle Keras (.h5) UNE SEULE FOIS (lazy singleton) et expose
`predict_mask()` qui renvoie un masque binaire propre (2 carotides).

Pensé pour être importé par les endpoints FastAPI (app/api/analysis.py),
pas exécuté en script. Stateless côté appel, le modèle est mis en cache module.
"""
import logging

import numpy as np
import tensorflow as tf
from scipy import ndimage
from tensorflow.keras.models import load_model

from app.config import settings

logger = logging.getLogger(__name__)

# Cache module — le modèle n'est chargé qu'à la première demande.
_model = None


# ────────────────────────────────────────────────────────────────────────
# Fonctions custom nécessaires pour DÉSÉRIALISER le .h5
# (mêmes définitions qu'à l'entraînement — sinon load_model échoue)
# ────────────────────────────────────────────────────────────────────────


def weighted_binary_crossentropy(y_true, y_pred):
    pos_weight = settings.unet_pos_weight
    epsilon = tf.keras.backend.epsilon()
    y_pred = tf.clip_by_value(y_pred, epsilon, 1.0 - epsilon)
    bce = -(y_true * tf.math.log(y_pred) + (1.0 - y_true) * tf.math.log(1.0 - y_pred))
    weighted = bce * (y_true * pos_weight + (1.0 - y_true))
    return tf.reduce_mean(weighted)


def dice_coefficient(y_true, y_pred, smooth=1.0):
    y_true_f = tf.cast(tf.keras.backend.flatten(y_true), tf.float32)
    y_pred_f = tf.keras.backend.flatten(y_pred)
    intersection = tf.keras.backend.sum(y_true_f * y_pred_f)
    return (2.0 * intersection + smooth) / (
        tf.keras.backend.sum(y_true_f) + tf.keras.backend.sum(y_pred_f) + smooth
    )


# ────────────────────────────────────────────────────────────────────────
# Chargement (lazy) du modèle
# ────────────────────────────────────────────────────────────────────────


def get_model():
    """Charge le modèle au premier appel puis le réutilise."""
    global _model
    if _model is None:
        path = settings.unet_model_path
        if not path.is_file():
            raise FileNotFoundError(
                f"Modèle introuvable : {path}. "
                f"Placez carotide_detector_v2.h5 dans {settings.model_dir}."
            )
        logger.info("Chargement du modèle U-Net : %s", path)
        _model = load_model(
            path,
            custom_objects={
                "weighted_binary_crossentropy": weighted_binary_crossentropy,
                "dice_coefficient": dice_coefficient,
            },
            compile=False,  # inférence seule, pas besoin de recompiler
        )
        logger.info("Modèle U-Net chargé (input %s)", _model.input_shape)
    return _model


# ────────────────────────────────────────────────────────────────────────
# Post-traitement
# ────────────────────────────────────────────────────────────────────────


def _keep_two_largest(binary_mask: np.ndarray) -> np.ndarray:
    """
    Ne conserve que les 2 plus grandes composantes connexes
    (= les 2 carotides), élimine le bruit. Si moins de 2, renvoie tel quel.
    """
    labeled, n = ndimage.label(binary_mask)
    if n <= 2:
        return binary_mask
    sizes = ndimage.sum(binary_mask, labeled, range(1, n + 1))
    keep_labels = np.argsort(sizes)[-2:] + 1
    return np.isin(labeled, keep_labels).astype(np.uint8)


# ────────────────────────────────────────────────────────────────────────
# API publique du service
# ────────────────────────────────────────────────────────────────────────


def predict_mask(preprocessed: np.ndarray, clean: bool = True) -> np.ndarray:
    """
    Prédit le masque des carotides pour une coupe prétraitée.

    Args:
        preprocessed: tenseur (1, S, S, 1) issu de dicom_loader.preprocess_for_unet
        clean: si True, applique le post-traitement (2 plus grosses composantes)

    Returns:
        masque binaire uint8 de forme (S, S), valeurs {0, 1}
    """
    model = get_model()
    pred = model.predict(preprocessed, verbose=0)
    s = settings.img_size
    prob = pred[0].reshape(s, s)
    binary = (prob > settings.mask_threshold).astype(np.uint8)
    if clean:
        binary = _keep_two_largest(binary)
    return binary


def predict_probability(preprocessed: np.ndarray) -> np.ndarray:
    """Variante : renvoie la carte de probabilité brute (S, S) sans seuillage."""
    model = get_model()
    pred = model.predict(preprocessed, verbose=0)
    s = settings.img_size
    return pred[0].reshape(s, s)