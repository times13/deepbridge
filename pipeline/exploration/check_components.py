import nibabel as nib
import numpy as np
from scipy.ndimage import label

mask_path = r"C:\Projetsss\Patient03_Test\seg\internal_carotid_artery_left.nii.gz"

img = nib.load(mask_path)
mask = img.get_fdata() > 0

labeled, num = label(mask)

print(f"\nNombre de composantes : {num}\n")

for i in range(1, num + 1):
    coords = np.argwhere(labeled == i)
    size = len(coords)

    xmin, ymin, zmin = coords.min(axis=0)
    xmax, ymax, zmax = coords.max(axis=0)

    print(f"Composante {i}")
    print(f"  Taille : {size} voxels")
    print(f"  X : {xmin} -> {xmax}")
    print(f"  Y : {ymin} -> {ymax}")
    print(f"  Z : {zmin} -> {zmax}")
    print()