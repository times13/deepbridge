import nibabel as nib
import numpy as np
from scipy.ndimage import label, map_coordinates
from scipy.spatial import cKDTree
import matplotlib.pyplot as plt

# ==========================================================
# PARAMÈTRES
# ==========================================================

mask_path = r"C:\Projetsss\Patient03_Test\seg\internal_carotid_artery_right.nii.gz"
cta_path = r"C:\Projetsss\Patient03_Test\ct.nii.gz"

component_A = 3
component_B = 4

nb_samples = 50

# ==========================================================
# LECTURE
# ==========================================================

cta_nii = nib.load(cta_path)
cta = cta_nii.get_fdata()

mask = nib.load(mask_path).get_fdata() > 0

spacing = np.array(cta_nii.header.get_zooms()[:3])

labels, n = label(mask)

# ==========================================================
# VOXELS DES COMPOSANTES
# ==========================================================

coordsA = np.argwhere(labels == component_A)
coordsB = np.argwhere(labels == component_B)

coordsA_mm = coordsA * spacing
coordsB_mm = coordsB * spacing

tree = cKDTree(coordsA_mm)

distances, indices = tree.query(coordsB_mm, k=1)

idxB = np.argmin(distances)
idxA = indices[idxB]

pointA = coordsA[idxA]
pointB = coordsB[idxB]

print("\n=================================")
print("POINTS LES PLUS PROCHES")
print("=================================")

print("Point A :", pointA)
print("Point B :", pointB)
print("Distance :", distances[idxB], "mm")

# ==========================================================
# ECHANTILLONNAGE
# ==========================================================

x = np.linspace(pointA[0], pointB[0], nb_samples)
y = np.linspace(pointA[1], pointB[1], nb_samples)
z = np.linspace(pointA[2], pointB[2], nb_samples)

profile = map_coordinates(
    cta,
    [x, y, z],
    order=1,
    mode="nearest"
)

# ==========================================================
# STATISTIQUES
# ==========================================================

print("\n========== PROFIL HU ==========")

print("HU min    :", profile.min())
print("HU max    :", profile.max())
print("HU moyen  :", profile.mean())
print("HU médian :", np.median(profile))
print("HU std    :", profile.std())

print("\nValeurs HU :")

for i, hu in enumerate(profile):
    print(f"{i+1:02d} : {hu:.1f}")

# ==========================================================
# GRAPHIQUE
# ==========================================================

plt.figure(figsize=(8,4))

plt.plot(profile, linewidth=2)

plt.xlabel("Position sur le segment")

plt.ylabel("HU")

plt.title(f"Profil HU : C{component_A} -> C{component_B}")

plt.grid(True)

plt.tight_layout()

plt.savefig("HU_profile_C3_C4.png", dpi=200)

plt.show()