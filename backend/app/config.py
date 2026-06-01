"""
Centralized configuration. Values can be overridden via environment variables
or a `.env` file at the backend root.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ──────────────────────────────────────────────────────────────
    # Paths
    # ──────────────────────────────────────────────────────────────
    data_dir: Path = Path("./data")
    model_dir: Path = Path("./app/models")

    # Model filenames (placed inside model_dir)
    unet_model_filename: str = "carotide_detector_v2.h5"
    rf_model_filename: str = "random_forest.onnx"

    # ──────────────────────────────────────────────────────────────
    # Inférence U-Net (segmentation carotides)
    # ──────────────────────────────────────────────────────────────
    img_size: int = 256            # taille d'entrée attendue par le .h5
    mask_threshold: float = 0.5    # seuil de binarisation de la prédiction
    unet_pos_weight: int = 70      # poids utilisé à l'entraînement (loss)

    # Fenêtrage par défaut si absent du DICOM (tissus mous / vaisseaux du cou).
    # Le code privilégie les valeurs inscrites dans le DICOM si présentes.
    default_window_center: int = 40
    default_window_width: int = 100

    # Sélection de la série : on EXCLUT seulement ce qui est manifestement
    # hors-sujet. On n'exige jamais de mot-clé positif (texte libre peu fiable) ;
    # l'orientation axiale + le nombre de coupes font le vrai tri.
    excluded_series_keywords: tuple[str, ...] = (
        "crane", "scout", "topogram", "localizer", "sag", "cor",
    )

    # ──────────────────────────────────────────────────────────────
    # Validation de l'examen (anti pied/main/thorax/IRM…)
    # ──────────────────────────────────────────────────────────────
    accepted_modality: str = "CT"

    # Parties du corps explicitement hors-sujet (tag BodyPartExamined ou
    # trahies par SeriesDescription). MAJUSCULES, comparaison insensible à la casse.
    excluded_body_parts: tuple[str, ...] = (
        "FOOT", "PIED", "HAND", "MAIN", "CHEST", "THORAX", "ABDOMEN",
        "PELVIS", "KNEE", "GENOU", "SPINE", "RACHIS", "BRAIN", "CERVEAU",
    )

    # Sanity check du masque prédit (sur image img_size × img_size)
    mask_min_pixels: int = 50        # une carotide plausible fait au moins ~50 px
    mask_max_pixels: int = 5000      # au-delà : aberrant (le modèle "bave")
    # Fraction minimale de coupes portant un signal carotidien crédible.
    # En dessous : probablement pas un examen du cou.
    min_fraction_slices_with_signal: float = 0.05

    # ──────────────────────────────────────────────────────────────
    # API metadata
    # ──────────────────────────────────────────────────────────────
    app_version: str = "0.1.0"

    # CORS — extend as needed
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    @property
    def unet_model_path(self) -> Path:
        return self.model_dir / self.unet_model_filename

    @property
    def rf_model_path(self) -> Path:
        return self.model_dir / self.rf_model_filename


settings = Settings()