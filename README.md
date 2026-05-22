# DeepBridge — Aide à la décision pour la sténose carotidienne

Projet d'innovation — Master 2 MIAGE MBDS  
Université Côte d'Azur — 2025/2026

---

## Présentation

DeepBridge est une application web d'aide à la décision chirurgicale pour les patients atteints de sténose carotidienne.  
Le médecin uploade les images scanner (DICOM) d'un patient, et l'application analyse automatiquement les images pour fournir :

- Le pourcentage de sténose des deux carotides (critères NASCET et ECST)
- Une estimation du risque de complication post-opératoire
- Une recommandation argumentée : opérer ou surveiller

Ce projet s'appuie sur les travaux des promotions précédentes (2020–2025) et apporte quatre contributions nouvelles :
1. Une application **web** (aucune promotion précédente n'en avait livré une)
2. Le calcul réel des critères **NASCET et ECST** par géométrie vasculaire
3. L'**intégration** du pipeline image (U-Net) et du pipeline clinique (Random Forest) en une recommandation unique
4. Un **rapport bilatéral** comparant les deux carotides

---

## Stack technique

| Couche | Technologie |
|--------|------------|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| Viewer DICOM | Cornerstone.js |
| Backend | Python 3.11 + FastAPI |
| Modèle image | U-Net Keras (`.h5`) — détection de sténose |
| Modèle clinique | Random Forest ONNX — risque de complication |
| Géométrie vasculaire | scikit-image (squelettisation + mesure de diamètres) |
| Rapport | ReportLab (PDF) |
| Conteneurisation | Docker + Docker Compose |

---

## Structure du projet
deepbridge/
│
├── docker-compose.yml
├── api.md
├── README.md
├── .gitignore
│
├── frontend/
│   │
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   │
│   └── src/
│       │
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       │
│       ├── pages/
│       │   └── PatientAnalysis.tsx
│       │
│       ├── components/
│       │   └── DicomViewer.tsx
│       │
│       ├── services/
│       │   └── api.ts
│       │
│       └── types/
│           └── analysis.ts
│
├── backend/
│   │
│   ├── Dockerfile
│   ├── pyproject.toml
│   │
│   └── app/
│       │
│       ├── main.py
│       ├── config.py
│       │
│       ├── api/
│       │   ├── patients.py
│       │   ├── analysis.py
│       │   └── reports.py
│       │
│       ├── services/
│       │   ├── dicom_loader.py
│       │   ├── unet_inference.py
│       │   ├── stenosis_geometry.py
│       │   ├── rf_inference.py
│       │   ├── recommendation.py
│       │   └── pdf_report.py
│       │
│       ├── schemas/
│       │   ├── patient.py
│       │   └── analysis.py
│       │
│       └── models/
│           ├── carotide_detector_v2.h5
│           └── random_forest.onnx
│
└── data/
    │
    └── patients/
        │
        └── PATIENT_001/
            │
            ├── slices/
            │   ├── image001.dcm
            │   ├── image002.dcm
            │   └── ...
            │
            └── metadata.json
---

## Lancement rapide

### Prérequis

- Node.js 20+
- Python 3.11+
- Docker Desktop (optionnel, pour la stack complète)

### Frontend seul (développement)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### Backend seul (développement)

```bash
cd backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000
# → http://localhost:8000/docs  (documentation interactive)
```

### Stack complète (Docker)

```bash
docker-compose up --build
# Frontend → http://localhost:5173
# Backend  → http://localhost:8000
```

---

## Dataset

Le dataset provient du CHU de Nice (2020–2021).  
Il contient des scanners de patients atteints de sténose carotidienne au format DICOM, accompagnés de métadonnées cliniques (âge, sexe, technique chirurgicale, complications).

Le dataset n'est **pas inclus** dans ce dépôt (données médicales sensibles).  
Pour y accéder, contacter M. Gregory Galli — Université Côte d'Azur.

Structure attendue sur le disque :
data/patients/PATIENT_XXX/slices/*.dcm
data/patients/PATIENT_XXX/metadata.json

---

## Phases de développement

| Phase | Description | Statut |
|-------|-------------|--------|
| 1 | Frontend React + viewer DICOM + endpoints mockés | ✅ En cours |
| 2 | Backend FastAPI — squelette + endpoints mockés | 🔲 À faire |
| 3 | Lecture DICOM côté backend (pydicom) | 🔲 À faire |
| 4 | Pipeline U-Net — segmentation carotides | 🔲 À faire |
| 5 | Géométrie NASCET/ECST | 🔲 À faire |
| 6 | Random Forest — risque de complication | 🔲 À faire |
| 7 | Rapport PDF | 🔲 À faire |
| 8 | Dockerisation complète | 🔲 À faire |

---

## Travaux antérieurs

Ce projet s'inscrit dans une continuité de recherche depuis 2020 :

| Année | Contribution principale |
|-------|------------------------|
| 2020–2021 | Première version — visualiseur DICOM de base |
| 2021–2022 | Explorations diverses |
| 2022–2023 | Reconstruction 3D, approche volumétrique |
| 2023–2024 | Transformation de plans, problèmes d'aliasing |
| 2024–2025 | Accélération GPU (CUDA/ILGPU), U-Net Keras, Random Forest ONNX |

---

## Équipe
Étudiants:
Times ALFRED
Jeudy Ralph Stevens
Caleb Toussaint
Pierre Daewens

Projet réalisé dans le cadre du cours **Projets d'Innovation**  
Master 2 MIAGE MBDS — Université Côte d'Azur — 2025/2026