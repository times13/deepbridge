"""
Endpoint d'analyse — POST /api/analyze.
Le médecin uploade les .dcm d'UN nouveau patient, le backend fait l'inférence
avec les modèles pré-entraînés et retourne le rapport complet.
"""
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.analysis import AnalysisResult
from app.services.dicom_loader import (
    extract_dicom_metadata,
    is_dicom_bytes,
    sort_dicom_files,
)
from app.services.mocks import build_analysis_from_metadata

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/analyze", response_model=AnalysisResult)
async def analyze_patient(
    files: list[UploadFile] = File(
        ..., description="Fichiers DICOM (.dcm) d'un seul patient"
    ),
) -> AnalysisResult:
    """
    Reçoit les coupes DICOM d'un nouveau patient, les trie, extrait les
    métadonnées, et lance l'inférence.

    Phases :
    1. ✓ Validation des uploads + tri par InstanceNumber + extraction métadonnées
       + retour mocké basé sur les métadonnées extraites.
    2. ✓ Lecture DICOM via pydicom (cette phase).
    3. Inférence U-Net Keras sur chaque coupe → masque carotides.
    4. Squelettisation + balayage perpendiculaire → NASCET / ECST.
    5. Inférence Random Forest sur les features → probabilité de complication.
    6. Moteur de recommandation → verdict argumenté.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier reçu.")

    with tempfile.TemporaryDirectory(prefix="deepbridge_") as tmp:
        tmp_dir = Path(tmp)
        valid_files: list[Path] = []
        rejected = 0

        for upload in files:
            content = await upload.read()
            if not is_dicom_bytes(content):
                rejected += 1
                logger.info("Fichier rejeté (non-DICOM) : %s", upload.filename)
                continue
            # Sauvegarde temporaire — on a besoin d'un Path pour pydicom
            save_path = tmp_dir / (upload.filename or f"slice_{len(valid_files)}.dcm")
            save_path.write_bytes(content)
            valid_files.append(save_path)

        if not valid_files:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Aucun fichier DICOM valide dans l'upload "
                    f"({rejected} fichier(s) rejeté(s) — vérifie qu'ils ont bien "
                    f"le marqueur 'DICM' à l'offset 128)."
                ),
            )

        sorted_files = sort_dicom_files(valid_files)
        metadata = extract_dicom_metadata(sorted_files[0])

        logger.info(
            "Upload analysé : %d coupes valides, %d rejetées, métadonnées=%s",
            len(sorted_files),
            rejected,
            {k: metadata.get(k) for k in ("age", "sex", "scan_date", "modality")},
        )

        # Phase 2 : on retourne un résultat mocké réaliste basé sur les
        # métadonnées extraites. La vraie inférence U-Net + Random Forest
        # arrive en Phases 3-5.
        return build_analysis_from_metadata(
            metadata=metadata, slice_count=len(sorted_files)
        )
