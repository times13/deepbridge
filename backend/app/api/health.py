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
    # En Phase 3+, on inspectera app.state pour confirmer que U-Net et ONNX sont chargés.
    return HealthResponse(
        status="healthy",
        models_loaded=False,
        version=settings.app_version,
    )
