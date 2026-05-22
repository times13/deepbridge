"""
DeepBridge — Backend FastAPI.
Point d'entrée : `uvicorn app.main:app --reload`
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, health, reports
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup hook. En Phase 3+ on charge ici le U-Net Keras et le modèle ONNX.
    print(f"[DeepBridge] Backend démarré.")
    print(f"[DeepBridge] model_dir = {settings.model_dir.resolve()}")
    print(f"[DeepBridge] Docs : http://localhost:8000/docs")
    yield
    print("[DeepBridge] Backend arrêté.")


app = FastAPI(
    title="DeepBridge API",
    description=(
        "Aide à la décision pour la sténose carotidienne — "
        "analyse d'images DICOM uploadées et prédiction de complications post-opératoires."
    ),
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
