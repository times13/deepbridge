"""Dépôt d'un dossier DICOM et suivi de son analyse."""
from fastapi import APIRouter, File, HTTPException, UploadFile

from app import contexte
from app.config import settings
from app.services.travaux import ranger_depot

router = APIRouter()


def _file():
    f = contexte.file_travaux()
    if f is None:
        raise HTTPException(503, "Service d'analyse désactivé "
                                 "(pipeline_dir absent ou activer_depot=False)")
    return f


@router.post("/travaux")
async def deposer(fichiers: list[UploadFile] = File(...)):
    """Crée un travail et rend la main.

    L'analyse dure une quinzaine de minutes : aucune requête HTTP ne tient
    cette durée. Le client interroge ensuite l'état.
    """
    try:
        dest = ranger_depot(fichiers, settings.depots_dir)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _file().deposer(dest).dict()


@router.get("/travaux")
def liste():
    f = contexte.file_travaux()
    return [t.dict() for t in f.liste()] if f else []


@router.get("/travaux/{tid}")
def etat(tid: str):
    t = _file().etat(tid)
    if not t:
        raise HTTPException(404, "travail inconnu")
    d = t.dict()
    if t.etat == "termine":
        # Recharge pour que le patient apparaisse sans redémarrer le service.
        m = contexte.mesures()
        m.recharger()
        contexte.magasin().reindexer(settings.nascet_reference,
                                     settings.dossiers_dir)
        d["axes"] = [m.axe(t.patient_id, c) for c in ("gauche", "droite")
                     if m.existe(t.patient_id, c)]
    return d


@router.post("/travaux/{tid}/annuler")
def annuler(tid: str):
    return {"annule": _file().annuler(tid)}
