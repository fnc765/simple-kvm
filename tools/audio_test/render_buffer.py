"""Hardware-free PCM writer and timer-driven WASAPI buffer policy.

The exclusive USB driver may still be fetching the current scheduling period
when its interpolated position makes a few frames appear writable. Keep one
period free instead of refilling every last advertised frame in the ring.
"""

from __future__ import annotations

import ctypes

import numpy as np


def writable_frames(buffer_frames: int, padding: int, *, guard_frames: int = 0,
                    quantum: int = 1) -> int:
    if buffer_frames <= 0 or not 0 <= padding <= buffer_frames:
        raise ValueError("invalid render buffer/padding")
    if guard_frames < 0 or quantum <= 0:
        raise ValueError("invalid render guard/quantum")
    if guard_frames and buffer_frames < 2 * guard_frames + quantum:
        raise ValueError("render buffer too small for the scheduling guard")
    available = max(0, buffer_frames - padding - guard_frames)
    return available // quantum * quantum


def pcm_payload(samples: np.ndarray, frames: int, *, float32: bool = False,
                channels: int = 1) -> bytes:
    """Encode exactly the acquired frame count, padding the tail only once."""
    if samples.ndim != 1 or not 0 <= len(samples) <= frames or channels < 1:
        raise ValueError("invalid mono samples or render frame count")
    dtype = '<f4' if float32 else '<i2'
    output = np.zeros((frames, channels), dtype=dtype)
    values = samples.astype(dtype)
    if float32:
        values /= 32768.0
    output[:len(samples)] = values[:, None]
    return output.tobytes()


def write_render_packet(render, payload: bytes, frames: int,
                        block_align: int) -> None:
    """Validate BEFORE acquiring the endpoint memory; pair acquire/release."""
    if frames <= 0 or block_align <= 0 or len(payload) != frames * block_align:
        raise ValueError("render payload length does not match acquired frames")
    pointer = render.GetBuffer(frames)
    if isinstance(pointer, tuple):
        pointer = pointer[0]
    if isinstance(pointer, ctypes.c_void_p):
        pointer = pointer.value
    try:
        if not pointer:
            raise RuntimeError("render GetBuffer returned NULL")
        ctypes.memmove(pointer, payload, len(payload))
    except BaseException:
        # ReleaseBuffer(0, 0) cancels this packet without publishing partial PCM.
        render.ReleaseBuffer(0, 0)
        raise
    render.ReleaseBuffer(frames, 0)
