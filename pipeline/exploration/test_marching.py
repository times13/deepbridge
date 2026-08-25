from vmtk import vmtkscripts

# ------------------------------------------------------------------
# Lecture du masque
# ------------------------------------------------------------------

reader = vmtkscripts.vmtkImageReader()
reader.InputFileName = r"C:\Projetsss\Resultat_Test01\seg\internal_carotid_artery_right.nii"

reader.Execute()

# ------------------------------------------------------------------
# Marching Cubes
# ------------------------------------------------------------------

marching = vmtkscripts.vmtkMarchingCubes()

marching.Image = reader.Image

# Masque binaire (0/1)
marching.Level = 0.5

marching.Execute()

surface = marching.Surface

# ------------------------------------------------------------------
# Informations
# ------------------------------------------------------------------

print("="*60)
print(type(surface))
print("="*60)

print("Points    :", surface.GetNumberOfPoints())
print("Polygones :", surface.GetNumberOfPolys())
print("Cellules  :", surface.GetNumberOfCells())

print("\nBounds")
print(surface.GetBounds())

print("\nPointData arrays")
pointData = surface.GetPointData()

for i in range(pointData.GetNumberOfArrays()):
    print("-", pointData.GetArrayName(i))

print("\nCellData arrays")
cellData = surface.GetCellData()

for i in range(cellData.GetNumberOfArrays()):
    print("-", cellData.GetArrayName(i))