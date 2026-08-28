"""Audit linked audio descriptors, PMA tables, and resource gates from ELF."""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import tempfile
from pathlib import Path


FLASH_BASE = 0x08000000
RAM_TOTAL = 20 * 1024

PROFILES = {
    "bluepill1_audio": {
        "descriptor": "simple_kvm_bp1_audio_config_descriptor",
        "descriptor_size": 174,
        "interfaces": 4,
        "device": bytes((0xEF, 0x02, 0x01, 64)),
        "pma_used": 488,
        "ep_def": (
            (0x00, 32, 0), (0x80, 96, 0),
            (0x01, 160 | (256 << 16), 1),
            (0x82, 416, 0), (0x83, 480, 0), (0x02, 352, 0),
        ),
    },
    "bluepill2_audio": {
        "descriptor": "simple_kvm_bp2_audio_config_descriptor",
        "descriptor_size": 183,
        "interfaces": 5,
        "device": bytes((0xEF, 0x02, 0x01, 64)),
        "pma_used": 384,
        "ep_def": (
            (0x00, 40, 0), (0x80, 104, 0), (0x81, 168, 0),
            (0x82, 176, 0), (0x83, 184, 0),
            (0x84, 192 | (288 << 16), 1),
        ),
    },
}


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def symbols(nm: Path, elf: Path) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    for line in run(str(nm), "-S", "--defined-only", str(elf)).splitlines():
        match = re.match(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\S\s+(\S+)$", line)
        if match:
            found[match.group(3)] = (int(match.group(1), 16),
                                     int(match.group(2), 16))
    return found


def section_vma(objdump: Path, elf: Path, section: str) -> int:
    for line in run(str(objdump), "-h", str(elf)).splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[1] == section:
            return int(fields[3], 16)
    raise AssertionError(f"missing ELF section {section}")


def linked_bytes(symbol_table: dict[str, tuple[int, int]], name: str,
                 blob: bytes, base: int, expected_size: int) -> bytes:
    address, size = symbol_table[name]
    assert size == expected_size, (name, size, expected_size)
    offset = address - base
    result = blob[offset:offset + size]
    assert len(result) == size
    return result


def section_sizes(size_tool: Path, elf: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in run(str(size_tool), "-A", str(elf)).splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].startswith("."):
            result[fields[0]] = int(fields[1])
    return result


def audit_descriptor(descriptor: bytes, config: dict[str, object]) -> None:
    assert descriptor[0:2] == bytes((9, 2))
    assert int.from_bytes(descriptor[2:4], "little") == len(descriptor)
    assert descriptor[4] == config["interfaces"]
    assert bytes((0x01, 0x01, 0x02, 0x10, 0x01, 0x80, 0xBB, 0x00)) in descriptor
    endpoint_size = bytes((0x60, 0x00))
    assert endpoint_size in descriptor


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=sorted(PROFILES), required=True)
    parser.add_argument("--repo", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--toolchain-bin", type=Path,
                        default=Path.home() / ".platformio" / "packages" /
                                "toolchain-gccarmnoneeabi" / "bin")
    args = parser.parse_args()

    config = PROFILES[args.env]
    build_dir = args.repo / ".pio" / "build" / args.env
    elf = build_dir / "firmware.elf"
    binary = (build_dir / "firmware.bin").read_bytes()
    nm = args.toolchain_bin / "arm-none-eabi-nm.exe"
    objcopy = args.toolchain_bin / "arm-none-eabi-objcopy.exe"
    objdump = args.toolchain_bin / "arm-none-eabi-objdump.exe"
    size_tool = args.toolchain_bin / "arm-none-eabi-size.exe"
    for prerequisite in (elf, nm, objcopy, objdump, size_tool):
        assert prerequisite.exists(), f"missing prerequisite: {prerequisite}"

    symbol_table = symbols(nm, elf)
    descriptor = linked_bytes(
        symbol_table, str(config["descriptor"]), binary, FLASH_BASE,
        int(config["descriptor_size"]))
    audit_descriptor(descriptor, config)

    ep_blob = linked_bytes(symbol_table, "ep_def", binary, FLASH_BASE,
                           len(config["ep_def"]) * 12)
    ep_def = tuple(struct.unpack_from("<III", ep_blob, offset)
                   for offset in range(0, len(ep_blob), 12))
    assert ep_def == config["ep_def"], (ep_def, config["ep_def"])

    with tempfile.TemporaryDirectory(prefix="simple-kvm-elf-audit-") as temp:
        data_path = Path(temp) / "data.bin"
        run(str(objcopy), "--dump-section", f".data={data_path}", str(elf))
        data_blob = data_path.read_bytes()
    data_vma = section_vma(objdump, elf, ".data")
    device = linked_bytes(symbol_table, "USBD_Class_DeviceDesc", data_blob,
                          data_vma, 18)
    assert device[4:8] == config["device"]

    sections = section_sizes(size_tool, elf)
    flash = len(binary)
    static_ram = sections[".data"] + sections[".bss"]
    linker_reserved = sections.get("._user_heap_stack", 0)
    assert flash <= 56 * 1024
    assert static_ram <= 16 * 1024
    assert int(config["pma_used"]) <= 512
    static_headroom = RAM_TOTAL - static_ram
    print(
        "AUDIO_ELF_AUDIT_PASS "
        f"env={args.env} descriptor_bytes={len(descriptor)} "
        f"pma_used={config['pma_used']} flash={flash} "
        f"static_ram={static_ram} linker_reserved={linker_reserved} "
        f"static_headroom={static_headroom}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
