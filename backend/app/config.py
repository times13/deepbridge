"""
Configuration centralisée. Surchargeable par variables d'environnement ou par
un fichier `.env` à la racine du backend.
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ──────────────────────────────────────────────────────────────
    # Chemins
    # ──────────────────────────────────────────────────────────────
    data_dir: Path = Path("../data")
    pipeline_dir: Path = Path("../pipeline")
    python_pipeline: str = "python"

    # Executable TotalSegmentator. Il vit dans le venv du pipeline, absent du
    # PATH du processus uvicorn : l'appeler par son nom seul echoue en
    # WinError 2. On le designe donc explicitement.
    totalsegmentator: str = "TotalSegmentator"


    # Cohorte d'ETUDE — 292 axes, figée, LECTURE SEULE.
    # Les chiffres du mémoire (médiane 48,6 %, biais p = 3e-7) ne sont
    # vérifiables que si ce fichier ne bouge plus.
    nascet_reference: Path = Path("../data/reference/nascet.csv")

    # Dossiers CLINIQUES — un sous-dossier par patient analysé par
    # l'application. Issue à J30 inconnue : ces patients n'entrent ni dans
    # les statistiques du mémoire, ni dans la base de comparaison du risque.
    dossiers_dir: Path = Path("../data/dossiers")

    # Figures produites par etape2c / etape2d pour la cohorte d'étude.
    mesures_dir: Path = Path("../data/mesures_all")

    # Volumes et masques. Dossier de TRAVAIL, pas archive : ct.nii.gz pèse
    # 0,5 à 1 Go par patient et se reconstruit depuis le PACS.
    resultats_dir: Path = Path("../data/Resultats")

    # Dépôts temporaires et bases locales.
    # Racines ou le serveur cherche les dossiers DICOM. Le client ne peut
    # designer qu'un dossier SITUE SOUS l'une d'elles : sans ce confinement,
    # une requete pourrait faire lire n'importe quel dossier du serveur.
    racines_dicom: list[str] = ["../data/depots"]

    depots_dir: Path = Path("../data/depots")
    base_travaux: Path = Path("../data/travaux.sqlite")
    base_index: Path = Path("../data/index.sqlite")

    # ──────────────────────────────────────────────────────────────
    # Analyse
    # ──────────────────────────────────────────────────────────────
    device: str = "cpu"                 # cpu | gpu
    activer_depot: bool = True          # False = revue seule, aucun calcul

    # ──────────────────────────────────────────────────────────────
    # Seuils cliniques — issus des essais randomisés NASCET / ECST.
    # Ce ne sont pas des paramètres d'implémentation : ils encodent la
    # comparaison entre opérer et ne pas opérer, que les données locales
    # ne contiennent pas (tous les patients de la base ont été opérés).
    # ──────────────────────────────────────────────────────────────
    seuil_symptomatique: float = 50.0
    seuil_asymptomatique: float = 70.0

    # ──────────────────────────────────────────────────────────────
    # Validation d'examen — voir app/validation.py.
    # Repris de pipeline/inventory_dicom.py pour que l'application applique
    # les MÊMES critères que l'étude : un examen accepté ici doit être
    # comparable aux 292 axes de la cohorte de référence.
    # ──────────────────────────────────────────────────────────────
    accepted_modality: str = "CT"
    epaisseur_max_mm: float = 1.5
    coupes_min: int = 100
    etendue_z_min_mm: float = 80.0

    # Confirmation post-segmentation.
    # À CALIBRER sur composantes.csv : minimum de la colonne 'voxels' des
    # composantes significatives, puis descendre nettement en dessous. Un
    # seuil trop haut refuserait les carotides fines — donc les sténoses
    # serrées, et le biais de sélection s'en trouverait aggravé.
    voxels_carotide_min: int = 500
    etendue_carotide_min_mm: float = 60.0

    # ──────────────────────────────────────────────────────────────
    # API
    # ──────────────────────────────────────────────────────────────
    app_version: str = "0.2.0"

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]


settings = Settings()
