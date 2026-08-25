"""Consultation des mesures carotidiennes."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app import contexte
from app.config import settings

router = APIRouter()


@router.get("/synthese")
def synthese():
    """Les deux cohortes, séparées. La cohorte d'étude ne bouge jamais."""
    m = contexte.mesures()
    return {"etude": m.synthese("etude"), "clinique": m.synthese("clinique")}


@router.get("/axes")
def axes(verdict: str | None = None, cohorte: str = "etude"):
    return contexte.mesures().liste(verdict, cohorte)


@router.get("/file-prioritaire")
def file_prioritaire():
    """Axes non mesurables, triés par sténose présumée décroissante."""
    return contexte.mesures().file_prioritaire()


@router.get("/patients/{patient}")
def patient(patient: str):
    return contexte.mesures().patient(patient, settings.seuil_symptomatique,
                                      settings.seuil_asymptomatique)


@router.get("/artefacts/{patient}/{cote}/{nom}")
def artefact(patient: str, cote: str, nom: str):
    m = contexte.mesures()
    for racine in (m.mesures, m.dossiers / patient):
        cand = racine / f"{patient}_{cote}" / nom
        try:
            # Confinement : rien hors des racines déclarées.
            cand.resolve().relative_to(racine.resolve())
        except ValueError:
            continue
        if cand.is_file():
            return FileResponse(cand)
    raise HTTPException(404, "artefact absent")
