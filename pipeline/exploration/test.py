from vmtk import vmtkscripts

reader = vmtkscripts.vmtkImageReader()
reader.InputFileName = r"C:\Projetsss\component_2.nii.gz"
reader.Execute()

mc = vmtkscripts.vmtkMarchingCubes()
mc.Image = reader.Image
mc.Level = 0.5
mc.Execute()

viewer = vmtkscripts.vmtkSurfaceViewer()
viewer.Surface = mc.Surface
viewer.Execute()