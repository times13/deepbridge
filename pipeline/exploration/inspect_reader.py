from vmtk import vmtkscripts

reader = vmtkscripts.vmtkImageReader()

print("=" * 80)
print(type(reader))
print("=" * 80)

print("\nAttributs publics :\n")

for name in sorted(dir(reader)):
    if not name.startswith("_"):
        print(name)