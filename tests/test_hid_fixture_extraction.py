from pathlib import Path
import pytest
from tools.audio_test.extract_hid_fixture import extract

SOURCE = Path(__file__).resolve().parents[1] / "firmware/bluepill2/main.cpp"


def test_hid_fixture_is_verbatim_and_rejects_missing_or_ambiguous_boundaries():
    source = SOURCE.read_text(encoding="utf-8")
    body = extract(source)
    assert body.split("\n", 1)[1] in source
    with pytest.raises(ValueError, match="boundaries"):
        extract(source.replace("// END native-tested HID forwarding", "// removed"))
    with pytest.raises(ValueError, match="boundaries"):
        extract(source + "// BEGIN native-tested HID forwarding\n")


def test_extraction_fails_if_loop_no_longer_calls_timeout_or_activity():
    source = SOURCE.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="timeout/service"):
        extract(source.replace("hid_input_timeout_service(millis());", "/* removed */"))
    with pytest.raises(ValueError, match="activity"):
        extract(source.replace("hid_note_uart_activity(millis());", "/* removed */", 1))
