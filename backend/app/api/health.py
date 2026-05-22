"""
Endpoint de santé. Vérifie que le backend tourne et que les modèles sont chargés.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    models_loaded: bool
    version: str


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    # In Phase 3+ we'll inspect app.state to confirm U-Net and ONNX are loaded.
    return HealthResponse(
        status="healthy",
        models_loaded=False,
        version=settings.app_version,
    )
