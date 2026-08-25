import os
import nibabel as nib
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import label
from scipy.spatial import cKDTree

# ==========================================================
# PARAMÈTRES
# ==========================================================

mask_path = r"C:\Projetsss\Patient03_Test\seg\internal_carotid_artery_right.nii.gz"
cta_path = r"C:\Projetsss\Patient03_Test\ct.nii.gz"

component_A = 3
component_B = 4

roi_size = 32

output_dir = f"Gap_C{component_A}_C{component_B}"
os.makedirs(output_dir, exist_ok=True)

# ==========================================================
# LECTURE
# ==========================================================

cta_nii = nib.load(cta_path)
cta = cta_nii.get_fdata()

mask_nii = nib.load(mask_path)
mask = mask_nii.get_fdata() > 0

spacing = mask_nii.header.get_zooms()[:3]

labels, n = label(mask)

print(f"\nNombre de composantes : {n}")

# ==========================================================
# VOXELS DES COMPOSANTES
# ==========================================================

coordsA = np.argwhere(labels == component_A)
coordsB = np.argwhere(labels == component_B)

coordsA_mm = coordsA.astype(float)
coordsA_mm *= spacing

coordsB_mm = coordsB.astype(float)
coordsB_mm *= spacing

tree = cKDTree(coordsA_mm)

distances, indices = tree.query(coordsB_mm, k=1)

idxB = np.argmin(distances)
idxA = indices[idxB]

pointA = coordsA[idxA]
pointB = coordsB[idxB]

distance_mm = distances[idxB]

print("\n===================================")
print("POINTS LES PLUS PROCHES")
print("===================================")

print("Point A :", pointA)
print("Point B :", pointB)
print(f"Distance : {distance_mm:.2f} mm")

# ==========================================================
# ROI
# ==========================================================

center = ((pointA + pointB) / 2).astype(int)

half = roi_size // 2

xmin = max(center[0] - half, 0)
xmax = min(center[0] + half, cta.shape[0])

ymin = max(center[1] - half, 0)
ymax = min(center[1] + half, cta.shape[1])

zmin = max(center[2] - half, 0)
zmax = min(center[2] + half, cta.shape[2])

roi_cta = cta[xmin:xmax, ymin:ymax, zmin:zmax]
roi_mask = mask[xmin:xmax, ymin:ymax, zmin:zmax]

# ==========================================================
# SAUVEGARDE NIFTI
# ==========================================================

nib.save(
    nib.Nifti1Image(roi_cta, cta_nii.affine),
    os.path.join(output_dir, "roi_cta.nii.gz"),
)

nib.save(
    nib.Nifti1Image(roi_mask.astype(np.uint8), mask_nii.affine),
    os.path.join(output_dir, "roi_mask.nii.gz"),
)

# ==========================================================
# CENTRE DES COUPES
# ==========================================================

cx = roi_cta.shape[0] // 2
cy = roi_cta.shape[1] // 2
cz = roi_cta.shape[2] // 2

# ==========================================================
# FONCTION AFFICHAGE
# ==========================================================

def save_slice(image, mask, filename):

    plt.figure(figsize=(6,6))

    plt.imshow(image, cmap="gray")

    overlay = np.ma.masked_where(mask == 0, mask)

    plt.imshow(overlay, cmap="autumn", alpha=0.6)

    plt.axis("off")

    plt.tight_layout()

    plt.savefig(filename, dpi=200)

    plt.close()

# ==========================================================
# AXIAL
# ==========================================================

save_slice(
    roi_cta[:, :, cz],
    roi_mask[:, :, cz],
    os.path.join(output_dir, "axial.png")
)

# ==========================================================
# CORONAL
# ==========================================================

save_slice(
    roi_cta[:, cy, :],
    roi_mask[:, cy, :],
    os.path.join(output_dir, "coronal.png")
)

# ==========================================================
# SAGITTAL
# ==========================================================

save_slice(
    roi_cta[cx, :, :],
    roi_mask[cx, :, :],
    os.path.join(output_dir, "sagittal.png")
)

# ==========================================================
# RAPPORT
# ==========================================================

with open(os.path.join(output_dir, "report.txt"), "w") as f:

    f.write(f"Composante A : {component_A}\n")
    f.write(f"Composante B : {component_B}\n")
    f.write(f"Distance minimale : {distance_mm:.2f} mm\n")
    f.write(f"Point A : {pointA.tolist()}\n")
    f.write(f"Point B : {pointB.tolist()}\n")
    f.write(f"Centre ROI : {center.tolist()}\n")

print("\n===================================")
print("Analyse terminée")
print("===================================")

print(f"Dossier créé : {output_dir}")