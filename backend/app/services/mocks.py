"""
Construction d'une AnalysisResult mockée à partir des métadonnées extraites
d'un upload DICOM. Le verdict est dérivé du sexe et de l'âge pour donner un
résultat plausible pendant que la vraie inférence (Phases 3-5) n'est pas câblée.
"""
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.analysis import (
    AnalysisResult,
    CarotidStenosis,
    ComplicationRisk,
    FactorContribution,
    Recommendation,
)


_CRITERIA = [
    "NASCET ≥ 70% : indication d'endartériectomie (NASCET trial, NEJM 1991)",
    "ECST ≥ 50% : équivalent ECST du seuil NASCET 70% (ECST trial, Lancet 1998)",
    "Risque post-opératoire acceptable < 30% (ESVS Guidelines 2023)",
]

_REASONING = {
    "surgery": (
        "Sténose NASCET ≥ 70% (seuil chirurgical des essais NASCET, 1991). "
        "Risque post-opératoire prédit inférieur à 30%. "
        "Indication d'endartériectomie carotidienne."
    ),
    "monitoring": (
        "Sténose NASCET inférieure au seuil de 70% bilatéralement. "
        "Surveillance médicale recommandée avec contrôle Doppler à 6 mois."
    ),
    "contraindicated": (
        "Sténose significative mais risque de complication post-opératoire "
        "supérieur au bénéfice attendu. Traitement médical conservateur indiqué."
    ),
}


def _derive_profile(metadata: dict) -> tuple[float, float, float, float, float, str]:
    """
    Détermine un profil d'analyse plausible à partir des métadonnées du DICOM.
    Retourne (nascet_l, ecst_l, nascet_r, ecst_r, complication_p, verdict).
    Heuristique purement démo — la vraie analyse arrive en Phases 3-5.
    """
    age = metadata.get("age") or 65
    sex = metadata.get("sex") or "M"

    if age >= 78:
        # Personne âgée : sténose sévère + risque élevé → contre-indication
        return (82.0, 71.0, 30.0, 25.0, 0.42, "contraindicated")
    if age >= 68 and sex == "M":
        # Homme âgé : sténose sévère unilatérale → chirurgie
        return (78.0, 65.0, 22.0, 18.0, 0.18, "surgery")
    # Cas standard : sténose modérée bilatérale → surveillance
    return (45.0, 38.0, 38.0, 32.0, 0.09, "monitoring")


def build_analysis_from_metadata(metadata: dict, slice_count: int) -> AnalysisResult:
    """Construit une AnalysisResult mockée à partir des métadonnées du DICOM."""
    nascet_l, ecst_l, nascet_r, ecst_r, complication_p, verdict = _derive_profile(
        metadata
    )

    # On situe les coupes critiques au milieu de la pile par défaut.
    mid = max(slice_count // 2, 0)

    stenosis_left = CarotidStenosis(
        side="left",
        nascet_percent=nascet_l,
        ecst_percent=ecst_l,
        min_diameter_mm=round(6.4 * (1 - nascet_l / 100), 2),
        ref_diameter_mm=6.4,
        critical_slice_index=mid,
        confidence=0.91,
    )
    stenosis_right = CarotidStenosis(
        side="right",
        nascet_percent=nascet_r,
        ecst_percent=ecst_r,
        min_diameter_mm=round(6.2 * (1 - nascet_r / 100), 2),
        ref_diameter_mm=6.2,
        critical_slice_index=min(mid + 10, max(slice_count - 1, 0)),
        confidence=0.88,
    )
    complication_risk = ComplicationRisk(
        probability=complication_p,
        confidence_interval=(
            max(0.0, complication_p - 0.06),
            min(1.0, complication_p + 0.09),
        ),
        top_factors=[
            FactorContribution(name="age", contribution=0.31),
            FactorContribution(name="shunt", contribution=0.18),
            FactorContribution(name="surgical_technique", contribution=0.14),
        ],
    )
    recommendation = Recommendation(
        verdict=verdict,
        reasoning=_REASONING[verdict],
        criteria_used=_CRITERIA,
    )

    # patient_id généré à la volée — on n'a pas de base de patients
    patient_id = metadata.get("patient_id_dicom") or f"upload_{uuid4().hex[:8]}"

    return AnalysisResult(
        patient_id=patient_id,
        stenosis_left=stenosis_left,
        stenosis_right=stenosis_right,
        complication_risk=complication_risk,
        recommendation=recommendation,
        timestamp=datetime.now(timezone.utc),
        report_id=str(uuid4()),
    )
