"""
Données mockées pour la Phase 1.
Trois profils patients réalistes correspondant aux trois verdicts cliniques :
- PATIENT_001 → sténose sévère côté gauche → chirurgie recommandée
- PATIENT_002 → sténose modérée bilatérale → surveillance
- PATIENT_003 → sténose sévère mais risque opératoire élevé → contre-indication

Ces fixtures permettent au frontend de développer toute son UI sans attendre
les vrais modèles.
"""
from datetime import date, datetime, timezone
from uuid import uuid4

from app.schemas.analysis import (
    AnalysisResult,
    CarotidStenosis,
    ComplicationRisk,
    FactorContribution,
    Recommendation,
)
from app.schemas.patient import PatientDetail, PatientFeatures, PatientSummary

MOCK_PATIENTS: dict[str, PatientSummary] = {
    "PATIENT_001": PatientSummary(
        id="PATIENT_001",
        name="Patient 001",
        age=72,
        sex="M",
        scan_date=date(2021, 1, 18),
        slice_count=412,
    ),
    "PATIENT_002": PatientSummary(
        id="PATIENT_002",
        name="Patient 002",
        age=68,
        sex="F",
        scan_date=date(2021, 2, 4),
        slice_count=389,
    ),
    "PATIENT_003": PatientSummary(
        id="PATIENT_003",
        name="Patient 003",
        age=79,
        sex="M",
        scan_date=date(2021, 3, 12),
        slice_count=434,
    ),
}

_MOCK_FEATURES: dict[str, PatientFeatures] = {
    "PATIENT_001": PatientFeatures(
        age=72, sex="M", s_plus=1, surgical_technique="patch", shunt=False,
    ),
    "PATIENT_002": PatientFeatures(
        age=68, sex="F", s_plus=0, surgical_technique="eversion", shunt=False,
    ),
    "PATIENT_003": PatientFeatures(
        age=79, sex="M", s_plus=1, surgical_technique="patch",
        shunt=True, arterio=True, anomalie=True,
    ),
}


def get_mock_patient_detail(patient_id: str) -> PatientDetail | None:
    """Construit un PatientDetail mocké à partir du dict MOCK_PATIENTS."""
    summary = MOCK_PATIENTS.get(patient_id)
    if summary is None:
        return None
    return PatientDetail(
        id=summary.id,
        name=summary.name,
        scan_date=summary.scan_date,
        slice_count=summary.slice_count,
        features=_MOCK_FEATURES[patient_id],
        slices=[f"slice_{i:04d}" for i in range(summary.slice_count)],
    )


# Profil mocké par patient : (nascet_left, ecst_left, nascet_right, ecst_right,
#                              complication_proba, verdict)
_ANALYSIS_PROFILES: dict[str, tuple[float, float, float, float, float, str]] = {
    "PATIENT_001": (78.0, 65.0, 22.0, 18.0, 0.18, "surgery"),
    "PATIENT_002": (45.0, 38.0, 38.0, 32.0, 0.09, "monitoring"),
    "PATIENT_003": (82.0, 71.0, 30.0, 25.0, 0.42, "contraindicated"),
}

_REASONING: dict[str, str] = {
    "surgery": (
        "Sténose NASCET gauche ≥ 70% (seuil chirurgical des essais NASCET, 1991). "
        "Risque post-opératoire prédit inférieur à 30%. "
        "Indication d'endartériectomie carotidienne du côté gauche."
    ),
    "monitoring": (
        "Sténose NASCET inférieure au seuil de 70% bilatéralement. "
        "Surveillance médicale recommandée avec contrôle Doppler à 6 mois."
    ),
    "contraindicated": (
        "Sténose significative mais risque de complication post-opératoire "
        "supérieur au bénéfice attendu. Traitement médical conservateur "
        "(antiagrégant + statine + contrôle des facteurs de risque) indiqué."
    ),
}

_CRITERIA = [
    "NASCET ≥ 70% : indication d'endartériectomie (NASCET trial, NEJM 1991)",
    "ECST ≥ 50% : équivalent ECST du seuil NASCET 70% (ECST trial, Lancet 1998)",
    "Risque post-opératoire acceptable < 30% (ESVS Guidelines 2023)",
]


def build_mock_analysis(patient_id: str) -> AnalysisResult:
    """Construit une AnalysisResult mockée mais réaliste pour un patient donné."""
    profile = _ANALYSIS_PROFILES.get(
        patient_id, (60.0, 50.0, 30.0, 25.0, 0.15, "monitoring")
    )
    nascet_l, ecst_l, nascet_r, ecst_r, complication_p, verdict = profile

    stenosis_left = CarotidStenosis(
        side="left",
        nascet_percent=nascet_l,
        ecst_percent=ecst_l,
        min_diameter_mm=round(6.4 * (1 - nascet_l / 100), 2),
        ref_diameter_mm=6.4,
        critical_slice_index=178,
        confidence=0.91,
    )
    stenosis_right = CarotidStenosis(
        side="right",
        nascet_percent=nascet_r,
        ecst_percent=ecst_r,
        min_diameter_mm=round(6.2 * (1 - nascet_r / 100), 2),
        ref_diameter_mm=6.2,
        critical_slice_index=192,
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

    return AnalysisResult(
        patient_id=patient_id,
        stenosis_left=stenosis_left,
        stenosis_right=stenosis_right,
        complication_risk=complication_risk,
        recommendation=recommendation,
        timestamp=datetime.now(timezone.utc),
        report_id=str(uuid4()),
    )
