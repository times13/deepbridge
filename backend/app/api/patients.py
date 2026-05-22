"""
Endpoints liés au dossier patient :
- GET /            → liste des patients
- GET /{id}        → détail d'un patient
- GET /{id}/slices/{index} → bytes DICOM d'une coupe (Phase 3)
"""
from fastapi import APIRouter, HTTPException, Response

from app.schemas.patient import PatientDetail, PatientSummary
from app.services.mocks import MOCK_PATIENTS, get_mock_patient_detail

router = APIRouter()


@router.get("", response_model=list[PatientSummary])
async def list_patients() -> list[PatientSummary]:
    """Retourne tous les dossiers patients disponibles."""
    return list(MOCK_PATIENTS.values())


@router.get("/{patient_id}", response_model=PatientDetail)
async def get_patient(patient_id: str) -> PatientDetail:
    """Détail d'un patient + ses features cliniques + IDs des coupes."""
    detail = get_mock_patient_detail(patient_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} introuvable")
    return detail


@router.get(
    "/{patient_id}/slices/{slice_index}",
    responses={200: {"content": {"application/dicom": {}}}},
)
async def get_slice(patient_id: str, slice_index: int) -> Response:
    """
    Retourne les bytes bruts du fichier DICOM d'une coupe.
    Le frontend les passe à cornerstone-wado-image-loader pour affichage.

    Phase 1 : non implémenté (501).
    Phase 3 : lecture depuis data/patients/{id}/slices/.
    """
    raise HTTPException(
        status_code=501,
        detail="Lecture des coupes pas encore implémentée (Phase 3).",
    )
