from vmtk import vmtkscripts

center = vmtkscripts.vmtkCenterlines()

print("="*80)
print(type(center))
print("="*80)

for name in sorted(dir(center)):
    if not name.startswith("_"):
        print(name)