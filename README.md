# Mesure NASCET automatisée sur angioscanner

Contribution au projet DeepBridge — chaîne de mesure du degré de sténose carotidienne, appliquée à 292 axes de la cohorte CHU de Nice, et application web associée.

**Times ALFRED** · Projets d'Innovation · Master 2 MIAGE MBDS · Université Côte d'Azur · 2025/2026

---

## Ce que fait cette chaîne

Un dossier DICOM entre, un pourcentage de sténose sort — ou un refus motivé.

Sur les 292 axes de la cohorte, le système s'abstient dans 40,8 % des cas. Le parti pris est de traiter ce refus comme une sortie légitime plutôt que comme un échec : dans un contexte où le lecteur ne peut pas vérifier la valeur qu'on lui présente, une mesure fausse mais plausible est plus difficile à rattraper qu'une absence de mesure.

Ce choix n'a pas été évalué en usage réel. Il repose sur un raisonnement, non sur une observation.

---

## Résultats sur la cohorte

| | |
|---|---|
| Patients | 148 (146 mesurés bilatéralement) |
| Axes carotidiens analysés | **292** |
| Examens | février 2010 – septembre 2017 |

| Verdict | n | % |
|---|---|---|
| `mesure` | 145 | 49,7 |
| `mesure_incertaine` | 27 | 9,2 |
| `pas_de_stenose` | 1 | 0,3 |
| `non_calculable` | 119 | 40,8 |

Médiane des ratios publiés : **48,6 %**. Neuf axes franchissent le seuil de 70 % après correction du biais de détection de bord.

### Le refus n'est pas aléatoire

Les axes refusés sont significativement **plus sténosés** que les mesures publiées — ratio implicite médian de 56,8 % contre 46,8 %, Mann-Whitney $p = 3 \times 10^{-7}$. Et 16,8 % des refus dépasseraient 70 %, contre 5,2 % des mesures.

Le mécanisme est géométrique : une sténose serrée laisse un lumen d'un à deux voxels, le volume partiel fait chuter le rehaussement mesuré, et le critère de rehaussement minimal se déclenche préférentiellement sur les lésions les plus graves.

> La chaîne ne sait pas mesurer les cas graves, mais elle sait les reconnaître. Les 119 refus sont donc présentés triés par sévérité présumée — une file de travail, pas un journal d'échecs.

### Deux résultats négatifs

**ECST n'est pas calculable sur angioscanner.** Son dénominateur suppose de reconstituer la paroi artérielle externe, invisible sur une acquisition injectée qui ne rehausse que la lumière. Sur les 170 axes portant une valeur, 22,9 % des couples NASCET/ECST sont incohérents et 30 % des estimations ne tiennent que par un garde-fou. Le critère est conservé en colonnes `expl_*` pour la traçabilité méthodologique, jamais exploité.

**Une interruption du masque n'est pas une sténose.** L'analyse densitométrique du segment séparant deux composantes d'un masque fragmenté montre 256 à 269 UH sur toute sa longueur — le niveau d'une lumière artérielle opacifiée. Le vaisseau est perméable ; le défaut vient du modèle de segmentation, non de l'anatomie. Traiter ces interruptions comme des sténoses aurait rapporté des occlusions sur des carotides saines.

---

## La chaîne

```
dossier DICOM
   │
   ├─ pré-vol sur en-têtes                    2 s
   │    modalité, épaisseur ≤ 1,5 mm, ≥ 100 coupes, étendue Z, contraste
   │
   ├─ conversion DICOM → NIfTI                SimpleITK, série CT la plus fournie
   │
   ├─ segmentation TotalSegmentator          ~12,5 min
   │    headneck_bones_vessels  →  carotides internes + jugulaires
   │    total --roi_subset      →  carotides communes
   │
   ├─ confirmation de la région               sur les masques, pas sur les tags
   │
   ├─ ligne centrale géodésique               Dijkstra pondéré par la
   │                                          transformée de distance
   │
   ├─ mesure FWHM                             repère transporté, reformatage
   │                                          polaire, exclusion du calcium
   │
   └─ verdict à quatre états
```

### Trois choix de conception

**La carotide commune est fusionnée à l'interne.** Sans elle, la mesure porte au-dessus du bulbe — donc au-dessus du site où siège la majorité des lésions. Cette correction fait passer la médiane de 34 % à 48,6 %, et la classe 50–70 % de 11 % à 40,7 % des ratios publiés.

**L'axe est un plus court chemin géodésique**, non un centroïde par coupe ni une squelettisation. Ces deux méthodes supposent qu'une coupe axiale ne traverse le vaisseau qu'une fois — hypothèse fausse dès qu'une carotide fait une boucle. Le chemin géodésique ignore en outre les culs-de-sac par construction, ce qui écarte le moignon de carotide externe sans traitement dédié.

**Le diamètre est mesuré sur l'image, non sur le masque.** Le masque est une décision binaire déjà prise, à la résolution du voxel. Le profil d'intensité conserve l'information de transition et permet une localisation sous-voxel du bord. Un rayon qui rencontre du calcium s'y arrête : la plaque borne le lumen au lieu d'y être incluse, car elle est *plus dense* que le produit de contraste et un seuil naïf surestimerait le lumen résiduel.

---

## Ce qui a été écarté

| Approche | Motif |
|---|---|
| U-Net `carotide_detector_v2.h5` (promotion 2024-2025) | entraîné sur des masques erronés — segmente là où il n'y a pas de carotide |
| Squelettisation scikit-image | hypothèse d'une seule traversée par coupe axiale |
| Lignes centrales VMTK | sélection de graines interactive, non automatisable sur 292 axes |
| Critère ECST | dénominateur non observable en angioscanner |

