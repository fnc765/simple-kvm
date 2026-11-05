"""Extract BP2's unchanged HID state/functions for native SDK-boundary tests."""
from pathlib import Path
import argparse


def extract(source: str) -> str:
    begin = "// BEGIN native-tested HID forwarding\n"
    end = "// END native-tested HID forwarding\n"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise ValueError("BP2 HID fixture boundaries changed")
    if source.count("hid_note_uart_activity(millis());") != 2:
        raise ValueError("BP2 setup/parser activity wiring changed")
    loop = source.split("void loop()\n{", 1)[1]
    if not loop.endswith(
        "    hid_input_timeout_service(millis());\n"
        "    abs_mouse_service();\n    hid_queued_service();\n}\n"
    ):
        raise ValueError("BP2 loop timeout/service wiring changed")
    body = source.split(begin, 1)[1].split(end, 1)[0]
    return "// Generated verbatim from firmware/bluepill2/main.cpp.\n" + body


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2] / "firmware/bluepill2/main.cpp")
    args = parser.parse_args()
    args.output.write_text(extract(args.source.read_text(encoding="utf-8")), encoding="utf-8")
