from vmtk import vmtkscripts

marching = vmtkscripts.vmtkMarchingCubes()

print("=" * 80)
print(type(marching))
print("=" * 80)

print("\nAttributs publics :\n")

for name in sorted(dir(marching)):
    if not name.startswith("_"):
        print(name)