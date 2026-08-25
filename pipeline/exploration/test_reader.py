from vmtk import vmtkscripts

reader = vmtkscripts.vmtkImageReader()

# <-- remplace par ton fichier
reader.InputFileName = r"C:\Projetsss\Resultat_Test01\seg\internal_carotid_artery_right.nii.gz"

reader.Execute()

image = reader.Image

print("=" * 60)
print(type(image))
print("=" * 60)

print("Dimensions :", image.GetDimensions())
print("Spacing    :", image.GetSpacing())
print("Origin     :", image.GetOrigin())
print("ScalarRange:", image.GetScalarRange())