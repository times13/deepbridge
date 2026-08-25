"""
DeepBridge — Backend FastAPI.
Point d'entrée : `uvicorn app.main:app --reload`
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import contexte
from app.api import axes, corrections, travaux
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    bilan = contexte.demarrer()
    e, c = bilan["etude"], bilan["clinique"]
    print(f"[DeepBridge] etude    : {e['axes']} axes, {e['patients']} patients, "
          f"{e['n_refus']} refus, mediane "
          f"{e['mediane_publiee'] if e['mediane_publiee'] is None else round(e['mediane_publiee'], 1)} %"
          f"  (lecture seule)")
    print(f"[DeepBridge] clinique : {c['axes']} axes, {c['patients']} patients "
          f"-> {settings.dossiers_dir}")
    print(f"[DeepBridge] depot DICOM : "
          f"{'actif, pipeline ' + str(settings.pipeline_dir) if bilan['depot'] else 'desactive (revue seule)'}")
    print(f"[DeepBridge] Docs : http://localhost:8000/docs")
    yield
    contexte.arreter()
    print("[DeepBridge] Backend arrete.")


app = FastAPI(
    title="DeepBridge API",
    description=(
        "Aide à la décision pour la sténose carotidienne — mesure NASCET "
        "automatisée sur angioscanner, avec abstention motivée."
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

app.include_router(axes.router, prefix="/api", tags=["mesures"])
app.include_router(travaux.router, prefix="/api", tags=["analyse"])
app.include_router(corrections.router, prefix="/api", tags=["corrections"])
