# Backend — API de mesure

FastAPI. Expose les mesures produites par `../pipeline/`, gère la file d'analyse et la saisie des corrections. Il **appelle** le pipeline par `subprocess`, il ne le réimplémente pas.

## Lancer

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install fastapi uvicorn pandas python-multipart pydicom nibabel numpy pydantic-settings
uvicorn app.main:app --reload
```

Configuration : `.env`, voir `.env.exemple`. Documentation interactive sur
`http://localhost:8000/docs`.

## Routes

| Groupe | Routes |
|---|---|
| `mesures` | synthese · axes · file-prioritaire · patients/{id} · artefacts |
| `analyse` | dossiers-disponibles · dossiers/prevol · travaux (GET, POST, local) · travaux/{id} · annuler |
| `corrections` | corrections (GET, POST) · corrections/accord |

## Modules

| Fichier | Rôle |
|---|---|
| `validation.py` | pré-vol sur en-têtes, contrôle post-segmentation |
| `services/mesures.py` | lecture des deux magasins, sérialisation des axes |
| `services/travaux.py` | file SQLite, worker, appels au pipeline |
| `services/magasin.py` | index des mesures, table des corrections |
| `services/dicom_loader.py` | validation d'upload, métadonnées patient, lecture HU |

## Deux points de configuration

`python_pipeline` désigne l'interpréteur qui exécute le pipeline :
TotalSegmentator traîne PyTorch et plusieurs gigaoctets, le venv du backend
reste léger.

`racines_dicom` borne les dossiers que le client peut désigner. Un chemin
hors de ces racines est refusé.