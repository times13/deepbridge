import os

f = r"C:\Projetsss\Resultat_Test01\seg\internal_carotid_artery_right.nii"

print("Existe :", os.path.exists(f))
print("Taille :", os.path.getsize(f))

with open(f, "rb") as fp:
    print("16 premiers octets :", fp.read(16))