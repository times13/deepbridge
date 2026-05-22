# DeepBridge — Contrat d'API

**Base URL en dev** : `http://localhost:8000`
**Documentation interactive auto-générée** : `http://localhost:8000/docs`

Architecture : **upload-based**. Le médecin uploade les fichiers DICOM d'un patient depuis le navigateur, le backend traite la requête et retourne le rapport. Pas de stockage serveur, pas de liste de patients persistante — chaque analyse est éphémère.

## Convention générale

- Tous les endpoints retournent du JSON (sauf le PDF de rapport).
- Les erreurs suivent le format FastAPI standard : `{"detail": "message"}` avec un code HTTP approprié.
- Tous les pourcentages sont sur 100 sauf indication contraire.
- Toutes les probabilités (Random Forest) sont sur 1.

---

## GET /api/health

Vérifie que le backend tourne et que les modèles sont chargés.

**Réponse 200**
```json
{
  "status": "healthy",
  "models_loaded": false
}
```

---

## POST /api/analyze

**Le seul endpoint d'analyse.** Le frontend envoie en multipart les fichiers DICOM du patient à analyser, le backend extrait les métadonnées, fait l'inférence, et retourne le rapport complet.

**Request** : `multipart/form-data`
- `files` (répété) : un ou plusieurs fichiers DICOM (toutes les coupes d'un même patient)

**Exemple côté frontend (axios)** :
```js
const formData = new FormData();
selectedFiles.forEach(f => formData.append('files', f));
const res = await axios.post('http://localhost:8000/api/analyze', formData);
```

**Exemple côté frontend (fetch)** :
```js
const formData = new FormData();
selectedFiles.forEach(f => formData.append('files', f));
const res = await fetch('http://localhost:8000/api/analyze', {
  method: 'POST',
  body: formData,
});
const result = await res.json();
```

**Réponse 200** — `AnalysisResult` :
```json
{
  "patient_id": "1.2.840.113619.2.5.1762583153.0",
  "stenosis_left": {
    "side": "left",
    "nascet_percent": 78.0,
    "ecst_percent": 65.0,
    "min_diameter_mm": 1.41,
    "ref_diameter_mm": 6.4,
    "critical_slice_index": 178,
    "confidence": 0.91
  },
  "stenosis_right": {
    "side": "right",
    "nascet_percent": 22.0,
    "ecst_percent": 18.0,
    "min_diameter_mm": 4.84,
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
      {"name": "surgical_technique", "contribution": 0.14}
    ]
  },
  "recommendation": {
    "verdict": "surgery",
    "reasoning": "Sténose NASCET ≥ 70% (seuil chirurgical des essais NASCET, 1991). Risque post-opératoire prédit inférieur à 30%. Indication d'endartériectomie carotidienne.",
    "criteria_used": [
      "NASCET ≥ 70% : indication d'endartériectomie (NASCET trial, NEJM 1991)",
      "ECST ≥ 50% : équivalent ECST du seuil NASCET 70% (ECST trial, Lancet 1998)",
      "Risque post-opératoire acceptable < 30% (ESVS Guidelines 2023)"
    ]
  },
  "timestamp": "2026-05-22T14:32:18.124Z",
  "report_id": "8c3f1a9b-4e2d-4a17-9f10-7c2b8e3d5f6a"
}
```

`patient_id` est extrait du tag DICOM `PatientID`. Si absent, un identifiant aléatoire `upload_xxxxxxxx` est généré.

`verdict` est l'un de : `"surgery"`, `"monitoring"`, `"contraindicated"`.

**Réponse 400** :
- `"Aucun fichier reçu."` — aucun fichier dans le multipart
- `"Aucun fichier DICOM valide dans l'upload (N fichier(s) rejeté(s)...)"` — les fichiers reçus ne sont pas des DICOM (validation par marqueur magique `DICM` à l'offset 128)

---

## GET /api/reports/{report_id}

Récupère un rapport généré précédemment, au format JSON identique à la réponse de `POST /analyze`.

**Phase 1-2** : non implémenté, retourne 501.
**Phase 7** : récupération depuis SQLite.

---

## GET /api/reports/{report_id}.pdf

Télécharge le rapport au format PDF (`Content-Type: application/pdf`).

**Phase 1-2** : non implémenté, retourne 501.

---

## Origines CORS autorisées

Pendant le développement, le backend autorise :
- `http://localhost:5173` (Vite par défaut)
- `http://localhost:3000` (alt)
- `http://127.0.0.1:5173`
- `http://127.0.0.1:3000`


---

## Phase 2 — état actuel

L'endpoint `POST /api/analyze` :
- ✓ Valide chaque fichier uploadé (marqueur DICM)
- ✓ Trie les coupes par `InstanceNumber`
- ✓ Extrait les métadonnées du premier DICOM (âge, sexe, date d'examen, modalité)
- ⏳ Phase 3 : passera les coupes au U-Net Keras pour segmentation
- ⏳ Phase 4 : géométrie NASCET / ECST par squelettisation
- ⏳ Phase 5 : Random Forest sur les features cliniques pour prédiction de complications
- ⏳ Phase 6 : moteur de recommandation combinant les deux

En attendant les Phases 3-6, la réponse est mockée mais dérivée des métadonnées extraites (les patients âgés obtiennent une recommandation différente des patients jeunes, etc.) — Claude A peut développer toute l'UI contre une réponse réaliste.

---

