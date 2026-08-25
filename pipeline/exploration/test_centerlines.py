from vmtk import vmtkscripts

# Lecture
reader = vmtkscripts.vmtkImageReader()
reader.InputFileName = r"C:\Projetsss\Resultat_Test01\seg\internal_carotid_artery_right.nii"
reader.Execute()

# Surface
marching = vmtkscripts.vmtkMarchingCubes()
marching.Image = reader.Image
marching.Level = 0.5
marching.Execute()

# Seed selector
selector = vmtkscripts.vmtkCarotidProfilesSeedSelector()
selector.SetSurface(marching.Surface)

print("Avant Execute")

selector.Execute()

print("Après Execute")

print("Source :", selector.GetSourceSeedIds())
print("Target :", selector.GetTargetSeedIds())