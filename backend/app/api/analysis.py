"""
Endpoint d'analyse complète d'un patient.
Orchestre (en phases ultérieures) : lecture DICOM → U-Net → géométrie NASCET/ECST
→ Random Forest → moteur de recommandation.

Phase 1 : retourne un résultat mocké réaliste par patient.
"""
from fastapi import APIRouter, HTTPException

from app.schemas.analysis import AnalysisResult
from app.services.mocks import MOCK_PATIENTS, build_mock_analysis

router = APIRouter()


@router.post("/{patient_id}/analyze", response_model=AnalysisResult)
async def analyze_patient(patient_id: str) -> AnalysisResult:
    """
    Lance l'analyse complète d'un dossier patient.

    Phases :
    1. ✓ Retour mocké réaliste par patient.
    2. Lecture des coupes DICOM depuis le disque.
    3. Inférence U-Net pour segmenter les carotides.
    4. Squelettisation + balayage perpendiculaire → NASCET/ECST.
    5. Inférence Random Forest sur les features → probabilité de complication.
    6. Moteur de recommandation → verdict argumenté.
    """
    if patient_id not in MOCK_PATIENTS:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} introuvable")
    return build_mock_analysis(patient_id)
