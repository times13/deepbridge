"""Analyse d'un dossier DICOM : par chemin serveur ou par televersement."""
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app import contexte
from app.config import settings
from app.services.travaux import ranger_depot
from app.validation import prevol

router = APIRouter()


def _file():
    f = contexte.file_travaux()
    if f is None:
        raise HTTPException(503, "Service d'analyse desactive "
                                 "(pipeline_dir absent ou activer_depot=False)")
    return f


def _confine(chemin: str) -> Path:
    """Verifie qu'un chemin demande par le client reste dans les racines
    declarees.

    Sans ce controle, un client pourrait faire lire n'importe quel dossier du
    serveur. Les racines autorisees sont fixees dans la configuration, jamais
    transmises par la requete.
    """
    p = Path(chemin).expanduser()
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise HTTPException(404, f"Dossier introuvable : {chemin}")
    if not p.is_dir():
        raise HTTPException(400, f"Ce n'est pas un dossier : {chemin}")
    for racine in settings.racines_dicom:
        try:
            p.relative_to(Path(racine).expanduser().resolve())
            return p
        except (ValueError, OSError):
            continue
    raise HTTPException(
        403, "Dossier hors des racines autorisees. Ajouter son parent a "
             "racines_dicom dans le fichier .env.")


# --------------------------------------------------------------------------- #
# Parcours par chemin — le chemin normal
# --------------------------------------------------------------------------- #

@router.get("/dossiers-disponibles")
def dossiers_disponibles(racine: str | None = None):
    """Sous-dossiers de premier niveau des racines DICOM declarees.

    Le navigateur ne transmet jamais de chemin de fichier a JavaScript : une
    page ne peut envoyer que du CONTENU. Televerser 600 Mo vers un serveur qui
    tourne sur la meme machine que le fichier n'a aucun sens — on laisse donc
    le serveur enumerer ce qu'il voit, et le client choisit.
    """
    racines = [_confine(racine)] if racine else [
        Path(r).expanduser() for r in settings.racines_dicom]
    sorties = []
    for r in racines:
        if not r.is_dir():
            continue
        for d in sorted(p for p in r.iterdir() if p.is_dir()):
            try:
                n = sum(1 for f in d.rglob("*") if f.is_file())
            except OSError:
                continue
            sorties.append({"nom": d.name, "chemin": str(d), "fichiers": n})
    return sorties


class DepotLocal(BaseModel):
    dossier: str


@router.post("/travaux/local")
def deposer_local(d: DepotLocal):
    """Cree un travail sur un dossier deja present sur le serveur.

    Zero octet transfere : le pipeline lit la ou le fichier se trouve deja.
    C'est aussi l'usage reel — un poste hospitalier monte le partage PACS et
    designe un dossier, il ne le televerse pas.
    """
    p = _confine(d.dossier)
    return _file().deposer(p).dict()


@router.post("/dossiers/prevol")
def controler(d: DepotLocal):
    """Recevabilite d'un dossier SANS lancer l'analyse.

    Deux secondes de lecture d'en-tetes contre douze minutes de segmentation :
    autant savoir avant de lancer.
    """
    p = _confine(d.dossier)
    fichiers = sorted(f for f in p.rglob("*") if f.is_file())
    return prevol(fichiers).dict()


# --------------------------------------------------------------------------- #
# Televersement — pour un serveur distant seulement
# --------------------------------------------------------------------------- #

@router.post("/travaux")
async def deposer(fichiers: list[UploadFile] = File(...)):
    """Depot par televersement.

    RESERVE au cas ou le serveur est distant. Sur un poste local, preferer
    /travaux/local : l'ecriture est ici synchrone et bloque la boucle
    d'evenements, ce qui fait echouer les envois de plusieurs centaines de
    megaoctets.
    """
    try:
        dest = ranger_depot(fichiers, settings.depots_dir)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _file().deposer(dest).dict()


# --------------------------------------------------------------------------- #

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
        # Recharge pour que le patient apparaisse sans redemarrer le service.
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
