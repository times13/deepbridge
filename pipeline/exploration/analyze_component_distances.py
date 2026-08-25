import nibabel as nib
import numpy as np
from scipy.ndimage import label
from scipy.spatial import cKDTree

# ==========================
# PARAMÈTRES
# ==========================

mask_path = r"C:\Projetsss\Patient03_Test\seg\internal_carotid_artery_right.nii.gz"

# ==========================
# LECTURE DU MASQUE
# ==========================

nii = nib.load(mask_path)
mask = nii.get_fdata() > 0

# taille des voxels (mm)
spacing = nii.header.get_zooms()[:3]

# ==========================
# COMPOSANTES CONNEXES
# ==========================

labels, n_components = label(mask)

print(f"\nNombre de composantes : {n_components}")

# coordonnées physiques de chaque composante
components = {}

for i in range(1, n_components + 1):

    coords = np.argwhere(labels == i)

    # conversion voxel -> mm
    coords_mm = coords.astype(float)
    coords_mm[:, 0] *= spacing[0]
    coords_mm[:, 1] *= spacing[1]
    coords_mm[:, 2] *= spacing[2]

    components[i] = coords_mm

# ==========================
# MATRICE DES DISTANCES
# ==========================

distance_matrix = np.zeros((n_components, n_components))

print("\nDistances minimales entre composantes\n")

for i in range(1, n_components + 1):

    tree = cKDTree(components[i])

    for j in range(i + 1, n_components + 1):

        distances, _ = tree.query(components[j], k=1)

        dmin = distances.min()

        distance_matrix[i - 1, j - 1] = dmin
        distance_matrix[j - 1, i - 1] = dmin

        print(f"C{i} <-> C{j} : {dmin:.2f} mm")

# ==========================
# MATRICE
# ==========================

print("\n==============================")
print("Matrice des distances (mm)")
print("==============================\n")

header = "      "

for i in range(1, n_components + 1):
    header += f"C{i:>8}"

print(header)

for i in range(n_components):

    line = f"C{i+1:<3} "

    for j in range(n_components):

        if i == j:
            line += f"{'-':>8}"
        else:
            line += f"{distance_matrix[i,j]:8.2f}"

    print(line)