import SimpleITK as sitk

f = r"C:\Projetsss\Resultat_Test01\seg\internal_carotid_artery_right.nii"

img = sitk.ReadImage(f)

print(img.GetSize())
print(img.GetSpacing())
print(img.GetPixelIDTypeAsString())