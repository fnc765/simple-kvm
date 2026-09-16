"""Independent reference model for mono USB audio bridge primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import struct


FRAME_BYTES = 112
PCM_BYTES = 96
SAMPLES_PER_FRAME = 48
RING_TARGET = 512
RING_CAPACITY = 1024
ASRC_CLAMP_PPM = 2000


class FrameError(Enum):
    OK = auto()
    LENGTH = auto()
    MAGIC = auto()
    VERSION = auto()
    SAMPLE_COUNT = auto()
    CRC = auto()


@dataclass(frozen=True)
class ReferenceFrame:
    flags: int = 1
    sequence: int = 0
    boot_nonce: int = 0
    session_counter: int = 0
    samples: tuple[int, ...] = ()
    control: bytes = b""


def crc16_ccitt_false(data: bytes | bytearray) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_frame(frame: ReferenceFrame) -> bytes:
    if len(frame.samples) > SAMPLES_PER_FRAME:
        raise ValueError("sample_count exceeds 48")
    output = bytearray(FRAME_BYTES)
    output[:14] = struct.pack(
        "<2sBBHIHBB",
        b"\xA5\x5A",
        1,
        frame.flags & 0xFF,
        frame.sequence & 0xFFFF,
        frame.boot_nonce & 0xFFFFFFFF,
        frame.session_counter & 0xFFFF,
        len(frame.samples),
        0,
    )
    if frame.samples:
        output[14 : 14 + len(frame.samples) * 2] = struct.pack(
            f"<{len(frame.samples)}h", *frame.samples
        )
    else:
        output[14 : 14 + min(len(frame.control), PCM_BYTES)] = frame.control[:PCM_BYTES]
    output[110:112] = crc16_ccitt_false(output[2:110]).to_bytes(2, "little")
    return bytes(output)


def decode_frame(data: bytes) -> tuple[ReferenceFrame | None, FrameError]:
    if len(data) != FRAME_BYTES:
        return None, FrameError.LENGTH
    if data[:2] != b"\xA5\x5A":
        return None, FrameError.MAGIC
    if data[2] != 1:
        return None, FrameError.VERSION
    sample_count = data[12]
    if sample_count > SAMPLES_PER_FRAME:
        return None, FrameError.SAMPLE_COUNT
    if int.from_bytes(data[110:112], "little") != crc16_ccitt_false(data[2:110]):
        return None, FrameError.CRC
    _, _, flags, sequence, nonce, session, _, _ = struct.unpack("<2sBBHIHBB", data[:14])
    samples = (
        struct.unpack(f"<{sample_count}h", data[14 : 14 + sample_count * 2])
        if sample_count
        else ()
    )
    control = b"" if sample_count else data[14:110]
    return (
        ReferenceFrame(
            flags=flags,
            sequence=sequence,
            boot_nonce=nonce,
            session_counter=session,
            samples=tuple(samples),
            control=control,
        ),
        FrameError.OK,
    )


@dataclass(frozen=True)
class ControllerResult:
    min_fill: int
    max_fill: int
    step_ppm: int
    underflows: int
    overflows: int


def simulate_controller(source_ppm: int, seconds: int) -> ControllerResult:
    integral_q16 = 0
    step_ppm = 0
    fill_q16 = RING_TARGET << 16
    source_remainder = 0
    min_fill = RING_TARGET
    max_fill = RING_TARGET
    underflows = 0
    overflows = 0

    for update in range(seconds * 125):
        source_remainder += 384 * source_ppm * 65536
        source_q16 = (384 << 16) + source_remainder // 1_000_000
        source_remainder %= 1_000_000
        consumed_q16 = (384 << 16) + (384 * step_ppm * 65536) // 1_000_000
        fill_q16 += source_q16 - consumed_q16
        fill = fill_q16 >> 16
        if fill <= 0:
            underflows += 1
            fill = RING_TARGET
            fill_q16 = fill << 16
        elif fill >= RING_CAPACITY:
            overflows += 1
            fill = RING_TARGET
            fill_q16 = fill << 16

        error = fill - RING_TARGET
        proposed_integral = max(
            -(ASRC_CLAMP_PPM << 16),
            min(ASRC_CLAMP_PPM << 16, integral_q16 + error * 128),
        )
        proposed = error * 8 + (proposed_integral >> 16)
        if -ASRC_CLAMP_PPM <= proposed <= ASRC_CLAMP_PPM:
            integral_q16 = proposed_integral
        step_ppm = max(
            -ASRC_CLAMP_PPM,
            min(ASRC_CLAMP_PPM, error * 8 + (integral_q16 >> 16)),
        )
        if update > 625:
            min_fill = min(min_fill, fill)
            max_fill = max(max_fill, fill)

    return ControllerResult(min_fill, max_fill, step_ppm, underflows, overflows)
