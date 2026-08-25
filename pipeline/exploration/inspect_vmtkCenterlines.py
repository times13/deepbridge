from vmtk import vmtkscripts

selector = vmtkscripts.vmtkCarotidProfilesSeedSelector()

print(type(selector))

for name in sorted(dir(selector)):
    if not name.startswith("_"):
        print(name)