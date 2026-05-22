"""
DeepBridge — Backend FastAPI.
Point d'entrée : `uvicorn app.main:app --reload`
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, health, patients, reports
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup hook. In Phase 3+ we load the U-Net model and the ONNX model here.
    # For now we just print the data directory so it's clear what the server sees.
    print(f"[DeepBridge] Backend démarré.")
    print(f"[DeepBridge] data_dir = {settings.data_dir.resolve()}")
    print(f"[DeepBridge] model_dir = {settings.model_dir.resolve()}")
    print(f"[DeepBridge] Docs : http://localhost:8000/docs")
    yield
    print("[DeepBridge] Backend arrêté.")


app = FastAPI(
    title="DeepBridge API",
    description=(
        "Aide à la décision pour la sténose carotidienne — "
        "analyse d'images DICOM et prédiction de complications post-opératoires."
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
app.include_router(patients.router, prefix="/api/patients", tags=["patients"])
app.include_router(analysis.router, prefix="/api/patients", tags=["analysis"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
