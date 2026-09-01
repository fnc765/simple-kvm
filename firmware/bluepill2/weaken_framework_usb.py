"""Make the repository's USB overrides win over STM32duino's copies.

STM32duino compiles its built-in USBDevice sources as ordinary objects before
the project objects.  GNU ld therefore kept those first definitions when
``--allow-multiple-definition`` was used, silently discarding most of the
three-interface HID implementation.  Weakening only the three framework
objects immediately before linking lets the project's strong definitions win
while retaining any framework-only fallback symbols.
"""

from pathlib import Path
import subprocess

Import("env")  # type: ignore[name-defined]  # PlatformIO/SCons injection


_FRAMEWORK_USB_OBJECTS = (
    Path("USBDevice/src/usbd_desc.c.o"),
    Path("USBDevice/src/usbd_ep_conf.c.o"),
    Path("USBDevice/src/hid/usbd_hid_composite.c.o"),
)


def _weaken_framework_usb(target, source, env):  # noqa: ANN001
    build_dir = Path(env.subst("$BUILD_DIR"))
    objcopy_name = env.subst("$OBJCOPY").strip('"')
    objcopy = env.WhereIs(objcopy_name) or objcopy_name

    for relative_path in _FRAMEWORK_USB_OBJECTS:
        object_path = build_dir / relative_path
        if not object_path.is_file():
            raise RuntimeError(f"framework USB object not found: {object_path}")
        subprocess.run(
            [objcopy, "--weaken", str(object_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"Weakened framework USB object: {relative_path}")


env.AddPreAction("$BUILD_DIR/${PROGNAME}.elf", _weaken_framework_usb)  # type: ignore[name-defined]
