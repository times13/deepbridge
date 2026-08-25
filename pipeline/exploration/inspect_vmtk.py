from vmtk import vmtkscripts
import inspect

print("=" * 80)
print("CLASSES VMTK")
print("=" * 80)

count = 0

for name in sorted(dir(vmtkscripts)):
    obj = getattr(vmtkscripts, name)

    if inspect.isclass(obj):
        print(name)
        count += 1

print("\nNombre de classes :", count)