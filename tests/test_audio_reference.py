"""Independent Python vectors for the hardware-free audio core."""

from __future__ import annotations

import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "audio_test"))

from audio_reference import (  # noqa: E402
    FRAME_BYTES,
    PCM_BYTES,
    SAMPLES_PER_FRAME,
    FrameError,
    ReferenceFrame,
    crc16_ccitt_false,
    decode_frame,
    encode_frame,
    simulate_controller,
)


def test_crc16_ccitt_false_known_vector():
    assert crc16_ccitt_false(b"123456789") == 0x29B1


def test_audio_frame_roundtrip_and_layout():
    samples = tuple(range(-24, 24))
    frame = ReferenceFrame(
        flags=1,
        sequence=0xFFFF,
        boot_nonce=0x78563412,
        session_counter=0x1234,
        samples=samples,
    )
    encoded = encode_frame(frame)
    assert len(encoded) == FRAME_BYTES == 112
    assert encoded[:2] == b"\xA5\x5A"
    assert encoded[12] == SAMPLES_PER_FRAME == 48
    assert len(encoded[14:110]) == PCM_BYTES == 96
    decoded, error = decode_frame(encoded)
    assert error is FrameError.OK
    assert decoded == frame


def test_audio_frame_rejects_crc_magic_version_and_sample_count():
    encoded = bytearray(encode_frame(ReferenceFrame(samples=(0,) * 48)))
    encoded[20] ^= 0x01
    assert decode_frame(bytes(encoded))[1] is FrameError.CRC

    encoded = bytearray(encode_frame(ReferenceFrame(samples=(0,) * 48)))
    encoded[0] = 0
    assert decode_frame(bytes(encoded))[1] is FrameError.MAGIC

    encoded = bytearray(encode_frame(ReferenceFrame(samples=(0,) * 48)))
    encoded[2] = 2
    encoded[110:112] = crc16_ccitt_false(encoded[2:110]).to_bytes(2, "little")
    assert decode_frame(bytes(encoded))[1] is FrameError.VERSION

    encoded = bytearray(encode_frame(ReferenceFrame(samples=(0,) * 48)))
    encoded[12] = 49
    encoded[110:112] = crc16_ccitt_false(encoded[2:110]).to_bytes(2, "little")
    assert decode_frame(bytes(encoded))[1] is FrameError.SAMPLE_COUNT


def test_reference_signal_vectors_cover_full_scale():
    vectors = {
        "silence": (0,) * 48,
        "dc_positive": (32767,) * 48,
        "dc_negative": (-32768,) * 48,
        "impulse": (32767,) + (0,) * 47,
        "alternating": tuple(32767 if i & 1 else -32768 for i in range(48)),
        "sine_997": tuple(
            round(20000 * math.sin(2 * math.pi * 997 * i / 48000))
            for i in range(48)
        ),
    }
    for samples in vectors.values():
        decoded, error = decode_frame(encode_frame(ReferenceFrame(samples=samples)))
        assert error is FrameError.OK
        assert decoded.samples == samples


def test_reference_controller_short_drift_matrix():
    for drift in (-1000, -500, -100, 0, 100, 500, 1000):
        result = simulate_controller(source_ppm=drift, seconds=120)
        assert result.underflows == 0
        assert result.overflows == 0
        assert 205 <= result.min_fill <= result.max_fill <= 819
        assert abs(result.step_ppm - drift) <= 20
