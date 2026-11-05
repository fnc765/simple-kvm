"""Execute the real WASAPI setup/capture code with only COM/I/O replaced."""
import ctypes
import sys

import numpy as np
import pytest

if sys.platform != "win32":
    pytest.skip("WASAPI COM definitions require Windows", allow_module_level=True)

from tools.audio_test import _bp_e2e_probe as audio
from tools.audio_test import windows_audio


class Client:
    def __init__(self, fail_raw=False):
        self.calls = []
        self.fail_raw = fail_raw

    def QueryInterface(self, interface):
        assert str(interface._iid_).upper() == "{726778CD-F60A-4EDA-82DE-E47610CD78AA}"
        self.calls.append("query")
        return self

    def SetClientProperties(self, pointer):
        p = ctypes.cast(pointer, ctypes.POINTER(audio.AudioClientProperties)).contents
        self.calls.append(("properties", p.cbSize, p.bIsOffload, p.eCategory, p.Options))
        if self.fail_raw:
            raise RuntimeError("RAW rejected")

    def Initialize(self, mode, flags, duration, periodicity, pointer, guid):
        p = ctypes.cast(pointer, ctypes.POINTER(audio.WAVEFORMATEX)).contents
        self.calls.append(("initialize", mode, flags, duration, periodicity,
                           p.wFormatTag, p.nChannels, p.nSamplesPerSec, p.wBitsPerSample))

    def Start(self):
        self.calls.append("start")

    def Stop(self):
        self.calls.append("stop")


def test_shared_raw_uses_client_properties_before_native_pcm_initialization(monkeypatch):
    client = Client()
    monkeypatch.setattr(audio, "get_mix_format", lambda _: pytest.fail("RAW used processed mix format"))
    fmt = audio.initialize_audio_client(client, exclusive=False, use_mix=True)
    assert client.calls == [
        "query", ("properties", 16, 0, 0, 1),
        ("initialize", 0, 0, 10_000_000, 0, 1, 1, 48000, 16),
    ]
    assert fmt.nBlockAlign == 2


def test_raw_failure_is_not_silently_retried_as_processed_audio():
    client = Client(fail_raw=True)
    with pytest.raises(RuntimeError, match="RAW rejected"):
        audio.initialize_audio_client(client, exclusive=False)
    assert not any(isinstance(c, tuple) and c[0] == "initialize" for c in client.calls)


def test_exclusive_stream_does_not_request_shared_raw_properties():
    client = Client()
    audio.initialize_audio_client(client, exclusive=True, use_mix=True)
    assert client.calls == [("initialize", 1, 0, 1_000_000, 1_000_000, 1, 1, 48000, 16)]


def test_explicit_processed_mix_preserves_float_stereo_and_autoconvert(monkeypatch):
    client = Client()
    monkeypatch.setattr(audio, "get_mix_format", lambda _: audio.WAVEFORMATEX(3, 2, 48000, 384000, 8, 32, 0))
    audio.initialize_audio_client(client, exclusive=False, use_mix=True, raw=False)
    assert client.calls == [("initialize", 0, 0x80000000, 10_000_000, 0, 3, 2, 48000, 32)]


@pytest.mark.parametrize("raw", [True, False])
def test_capture_executes_shared_raw_pcm_or_processed_float_decode(monkeypatch, raw):
    client = Client()
    expected = np.array([0, 16384] * 24, dtype="<i2")
    payload = expected.tobytes() if raw else np.tile(np.array([[.25, -.25], [.5, .5]], dtype="<f4"), (24, 1)).tobytes()
    memory = ctypes.create_string_buffer(payload)

    class Capture:
        ready = True

        def GetNextPacketSize(self): return 48 if self.ready else 0
        def GetBuffer(self): return ctypes.addressof(memory), 48, 0
        def ReleaseBuffer(self, frames):
            assert frames == 48
            self.ready = False

    capture = Capture()
    monkeypatch.setattr(audio, "activate_client", lambda _: client)
    monkeypatch.setattr(audio, "get_service", lambda *_: capture)
    monkeypatch.setattr(audio, "get_mix_format", lambda _: audio.WAVEFORMATEX(3, 2, 48000, 384000, 8, 32, 0))
    pcm, metadata = windows_audio.capture_pcm16("test-endpoint", .003, exclusive=False, raw=raw)
    assert pcm == expected.tobytes()
    assert metadata["frames"] == 48 and metadata["raw"] is raw
    assert metadata["exclusive"] is False
    assert metadata["format"] == ("48000Hz/1ch/PCM/16bit" if raw else "48000Hz/2ch/float32/32bit")
    assert client.calls[-2:] == ["start", "stop"]
