import os
import nibabel as nib
import numpy as np
from scipy.ndimage import label
from scipy.spatial import cKDTree

# =====================================================
# PARAMÈTRES
# =====================================================

mask_path = r"C:\Projetsss\Patient03_Test\seg\internal_carotid_artery_right.nii.gz"
cta_path = r"C:\Projetsss\Patient03_Test\ct.nii.gz"

component_A = 3
component_B = 4

roi_size = 32      # taille du cube (voxels)

# =====================================================
# LECTURE
# =====================================================

mask_nii = nib.load(mask_path)
mask = mask_nii.get_fdata() > 0

cta_nii = nib.load(cta_path)
cta = cta_nii.get_fdata()

spacing = mask_nii.header.get_zooms()[:3]

labels, n = label(mask)

print(f"\nNombre de composantes : {n}")

# =====================================================
# EXTRACTION DES VOXELS
# =====================================================

coordsA = np.argwhere(labels == component_A)
coordsB = np.argwhere(labels == component_B)

if len(coordsA) == 0:
    raise Exception("Composante A introuvable")

if len(coordsB) == 0:
    raise Exception("Composante B introuvable")

# =====================================================
# KDTree
# =====================================================

coordsA_mm = coordsA.astype(float)
coordsA_mm[:,0] *= spacing[0]
coordsA_mm[:,1] *= spacing[1]
coordsA_mm[:,2] *= spacing[2]

coordsB_mm = coordsB.astype(float)
coordsB_mm[:,0] *= spacing[0]
coordsB_mm[:,1] *= spacing[1]
coordsB_mm[:,2] *= spacing[2]

tree = cKDTree(coordsA_mm)

distances, indices = tree.query(coordsB_mm, k=1)

idxB = np.argmin(distances)
idxA = indices[idxB]

pointA = coordsA[idxA]
pointB = coordsB[idxB]

distance_mm = distances[idxB]

print("\n================================")
print("POINTS LES PLUS PROCHES")
print("================================")

print("Composante", component_A, ":", pointA)
print("Composante", component_B, ":", pointB)

print(f"Distance : {distance_mm:.2f} mm")

# =====================================================
# CENTRE ROI
# =====================================================

center = ((pointA + pointB) / 2).astype(int)

print("\nCentre ROI :", center)

half = roi_size // 2

xmin = max(center[0]-half,0)
xmax = min(center[0]+half,cta.shape[0])

ymin = max(center[1]-half,0)
ymax = min(center[1]+half,cta.shape[1])

zmin = max(center[2]-half,0)
zmax = min(center[2]+half,cta.shape[2])

roi = cta[
    xmin:xmax,
    ymin:ymax,
    zmin:zmax
]

print("\nROI :", roi.shape)

# =====================================================
# SAUVEGARDE
# =====================================================

roi_affine = cta_nii.affine

roi_img = nib.Nifti1Image(roi, roi_affine)

output = f"ROI_C{component_A}_C{component_B}.nii.gz"

nib.save(roi_img, output)

print("\nROI sauvegardée :")
print(output)