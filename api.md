# DeepBridge — Contrat d'API

**Version** : 0.1.0 (Phase 1 — réponses mockées)
**Base URL en dev** : `http://localhost:8000`
**Documentation interactive auto-générée** : `http://localhost:8000/docs`

Ce document est la source de vérité pour les appels entre le frontend React et le backend FastAPI. Les deux côtés s'alignent sur ce fichier. Toute modification de contrat se discute ici en premier, avant le code.

## Convention générale

- Tous les endpoints retournent du JSON (sauf le téléchargement DICOM brut et le PDF).
- Les erreurs suivent le format FastAPI standard : `{"detail": "message"}` avec un code HTTP approprié (404, 422, 500).
- Tous les pourcentages sont exprimés sur 100 (pas sur 1) sauf indication contraire.
- Toutes les probabilités (Random Forest) sont sur 1.

---

## GET /api/health

Vérifie que le backend tourne et que les modèles sont chargés.

**Réponse 200**
```json
{
  "status": "healthy",
  "models_loaded": false,
  "version": "0.1.0"
}
```

---

## GET /api/patients

Liste tous les dossiers patients disponibles. Utilisé par la page liste du frontend.

**Réponse 200**
```json
[
  {
    "id": "PATIENT_001",
    "name": "Patient 001",
    "age": 72,
    "sex": "M",
    "scan_date": "2021-01-18",
    "slice_count": 412
  },
  {
    "id": "PATIENT_002",
    "name": "Patient 002",
    "age": 68,
    "sex": "F",
    "scan_date": "2021-02-04",
    "slice_count": 389
  }
]
```

---

## GET /api/patients/{patient_id}

Détail d'un patient avec ses features cliniques (utilisées par le modèle de complication) et la liste des IDs de coupes disponibles.

**Réponse 200**
```json
{
  "id": "PATIENT_001",
  "name": "Patient 001",
  "scan_date": "2021-01-18",
  "slice_count": 412,
  "features": {
    "age": 72,
    "sex": "M",
    "s_plus": 1,
    "surgical_technique": "patch",
    "shunt": false,
    "arterio": false,
    "re_inter": false,
    "anomalie": false,
    "anomalie_comm": false
  },
  "slices": ["slice_0000", "slice_0001", "...", "slice_0411"]
}
```

**Réponse 404** si le patient n'existe pas.

---

## GET /api/patients/{patient_id}/slices/{slice_index}

Retourne les bytes bruts d'une coupe DICOM (`Content-Type: application/dicom`). Le frontend les passe à cornerstone-wado-image-loader pour affichage.

`slice_index` est un entier `0..slice_count-1`.

**Phase 1** : non implémenté, retourne 501.
**Phase 3+** : lecture depuis `data/patients/{patient_id}/slices/`.

---

## POST /api/patients/{patient_id}/analyze

Lance l'analyse complète d'un patient. Coût : quelques secondes (inférence U-Net sur N coupes + Random Forest + géométrie). Retourne le résultat agrégé.

**Body** : aucun (toutes les infos viennent du dossier patient sur le serveur).

**Réponse 200**
```json
{
  "patient_id": "PATIENT_001",
  "stenosis_left": {
    "side": "left",
    "nascet_percent": 78.0,
    "ecst_percent": 65.0,
    "min_diameter_mm": 1.4,
    "ref_diameter_mm": 6.4,
    "critical_slice_index": 178,
    "confidence": 0.91
  },
  "stenosis_right": {
    "side": "right",
    "nascet_percent": 22.0,
    "ecst_percent": 18.0,
    "min_diameter_mm": 4.8,
    "ref_diameter_mm": 6.2,
    "critical_slice_index": 192,
    "confidence": 0.88
  },
  "complication_risk": {
    "probability": 0.18,
    "confidence_interval": [0.12, 0.27],
    "top_factors": [
      {"name": "age", "contribution": 0.31},
      {"name": "shunt", "contribution": 0.18},
      {"name": "technique", "contribution": 0.14}
    ]
  },
  "recommendation": {
    "verdict": "surgery",
    "reasoning": "Sténose NASCET gauche ≥ 70%. Risque post-opératoire < 30%. Indication d'endartériectomie du côté gauche.",
    "criteria_used": [
      "NASCET ≥ 70% indique endartériectomie carotidienne",
      "ECST ≥ 50% est l'équivalent ECST du seuil NASCET 70%",
      "Risque post-opératoire acceptable < 30%"
    ]
  },
  "timestamp": "2026-05-22T14:32:18.124Z",
  "report_id": "8c3f1a9b-4e2d-4a17-9f10-7c2b8e3d5f6a"
}
```

`verdict` est l'un de : `"surgery"`, `"monitoring"`, `"contraindicated"`.

**Réponse 404** si le patient n'existe pas.

---

## GET /api/reports/{report_id}

Récupère un rapport généré précédemment, au format JSON identique à la réponse de `POST /analyze`.

**Phase 1** : non implémenté, retourne 501.

---

## GET /api/reports/{report_id}.pdf

Télécharge le rapport au format PDF (`Content-Type: application/pdf`).

**Phase 1** : non implémenté, retourne 501.

---

## Structure des dossiers patients sur le disque

Pour information du frontend (qui ne lit pas le disque, mais c'est utile à savoir) :

```
data/patients/PATIENT_001/
├── slices/
│   ├── slice_0000.dcm
│   ├── slice_0001.dcm
│   └── ...
└── metadata.json    ← features extraites du CSV clinique
```

---

## Origines CORS autorisées

Pendant le développement, le backend autorise :
- `http://localhost:5173` (Vite par défaut)
- `http://localhost:3000` (alt)
- `http://127.0.0.1:5173`

---
