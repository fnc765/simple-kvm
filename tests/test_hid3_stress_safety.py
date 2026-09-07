"""Static safety gates for the one-PC HID stress harness.

The stress harness can move the host cursor by design.  These checks keep its
fail-closed contract visible without requiring a Windows desktop in native CI.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "tools" / "audio_test" / "_bp_e2e_hid3_continuous.py"


def _source() -> str:
    return HARNESS.read_text(encoding="utf-8")


def test_hid_stress_requires_foreground_input_shield_before_serial_open():
    text = _source()
    base = (REPO_ROOT / "tools" / "hardware_loopback.py").read_text(
        encoding="utf-8"
    )
    assert "monitor.start()" in text
    assert "self.require_safe_surface()" in base
    assert "monitor.safety_ok()" in text
    assert "HID3_SAFETY_FAIL" in text
    assert text.index("monitor.start()") < text.index("def open_serial")


def test_hid_stress_stops_injection_when_shield_is_lost():
    text = _source()
    assert "injection_enabled = threading.Event()" in text
    assert "injection_enabled.clear()" in text
    assert "safety_lost.set()" in text
    assert "and injection_enabled.is_set()" in text
    assert "safety_surface_ok" in text


def test_hid_stress_unregisters_raw_input_on_close():
    text = _source()
    assert "def closeEvent" in text
    assert "RIDEV_REMOVE" in text
    assert "for usage in (0x02, 0x06)" in text


def test_shared_loopback_uses_the_same_fail_closed_surface():
    text = (REPO_ROOT / "tools" / "hardware_loopback.py").read_text(
        encoding="utf-8"
    )
    concurrent = (
        REPO_ROOT / "tools" / "audio_test" / "_bp_e2e_hid_concurrent.py"
    ).read_text(encoding="utf-8")
    assert "self.require_safe_surface()" in text
    assert "RIDEV_REMOVE" in text
    assert "AUDIO_HID_SIMULTANEOUS_SAFETY_FAIL" in concurrent
    assert "safety_lost.set()" in concurrent
    assert "LOOPBACK_E2E_SAFETY_FAIL" in text


def test_audio_hid_harness_uses_c52c_and_pnp_preflight():
    text = _source()
    concurrent = (
        REPO_ROOT / "tools" / "audio_test" / "_bp_e2e_hid_concurrent.py"
    ).read_text(encoding="utf-8")
    probe = (REPO_ROOT / "tools" / "audio_test" / "_bp_e2e_probe.py").read_text(
        encoding="utf-8"
    )
    assert "BP2_AUDIO_PID" in text
    assert "BP2_AUDIO_PNP_PREFLIGHT" in text
    assert "bp2_audio_pnp_preflight" in concurrent
    assert "BP2_AUDIO_PID" in concurrent
    assert "bp2_audio_pnp_preflight" in probe
    assert "0xA1D1" not in text + concurrent
    legacy = (REPO_ROOT / "tools" / "hardware_loopback.py").read_text(
        encoding="utf-8"
    )
    assert "BP2_PID = 0xC52B" in legacy


def test_audio_probe_discovers_current_cdc_and_wasapi_devices_fail_closed():
    probe = (REPO_ROOT / "tools" / "audio_test" / "_bp_e2e_probe.py").read_text(
        encoding="utf-8"
    )
    assert "list_ports.comports()" in probe
    assert "BP1_AUDIO_VID = 0x0483" in probe
    assert "BP1_AUDIO_PID = 0xA1D0" in probe
    assert "resolve_bp1_serial_port" in probe
    assert "_select_endpoint" in probe
    assert "BP1_SERIAL_PORT" in probe
    assert "BP1_RENDER" in probe
    assert "BP2_CAPTURE" in probe
    # These were stale machine-specific values; the harness must not silently
    # fall back to them when Windows assigns a different port or endpoint ID.
    assert "COM11" not in probe
    assert "081A7D3C" not in probe
    assert "A627190E" not in probe


def test_audio_probe_ignores_short_startup_glitches_for_alignment():
    probe = (REPO_ROOT / "tools" / "audio_test" / "_bp_e2e_probe.py").read_text(
        encoding="utf-8"
    )
    assert "search_limit = min(len(captured), 131072)" in probe
    assert "sustained = starts" in probe
    assert "max(64, min(len(reference) // 4, 128))" in probe
