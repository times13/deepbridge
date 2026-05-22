"""
Schémas Pydantic décrivant un patient et ses features cliniques.
Ces modèles définissent le contrat JSON renvoyé par les endpoints `/patients/*`.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class PatientSummary(BaseModel):
    """Résumé d'un patient, affiché dans la liste des dossiers."""

    id: str = Field(..., description="Identifiant anonymisé unique")
    name: str = Field(..., description="Libellé affichable")
    age: int
    sex: Literal["M", "F"]
    scan_date: date
    slice_count: int = Field(..., description="Nombre de coupes DICOM disponibles")


class PatientFeatures(BaseModel):
    """
    Features cliniques utilisées en entrée du modèle Random Forest de prédiction
    de complications. Mapping basé sur les colonnes du CSV de Groupe 4.
    """

    age: int
    sex: Literal["M", "F"]
    s_plus: Optional[int] = Field(None, description="Variable clinique S+")
    surgical_technique: Optional[Literal["patch", "eversion"]] = None
    shunt: bool = Field(False, description="Shunt utilisé pendant l'opération")
    arterio: bool = False
    re_inter: bool = False
    anomalie: bool = False
    anomalie_comm: bool = False


class PatientDetail(BaseModel):
    """Détail complet d'un patient, retourné par `GET /api/patients/{id}`."""

    id: str
    name: str
    scan_date: date
    slice_count: int
    features: PatientFeatures
    slices: list[str] = Field(
        ..., description="IDs des coupes — utilisables avec /slices/{index}"
    )
