"""
Endpoints de rapports. Phase 1 : tout retourne 501.
Phase 7 : récupération JSON depuis SQLite + génération PDF via reportlab.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{report_id}")
async def get_report(report_id: str):
    """Récupère un rapport JSON par son UUID."""
    raise HTTPException(
        status_code=501, detail="Récupération de rapport pas encore implémentée (Phase 7)."
    )


@router.get("/{report_id}.pdf")
async def get_report_pdf(report_id: str):
    """Télécharge le rapport au format PDF."""
    raise HTTPException(
        status_code=501, detail="Export PDF pas encore implémenté (Phase 7)."
    )
