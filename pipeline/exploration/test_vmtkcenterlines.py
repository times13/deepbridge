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

viewer = vmtkscripts.vmtkSurfaceViewer()
viewer.Surface = marching.Surface
viewer.Execute()

print("Surface OK")

# # Centerlines
# center = vmtkscripts.vmtkCenterlines()
# center.Surface = marching.Surface

# # IMPORTANT
# center.SeedSelectorName = "openprofiles"

# print("Avant Execute()")
# writer = vmtkscripts.vmtkSurfaceWriter()
# writer.Surface = marching.Surface
# writer.OutputFileName = r"C:\Projetsss\surface.vtp"
# writer.Execute()

# connect = vmtkscripts.vmtkSurfaceConnectivity()
# connect.Surface = marching.Surface
# connect.Execute()

# center.Surface = connect.Surface

# center.Execute()

# print("Après Execute()")

# print("Centerlines :", center.Centerlines)
# print("Voronoi :", center.VoronoiDiagram)
# print("PoleIds :", center.PoleIds)

# if center.Centerlines:
    # print("Points :", center.Centerlines.GetNumberOfPoints())
    # print("Cells  :", center.Centerlines.GetNumberOfCells())