### Le U-Net

Le modèle a été repris tel quel et appliqué à la cohorte. L'inspection visuelle des masques produits, coupe par coupe, montre qu'il **segmente des régions dépourvues de carotide** : il ne se trompe pas sur les contours d'un vaisseau qu'il aurait trouvé, il désigne des structures qui n'en sont pas.

La cause tient à ses données d'entraînement. Les masques de référence avaient été produits semi-automatiquement, par une chaîne de détection en amont, et la présence des dossiers `masks/` et `corrected_masks/` dans le dépôt d'origine indique que le problème avait été perçu. Un modèle entraîné sur des annotations fausses hérite de leurs erreurs.

Le réentraînement aurait exigé une annotation manuelle de référence sur plusieurs dizaines de patients, hors de portée du calendrier et sans garantie de dépasser un modèle généraliste déjà entraîné sur un corpus bien supérieur.

---

## Structure

```
mesure-nascet/
├── pipeline/              chaîne de mesure, appelée par subprocess
│   ├── inventory_dicom.py             inventaire par en-têtes
│   ├── etape0_lot_segmentation.py     conversion + segmentation en lot
│   ├── batch_components.py            diagnostic 3D des modes d'échec
│   ├── etape2b_sections.py            diagnostic 2D (CROSSE / BRANCHE / ILOT)
│   ├── etape2c_centerline_geodesique.py
│   ├── etape2d_fwhm.py                mesure, NASCET, verdicts
│   ├── etape3_decision.py             jointure clinique
│   └── exploration/                   scripts d'investigation conservés
│
├── backend/               FastAPI, 12 routes
│   └── app/
│       ├── validation.py              pré-vol et contrôle post-segmentation
│       ├── api/                       axes · travaux · corrections
│       └── services/                  mesures · travaux · magasin
│
├── frontend/              React 18 + TypeScript + Vite + Tailwind
│   └── src/pages/         DepotPatient · FichePatient
│
└── docs/                  mémoire
```

Le backend **appelle** le pipeline, il ne le réimplémente pas : deux versions du même calcul divergeraient, et c'est celle de l'étude qui fait foi.

---

## Lancer

```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install fastapi uvicorn pandas python-multipart pydicom nibabel numpy pydantic-settings
uvicorn app.main:app --reload

# frontend
cd frontend && npm install && npm run dev
```

Configuration dans `backend/.env` — voir `.env.exemple`. Le pipeline conserve son propre interpréteur Python (`python_pipeline`) : TotalSegmentator traîne PyTorch et plusieurs gigaoctets, le backend reste léger.

Au démarrage, le service doit afficher :

```
[DeepBridge] etude    : 292 axes, 146 patients, 119 refus, mediane 48.6 %  (lecture seule)
[DeepBridge] clinique : 0 axes, 0 patients
```

### L'application

**Nouveau patient** — le serveur énumère les dossiers DICOM sous les racines déclarées, le radiologue en choisit un. Le pré-vol donne la recevabilité en deux secondes ; le bouton de lancement est désactivé sur un refus.

**Cohorte d'étude** — les 292 axes, filtrables par verdict. Aucune vocation clinique : ces patients ont été opérés entre 2010 et 2017.

**Fiche patient** — verdict, valeur bornée, pièces à conviction, figures. Aucun pourcentage n'y est affiché nu.

---

## Deux magasins, jamais confondus

| | Cohorte d'étude | Dossiers cliniques |
|---|---|---|
| Fichier | `data/reference/nascet.csv` | `data/dossiers/<PatientID>/nascet.csv` |
| Écriture | **jamais** | par l'application |
| Effectif | figé à 292 | croissant |
| Issue à J30 | connue | inconnue |

Les chiffres du mémoire ne sont vérifiables que si le fichier de référence ne bouge plus. Mélanger les deux les rendrait irreproductibles dès le premier patient analysé par l'application. L'empreinte SHA-256 de la référence est publiée dans `data/reference/CHECKSUMS.txt`.

---

## Limites

**Le taux de refus n'est pas neutre.** Établi et quantifié plus haut : le mécanisme qui protège de l'erreur écarte préférentiellement les patients qu'il fallait détecter. La distribution des ratios publiés est donc biaisée vers le bas.

**Le seuil `voxels_carotide_min` est estimé**, non calibré sur la cohorte. À ajuster depuis `composantes.csv` avant tout usage réel.

**L'étalonnage du biais δ n'est pas reproductible.** La constante `DELTA_FWHM_MM = 0.19` provient de fantômes dont le script générateur n'a pas été conservé. C'est précisément pourquoi la correction n'est appliquée qu'en colonnes exploratoires : ce biais dépend de la fonction d'étalement du point et du rehaussement propres à chaque acquisition, et ne doit pas se substituer à la mesure.

**Pas de mesure manuelle assistée.** Sur un axe non mesurable, la fiche affiche la cause et la coupe à inspecter, mais aucun outil de mesure — le viewer Cornerstone est en place dans le dépôt mais non branché.

---

## Données

Cohorte CHU de Nice. **Non incluse dans ce dépôt** — données médicales. Accès : M. Gregory Galli, Université Côte d'Azur.

Les examens (`StudyDate`) s'étendent de février 2010 à septembre 2017.

```
data/
├── reference/    nascet.csv · cles.csv · base_clinique.xlsx · CHECKSUMS.txt
├── dossiers/     patients analysés par l'application
├── mesures_all/  figures produites par etape2c et etape2d
└── Resultats/    ct.nii.gz et masques — dossier de travail, non archive
```