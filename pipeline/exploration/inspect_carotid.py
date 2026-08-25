import os
import numpy as np
import nibabel as nib
import matplotlib.pyplot as plt

# ===========================================================
# CHEMINS
# ===========================================================

ct_file = r"C:\Projetsss\Resultat_Test01\ct.nii.gz"

ica_file = r"C:\Projetsss\Resultat_Test01\seg\internal_carotid_artery_right.nii\internal_carotid_artery_right.nii"

cca_file = r"C:\Projetsss\Resultat_Test01\seg_total\common_carotid_artery_right.nii\common_carotid_artery_right.nii"

out_dir = r"C:\Projetsss\Resultat_Test01\compare_CCA_ICA"

# ===========================================================

os.makedirs(out_dir, exist_ok=True)

print("Chargement...")

ct = nib.load(ct_file).get_fdata()

ica = nib.load(ica_file).get_fdata() > 0

cca = nib.load(cca_file).get_fdata() > 0

print("CT :", ct.shape)
print("ICA :", ica.shape)
print("CCA :", cca.shape)

HALF = 45

# uniquement la zone intéressante
for z in range(545, 571):

    # coordonnées des deux masques réunis
    both = np.logical_or(ica[:, :, z], cca[:, :, z])

    if np.any(both):

        xs, ys = np.where(both)

        cx = int(xs.mean())
        cy = int(ys.mean())

    else:
        # si aucun masque, on garde le dernier centre connu
        if z == 545:
            cx = ct.shape[0] // 2
            cy = ct.shape[1] // 2

    x0 = max(0, cx - HALF)
    x1 = min(ct.shape[0], cx + HALF)

    y0 = max(0, cy - HALF)
    y1 = min(ct.shape[1], cy + HALF)

    img = np.clip(
        ct[x0:x1, y0:y1, z],
        -100,
        400
    )

    fig, ax = plt.subplots(figsize=(5,5))

    ax.imshow(
        img.T,
        cmap="gray",
        origin="lower"
    )

    # Carotide commune (rouge)
    if np.any(cca[:, :, z]):
        ax.contour(
            cca[x0:x1, y0:y1, z].T,
            levels=[0.5],
            colors="red",
            linewidths=2,
        )

    # Carotide interne (vert)
    if np.any(ica[:, :, z]):
        ax.contour(
            ica[x0:x1, y0:y1, z].T,
            levels=[0.5],
            colors="lime",
            linewidths=2,
        )

    ax.set_title(f"z={z}")

    ax.axis("off")

    plt.tight_layout()

    plt.savefig(
        os.path.join(
            out_dir,
            f"compare_{z:04d}.png"
        ),
        dpi=180
    )

    plt.close()

print("\nTerminé !")
print(out_dir)