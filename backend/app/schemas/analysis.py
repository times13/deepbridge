"""
Schémas Pydantic du résultat d'analyse complet.
Ce qui est retourné par `POST /api/patients/{id}/analyze` et stocké
dans les rapports.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CarotidStenosis(BaseModel):
    """Mesure de sténose pour une carotide (gauche ou droite)."""

    side: Literal["left", "right"]
    nascet_percent: float = Field(
        ...,
        ge=0,
        le=100,
        description="Pourcentage de sténose selon NASCET (référence = ICA distale)",
    )
    ecst_percent: float = Field(
        ...,
        ge=0,
        le=100,
        description="Pourcentage de sténose selon ECST (référence = diamètre estimé du vaisseau)",
    )
    min_diameter_mm: float = Field(..., description="Diamètre résiduel minimal en mm")
    ref_diameter_mm: float = Field(..., description="Diamètre de référence en mm")
    critical_slice_index: int = Field(
        ..., description="Index de la coupe où la sténose est maximale"
    )
    confidence: float = Field(
        ..., ge=0, le=1, description="Confiance moyenne du masque U-Net sur la zone"
    )


class FactorContribution(BaseModel):
    """Contribution d'une feature à la prédiction de complication (interprétabilité)."""

    name: str
    contribution: float


class ComplicationRisk(BaseModel):
    """Probabilité de complication post-opératoire prédite par le Random Forest."""

    probability: float = Field(..., ge=0, le=1)
    confidence_interval: tuple[float, float] = Field(
        ..., description="Intervalle 95% [bas, haut]"
    )
    top_factors: list[FactorContribution] = Field(
        default_factory=list,
        description="Top features contributives (feature importance ou SHAP)",
    )


class Recommendation(BaseModel):
    """
    Recommandation finale du moteur de décision, combinant sténose mesurée
    et risque de complication. Aide à la décision — pas un avis médical.
    """

    verdict: Literal["surgery", "monitoring", "contraindicated"]
    reasoning: str = Field(..., description="Justification clinique en langue naturelle")
    criteria_used: list[str] = Field(
        default_factory=list, description="Critères et seuils invoqués, avec leur source"
    )


class AnalysisResult(BaseModel):
    """Résultat d'analyse complet pour un patient."""

    patient_id: str
    stenosis_left: CarotidStenosis
    stenosis_right: CarotidStenosis
    complication_risk: ComplicationRisk
    recommendation: Recommendation
    timestamp: datetime
    report_id: str = Field(..., description="UUID du rapport, utilisable avec /api/reports/{id}")
