"""
Corrections du radiologue.

Le radiologue qui corrige une mesure ou tranche un refus produit ce qui manque
à l'étude : de la vérité terrain individuelle. Chaque relecture non enregistrée
est définitivement perdue — cette table ne se reconstitue pas après coup.
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import contexte

router = APIRouter()


class Correction(BaseModel):
    patient: str
    cote: str
    cohorte: str = "etude"
    # mesurable | non_mesurable | pas_de_stenose
    verdict_humain: str
    auteur: str | None = None
    nascet_humain: float | None = Field(None, ge=0, le=100)
    d_min: float | None = None
    d_ref: float | None = None
    z: int | None = None
    commentaire: str | None = None


@router.post("/corrections")
def saisir(c: Correction):
    """Enregistre le jugement humain ET le verdict machine du moment.

    Ne garder que la valeur humaine perdrait la comparaison dès que le
    pipeline évolue : on ne saurait plus contre quelle version la correction
    a été faite.
    """
    return contexte.magasin().corriger(
        c.patient, c.cote, c.cohorte, c.verdict_humain, auteur=c.auteur,
        nascet_humain=c.nascet_humain, d_min=c.d_min, d_ref=c.d_ref, z=c.z,
        commentaire=c.commentaire)


@router.get("/corrections")
def liste(patient: str | None = None, cote: str | None = None):
    return contexte.magasin().corrections(patient, cote)


@router.get("/corrections/accord")
def accord():
    """Taux d'accord entre verdict automatique et jugement humain.

    Sur une chaîne qui s'abstient 4 fois sur 10, savoir si elle s'abstient
    à raison vaut autant que la mesure elle-même.
    """
    return contexte.magasin().accord()
