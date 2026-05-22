# DeepBridge — Backend

API FastAPI pour l'analyse d'images DICOM (sténose carotidienne) et la prédiction de complications post-opératoires.

## Démarrage rapide

### Avec un venv local

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -e .[ml]
uvicorn app.main:app --reload
```

L'API démarre sur `http://localhost:8000`.

### Documentation interactive

- Swagger UI : http://localhost:8000/docs
- ReDoc : http://localhost:8000/redoc

### Avec Docker

```bash
docker build -t deepbridge-backend .
docker run -p 8000:8000 -v $(pwd)/../data:/app/data deepbridge-backend
```

## État actuel (Phase 1)

Tous les endpoints d'analyse et de listing patients retournent des **données mockées**. Le frontend peut développer toute son UI sans attendre les vrais modèles.

Endpoints fonctionnels : `GET /api/health`, `GET /api/patients`, `GET /api/patients/{id}`, `POST /api/patients/{id}/analyze`.

Endpoints retournant 501 (à implémenter dans les phases suivantes) :
- `GET /api/patients/{id}/slices/{n}` (Phase 3 — lecture DICOM disque)
- `GET /api/reports/{id}` (Phase 7)
- `GET /api/reports/{id}.pdf` (Phase 7)

## Roadmap

1. **Phase 1** ✓ Squelette + mocks
2. **Phase 2** Lecture DICOM réelle depuis `data/patients/{id}/slices/`
3. **Phase 3** Inférence U-Net pour la segmentation des carotides
4. **Phase 4** Calcul NASCET/ECST par squelettisation + balayage perpendiculaire
5. **Phase 5** Inférence Random Forest (ONNX) sur les features patient
6. **Phase 6** Moteur de recommandation combinant les deux
7. **Phase 7** Génération PDF du rapport

## Modèles à récupérer

Avant la Phase 3, télécharger les modèles pré-entraînés et les placer dans `app/models/` :

- `carotide_detector_v2.h5` — U-Net Keras, depuis [Groupe 3](https://github.com/MBDS-ANTENNES-24-25/projets-d-innovation-deepbridge-groupe1-tpi/blob/main/StenoseDetection_U-Net/carotide_detector_v2.h5)
- `random_forest.onnx` — Random Forest sklearn exporté ONNX, depuis [Groupe 4](https://github.com/MBDS-ANTENNES-24-25/projets-d-innovation-deepbridge-groupe2-tpi/blob/main/projets-d-innovation-24-25-avotra-saotra-serge-tafita-zoulfikar/random_forest_model.onnx)

## Contrat d'API

Voir `../api.md` à la racine du dépôt — c'est le contrat partagé avec le frontend.
