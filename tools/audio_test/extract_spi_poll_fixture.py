"""Extract the unchanged BP2 poll function and its state for native execution."""

from pathlib import Path
import argparse


def extract(source: str) -> str:
    start = "namespace simple_kvm::audio::bp2 {\nnamespace {\n"
    end = "\n}  // namespace\n"
    if source.count(start) != 1:
        raise ValueError("BP2 state namespace changed")
    if source.count(end) != 1:
        raise ValueError("BP2 state namespace boundary changed")
    state = source.split(start, 1)[1].split(end, 1)[0]
    signature = "void audio_spi_slave_poll(uint32_t now_ms)\n{"
    if source.count(signature) != 1:
        raise ValueError("BP2 poll signature changed")
    begin = source.index(signature)
    position = begin + len(signature)
    depth = 1
    while position < len(source) and depth:
        depth += (source[position] == "{") - (source[position] == "}")
        position += 1
    if depth or not source[position:].startswith("\n\n}  // namespace simple_kvm::audio::bp2"):
        raise ValueError("BP2 poll boundary changed")
    return (
        "// Generated from firmware/bluepill2/audio_spi_slave.cpp; do not edit.\n"
        "namespace simple_kvm::audio::bp2 {\nnamespace {\n"
        + state + "\n}\n" + source[begin:position] + "\n}\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--source", type=Path,
        default=Path(__file__).resolve().parents[2] / "firmware/bluepill2/audio_spi_slave.cpp",
    )
    args = parser.parse_args()
    args.output.write_text(extract(args.source.read_text(encoding="utf-8")), encoding="utf-8")
