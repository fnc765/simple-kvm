"""Bounded capture reads, including WASAPI's silent packets with NULL data."""
import ctypes


def read_capture_packet(pointer, frames: int, block_align: int, *, silent=False) -> bytes:
    if frames < 0 or block_align <= 0:
        raise ValueError('invalid capture frame count or block alignment')
    size = frames * block_align
    if silent or not size:
        return bytes(size)
    if isinstance(pointer, ctypes.c_void_p):
        pointer = pointer.value
    if not pointer:
        raise RuntimeError('non-silent capture packet has NULL data')
    return ctypes.string_at(pointer, size)
