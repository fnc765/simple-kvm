import ctypes

import pytest

from tools.audio_test.capture_buffer import read_capture_packet


@pytest.mark.parametrize('block_align', [2, 4, 8])
def test_capture_reads_exact_mono_pcm16_mono_float_or_stereo_float_size(block_align):
    memory = ctypes.create_string_buffer(bytes(range(64)))
    result = read_capture_packet(ctypes.c_void_p(ctypes.addressof(memory)), 3, block_align)
    assert result == bytes(range(3 * block_align))


def test_silent_packet_never_dereferences_null_or_invalid_data(monkeypatch):
    def fail_read(*args):
        raise AssertionError('silent data pointer was dereferenced')
    monkeypatch.setattr(ctypes, 'string_at', fail_read)
    assert read_capture_packet(None, 48, 2, silent=True) == bytes(96)
    assert read_capture_packet(1, 48, 4, silent=True) == bytes(192)
    assert read_capture_packet(None, 0, 2) == b''


def test_non_silent_null_packet_fails_before_memory_access():
    with pytest.raises(RuntimeError, match='NULL'):
        read_capture_packet(ctypes.c_void_p(), 48, 2)


@pytest.mark.parametrize('frames,align', [(-1, 2), (48, 0)])
def test_invalid_capture_layout_is_rejected(frames, align):
    with pytest.raises(ValueError):
        read_capture_packet(1, frames, align)
