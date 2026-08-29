"""
Objets partagés, construits une fois au démarrage.

FastAPI n'a pas de conteneur d'injection : on centralise ici plutôt que
d'éparpiller des singletons dans les routeurs. `demarrer()` est appelé par le
lifespan de main.py, les routeurs lisent les accesseurs.
"""
from app.config import settings
from app.services.magasin import Magasin
from app.services.mesures import Mesures
from app.services.travaux import FileTravaux

_mesures: Mesures | None = None
_magasin: Magasin | None = None
_file: FileTravaux | None = None


def demarrer() -> dict:
    """Construit les services. Retourne un résumé pour le journal de démarrage."""
    global _mesures, _magasin, _file

    settings.dossiers_dir.mkdir(parents=True, exist_ok=True)
    settings.depots_dir.mkdir(parents=True, exist_ok=True)

    _mesures = Mesures(settings.nascet_reference, settings.dossiers_dir,
                       settings.mesures_dir)
    _magasin = Magasin(settings.base_index)
    _magasin.reindexer(settings.nascet_reference, settings.dossiers_dir)

    # Sans pipeline, le dépôt DICOM est désactivé : utile pour montrer
    # l'application sans risquer de déclencher une segmentation de 12 minutes.
    if settings.activer_depot and settings.pipeline_dir.is_dir():
        settings.resultats_dir.mkdir(parents=True, exist_ok=True)

        def _apres_analyse(pid: str) -> None:
            """Recharge les mesures dès qu'un travail aboutit.

            Appelé par le worker, non par le client : le rechargement ne doit
            pas dépendre du fait qu'une interface interroge encore ce travail.
            """
            _mesures.recharger()
            _magasin.reindexer(settings.nascet_reference, settings.dossiers_dir)

        _file = FileTravaux(settings.base_travaux, settings.resultats_dir,
                            settings.dossiers_dir, settings.pipeline_dir,
                            python=settings.python_pipeline,
                            totalsegmentator=settings.totalsegmentator,
                            device=settings.device,
                            au_terme=_apres_analyse)

    return {"etude": _mesures.synthese("etude"),
            "clinique": _mesures.synthese("clinique"),
            "depot": _file is not None}


def arreter():
    if _file is not None:
        _file.arreter()


def mesures() -> Mesures:
    if _mesures is None:
        raise RuntimeError("contexte non démarré")
    return _mesures


def magasin() -> Magasin:
    if _magasin is None:
        raise RuntimeError("contexte non démarré")
    return _magasin


def file_travaux() -> FileTravaux | None:
    return _file
