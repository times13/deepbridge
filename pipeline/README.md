# pipeline/

Chaine de mesure validee sur 292 axes. Le backend l'appelle par subprocess.

## Production — dans l'ordre

| Script | Role |
|---|---|
| inventory_dicom.py | inventaire par en-tetes, criteres d'exploitabilite |
| etape0_lot_segmentation.py | DICOM -> ct.nii.gz -> TotalSegmentator (2 taches) |
| batch_components.py | diagnostic 3D : fragmentation, fuites, jugulaire |
| etape2b_sections.py | diagnostic 2D : CROSSE / BRANCHE / ILOT |
| etape2c_centerline_geodesique.py | axe geodesique + diametre inscrit |
| etape2d_fwhm.py | reformatage polaire, FWHM, NASCET, 4 verdicts |
| etape3_decision.py | jointure clinique, regle de decision |

## exploration/

Scripts d'investigation. Conserves comme trace des hypotheses testees :
ils documentent le chapitre 8 du memoire. Ne pas appeler depuis le backend.
