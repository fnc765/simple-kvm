"""Exercise real writes to guarded memory, never a sound device."""
import ctypes

import numpy as np
import pytest

from tools.audio_test.render_buffer import (
    pcm_payload, writable_frames, write_render_packet,
)


class RenderMemory:
    def __init__(self, frames, block_align):
        self.size = frames * block_align
        self.memory = ctypes.create_string_buffer(b'\xa5' * (self.size + 32))
        self.acquired = []
        self.released = []

    def GetBuffer(self, frames):
        self.acquired.append(frames)
        return ctypes.addressof(self.memory) + 16

    def ReleaseBuffer(self, frames, flags):
        self.released.append((frames, flags))


@pytest.mark.parametrize('count', [0, 1, 47, 48])
@pytest.mark.parametrize('float32,channels', [(False, 1), (True, 1), (True, 2)])
def test_payload_stays_inside_acquired_region_including_all_silent_tail(count, float32, channels):
    source = np.arange(count, dtype=np.int16) - 23
    align = (4 if float32 else 2) * channels
    render = RenderMemory(48, align)
    payload = pcm_payload(source, 48, float32=float32, channels=channels)
    write_render_packet(render, payload, 48, align)
    assert render.memory.raw[:16] == b'\xa5' * 16
    assert render.memory.raw[16 + render.size:16 + render.size + 16] == b'\xa5' * 16
    values = np.frombuffer(payload, dtype='<f4' if float32 else '<i2').reshape(48, channels)
    expected = source / 32768.0 if float32 else source
    np.testing.assert_array_equal(values[:count], np.repeat(expected[:, None], channels, axis=1))
    assert not np.any(values[count:])
    assert render.acquired == [48]
    assert render.released == [(48, 0)]


def test_old_double_silence_write_is_rejected_before_buffer_acquisition():
    render = RenderMemory(48, 2)
    with pytest.raises(ValueError, match='payload length'):
        write_render_packet(render, b'\x00' * 192, 48, 2)
    assert not render.acquired
    assert render.memory.raw[:128] == b'\xa5' * 128


@pytest.mark.parametrize('padding', [-1, 38401])
def test_invalid_driver_padding_is_rejected(padding):
    with pytest.raises(ValueError):
        writable_frames(38400, padding, guard_frames=4800, quantum=48)


@pytest.mark.parametrize('lead', [1, 6, 47, 48, 4799])
def test_guard_prevents_next_ring_lap_from_overwriting_inflight_pcm(lead):
    # The saved capture contained source[i + 38400] at source[i]. Model an
    # advertised cursor ahead of the completed USB transfer. An eager writer
    # overwrites the active lap; the scheduling-period guard must not do so.
    size = 38400
    memories = [np.arange(size, dtype=np.int32) for _ in range(2)]
    committed = [size, size]
    mismatches = [0, 0]
    for read in range(0, size * 4, 48):
        advertised = read + lead
        expected = np.arange(read, read + 48)
        for policy, (guard, quantum) in enumerate([(0, 1), (4800, 48)]):
            padding = committed[policy] - advertised
            count = writable_frames(size, padding, guard_frames=guard, quantum=quantum)
            new_pcm = np.arange(committed[policy], committed[policy] + count)
            memories[policy][new_pcm % size] = new_pcm
            committed[policy] += count
            actual = memories[policy][expected % size]
            mismatches[policy] += int(np.count_nonzero(actual != expected))
            if policy == 0:
                # Reproduce the observed signature, not just a risk counter.
                delta = actual - expected
                assert np.all((delta == 0) | (delta == size))
            else:
                np.testing.assert_array_equal(actual, expected)
    assert mismatches[0] == (size * 4 // 48) * min(lead, 48)
    assert mismatches[1] == 0
    assert min(committed) > size * 4


def test_small_render_buffer_fails_before_stream_start():
    with pytest.raises(ValueError, match='too small'):
        writable_frames(4800, 4800, guard_frames=4800, quantum=48)


@pytest.mark.parametrize('wrapped', [False, True])
def test_pointer_results_and_failed_copy_release_acquisition(monkeypatch, wrapped):
    render = RenderMemory(48, 2)
    original = render.GetBuffer
    render.GetBuffer = lambda count: ((ctypes.c_void_p(original(count)),)
                                     if wrapped else ctypes.c_void_p(original(count)))
    def fail_copy(*args):
        raise RuntimeError('copy failed')
    monkeypatch.setattr(ctypes, 'memmove', fail_copy)
    with pytest.raises(RuntimeError, match='copy failed'):
        write_render_packet(render, b'\x00' * 96, 48, 2)
    assert render.acquired == [48]
    assert render.released == [(0, 0)]


def test_null_buffer_is_not_written_and_is_released():
    render = RenderMemory(48, 2)
    render.GetBuffer = lambda count: ctypes.c_void_p()
    with pytest.raises(RuntimeError, match='NULL'):
        write_render_packet(render, b'\x00' * 96, 48, 2)
    assert render.released == [(0, 0)]
