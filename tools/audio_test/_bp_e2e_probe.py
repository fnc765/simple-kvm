import ctypes
import math
import os
import struct
import sys
import time
from ctypes import POINTER, byref, c_int, c_longlong, c_uint, c_uint16
from ctypes import c_uint32, c_uint64, c_void_p, c_wchar_p, cast, memmove
from pathlib import Path

import numpy as np
import serial
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown, CoCreateInstance


CLSCTX_ALL = 23
CLSID_MMDEVICE_ENUMERATOR = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_MMDEVICE_ENUMERATOR = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_AUDIO_CLIENT = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")

E_DATA_FLOW_RENDER = 0
E_DATA_FLOW_CAPTURE = 1
DEVICE_STATE_ACTIVE = 1
AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_SHAREMODE_EXCLUSIVE = 1
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
# Request the shared-mode RAW processing category so Windows audio
# enhancements/noise gates cannot turn a steady test tone into silence.
AUDCLNT_STREAMFLAGS_RAW = 0x00080000

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.bp2_identity import bp2_audio_pnp_preflight  # noqa: E402


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", c_uint16),
        ("nChannels", c_uint16),
        ("nSamplesPerSec", c_uint32),
        ("nAvgBytesPerSec", c_uint32),
        ("nBlockAlign", c_uint16),
        ("wBitsPerSample", c_uint16),
        ("cbSize", c_uint16),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-C0D8C8A5E7F3}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (['out'], POINTER(c_uint), 'pcDevices')),
        COMMETHOD([], HRESULT, "Item", (['in'], c_uint, 'nDevice'),
                  (['out'], POINTER(c_void_p), 'ppDevice')),
    ]


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate", (['in'], POINTER(GUID), 'iid'),
                  (['in'], c_uint, 'dwClsCtx'), (['in'], c_void_p, 'pActivationParams'),
                  (['out'], POINTER(c_void_p), 'ppInterface')),
        COMMETHOD([], HRESULT, "OpenPropertyStore", (['in'], c_uint, 'stgmAccess'),
                  (['out'], POINTER(c_void_p), 'ppProperties')),
        COMMETHOD([], HRESULT, "GetId", (['out'], POINTER(c_wchar_p), 'ppstrId')),
        COMMETHOD([], HRESULT, "GetState", (['out'], POINTER(c_uint), 'pdwState')),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = IID_MMDEVICE_ENUMERATOR
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints", (['in'], c_int, 'dataFlow'),
                  (['in'], c_uint, 'dwStateMask'),
                  (['out'], POINTER(c_void_p), 'ppDevices')),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint", (['in'], c_int, 'role'),
                  (['out'], POINTER(c_void_p), 'ppEndpoint')),
        COMMETHOD([], HRESULT, "GetDevice", (['in'], c_wchar_p, 'pwstrId'),
                  (['out'], POINTER(c_void_p), 'ppDevice')),
    ]


class IAudioClient(IUnknown):
    _iid_ = IID_AUDIO_CLIENT
    _methods_ = [
        COMMETHOD([], HRESULT, "Initialize", (['in'], c_int, 'ShareMode'),
                  (['in'], c_uint, 'StreamFlags'), (['in'], c_longlong, 'hnsBufferDuration'),
                  (['in'], c_longlong, 'hnsPeriodicity'), (['in'], POINTER(WAVEFORMATEX), 'pFormat'),
                  (['in'], POINTER(GUID), 'AudioSessionGuid')),
        COMMETHOD([], HRESULT, "GetBufferSize", (['out'], POINTER(c_uint), 'pNumBufferFrames')),
        COMMETHOD([], HRESULT, "GetStreamLatency", (['out'], POINTER(c_longlong), 'phnsLatency')),
        COMMETHOD([], HRESULT, "GetCurrentPadding", (['out'], POINTER(c_uint), 'pNumPaddingFrames')),
        COMMETHOD([], HRESULT, "IsFormatSupported", (['in'], c_int, 'ShareMode'),
                  (['in'], POINTER(WAVEFORMATEX), 'pFormat'),
                  (['out'], POINTER(c_void_p), 'ppClosestMatch')),
        COMMETHOD([], HRESULT, "GetMixFormat", (['out'], POINTER(c_void_p), 'ppDeviceFormat')),
        COMMETHOD([], HRESULT, "GetDevicePeriod", (['out'], POINTER(c_longlong), 'phnsDefaultDevicePeriod'),
                  (['out'], POINTER(c_longlong), 'phnsMinimumDevicePeriod')),
        COMMETHOD([], HRESULT, "Start"),
        COMMETHOD([], HRESULT, "Stop"),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "SetEventHandle", (['in'], c_void_p, 'eventHandle')),
        COMMETHOD([], HRESULT, "GetService", (['in'], POINTER(GUID), 'riid'),
                  (['out'], POINTER(c_void_p), 'ppv')),
    ]


class IAudioRenderClient(IUnknown):
    _iid_ = GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer", (['in'], c_uint, 'NumFramesRequested'),
                  (['out'], POINTER(c_void_p), 'ppData')),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (['in'], c_uint, 'NumFramesWritten'),
                  (['in'], c_uint, 'dwFlags')),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetBuffer", (['out'], POINTER(c_void_p), 'ppData'),
                  (['out'], POINTER(c_uint), 'pNumFramesToRead'),
                  (['out'], POINTER(c_uint), 'pdwFlags'),
                  (['out'], POINTER(c_uint64), 'pu64DevicePosition'),
                  (['out'], POINTER(c_uint64), 'pu64QPCPosition')),
        COMMETHOD([], HRESULT, "ReleaseBuffer", (['in'], c_uint, 'NumFramesRead')),
        COMMETHOD([], HRESULT, "GetNextPacketSize", (['out'], POINTER(c_uint), 'pNumFramesInNextPacket')),
    ]


def _obj(ptr, cls):
    if isinstance(ptr, int):
        ptr = c_void_p(ptr)
    return cast(ptr, POINTER(cls))


def get_devices(flow):
    enum = CoCreateInstance(CLSID_MMDEVICE_ENUMERATOR, IMMDeviceEnumerator,
                             clsctx=CLSCTX_ALL)
    raw = enum.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE)
    print("enum raw", type(raw), repr(raw))
    coll = _obj(raw, IMMDeviceCollection) if isinstance(raw, (c_void_p, int)) else raw
    count = coll.GetCount()
    if isinstance(count, tuple):
        count = count[0]
    result = []
    for i in range(int(count.value if hasattr(count, "value") else count)):
        dp = coll.Item(i)
        dev = _obj(dp, IMMDevice) if isinstance(dp, (c_void_p, int)) else dp
        wid = dev.GetId()
        if isinstance(wid, tuple):
            wid = wid[0]
        result.append((wid.value if hasattr(wid, "value") else wid, dev))
    return result


def activate_client(endpoint_id):
    enum = CoCreateInstance(CLSID_MMDEVICE_ENUMERATOR, IMMDeviceEnumerator,
                             clsctx=CLSCTX_ALL)
    raw_dev = enum.GetDevice(endpoint_id)
    dev = _obj(raw_dev, IMMDevice) if isinstance(raw_dev, (c_void_p, int)) else raw_dev
    iid = IID_AUDIO_CLIENT
    raw_client = dev.Activate(byref(iid), CLSCTX_ALL, None)
    if isinstance(raw_client, tuple):
        raw_client = raw_client[0]
    if not isinstance(raw_client, (c_void_p, int)):
        return raw_client
    return _obj(raw_client, IAudioClient)


def get_service(client, iid, interface):
    raw = client.GetService(byref(iid))
    if isinstance(raw, tuple):
        raw = raw[0]
    return _obj(raw, interface) if isinstance(raw, (int, c_void_p)) else raw


def _ptr_value(value):
    if isinstance(value, tuple):
        value = value[0]
    if isinstance(value, c_void_p):
        return value.value
    return value


def get_mix_format(client):
    raw = client.GetMixFormat()
    if isinstance(raw, tuple):
        raw = raw[0]
    ptr = _ptr_value(raw)
    if not ptr:
        raise RuntimeError("IAudioClient::GetMixFormat returned NULL")
    return WAVEFORMATEX.from_buffer_copy(
        ctypes.string_at(ptr, ctypes.sizeof(WAVEFORMATEX)))


def format_desc(fmt):
    tag = {1: "PCM", 3: "float32"}.get(int(fmt.wFormatTag),
                                      f"tag{int(fmt.wFormatTag)}")
    return (f"{int(fmt.nSamplesPerSec)}Hz/{int(fmt.nChannels)}ch/"
            f"{tag}/{int(fmt.wBitsPerSample)}bit")


def read_packets(port, duration=0.2):
    end = time.monotonic() + duration
    pending = bytearray()
    packets = []
    while time.monotonic() < end:
        chunk = port.read(4096)
        if chunk:
            pending.extend(chunk)
        while True:
            if len(pending) < 4:
                break
            try:
                start = pending.index(0xAA)
            except ValueError:
                pending.clear()
                break
            if start:
                del pending[:start]
            if len(pending) < 4:
                break
            length = pending[2]
            total = length + 4
            if length > 16:
                del pending[0]
                continue
            if len(pending) < total:
                break
            raw = bytes(pending[:total])
            del pending[:total]
            if crc8(raw[1:-1]) == raw[-1]:
                packets.append((raw[1], raw[3:-1]))
    return packets


def send_control(port, kind, payload=b"", drain=0.15):
    port.write(frame(kind, payload))
    port.flush()
    return read_packets(port, drain)


def decode_responses(packets):
    result = []
    for kind, payload in packets:
        if kind != 0x2C or len(payload) < 2:
            continue
        device = payload[0]
        page = payload[1]
        if len(payload) >= 16 and page in (1, 2):
            result.append({
                "device": device,
                "page": page,
                "marker": payload[1],
                "run_id": int.from_bytes(payload[2:6], "little"),
                "sequence": int.from_bytes(payload[6:8], "little"),
                "a": int.from_bytes(payload[8:12], "little"),
                "b": int.from_bytes(payload[12:16], "little"),
            })
        elif len(payload) >= 14:
            result.append({
                "device": device,
                "page": page,
                "a": int.from_bytes(payload[2:6], "little"),
                "b": int.from_bytes(payload[6:10], "little"),
                "c": int.from_bytes(payload[10:14], "little"),
            })
    return result


BP2_STATUS_PAGE_NAMES = {
    0: "legacy",
    1: "rx_accept",
    2: "transport_loss",
    3: "frame_validation",
    4: "continuity",
    5: "asrc",
    6: "ring",
    7: "session",
    8: "recovery",
    9: "capture_state",
    10: "usb_mic",
    11: "usb_state",
    12: "hid_busy",
    13: "hid_drop",
}


def read_status_pages(port):
    """Read the finite diagnostics pages without changing stream state."""
    result = {}
    for page, name in BP2_STATUS_PAGE_NAMES.items():
        responses = decode_responses(
            send_control(port, 0x21, bytes([page]), drain=0.05)
        )
        for response in responses:
            response = dict(response)
            response["name"] = name
            result[f"device{response['device']}_page{page}"] = response
    return result


def make_signal():
    rate = 48000
    if os.environ.get("BP_E2E_SIMPLE_TONE") == "1":
        tone_n = int(float(os.environ.get("BP_E2E_TONE_SECONDS", "5")) * rate)
        tone_t = np.arange(tone_n, dtype=np.float64) / rate
        if os.environ.get("BP_E2E_SQUARE") == "1":
            tone = np.where(
                np.sin(2.0 * math.pi * 997.0 * tone_t) >= 0.0,
                8200,
                -8200,
            ).astype(np.int16)
        else:
            tone = np.round(8200.0 * np.sin(2.0 * math.pi * 997.0 * tone_t)).astype(np.int16)
        return tone, tone[:480], tone, tone
    silence = np.zeros(rate // 2, dtype=np.int16)
    rng = np.random.default_rng(0x534B564D)
    preamble = rng.choice(np.array([-12000, 12000], dtype=np.int16), size=480)
    tone_n = 2 * rate
    tone_t = np.arange(tone_n, dtype=np.float64) / rate
    tone = np.round(8200.0 * np.sin(2.0 * math.pi * 997.0 * tone_t)).astype(np.int16)
    chirp_n = rate // 2
    chirp_t = np.arange(chirp_n, dtype=np.float64) / rate
    k = (10000.0 - 100.0) / (chirp_n / rate)
    chirp = np.round(7000.0 * np.sin(2.0 * math.pi * (100.0 * chirp_t + 0.5 * k * chirp_t * chirp_t))).astype(np.int16)
    prbs = rng.integers(-12000, 12001, size=2 * rate, dtype=np.int16)
    end_marker = np.tile(np.array([14000, -14000], dtype=np.int16), 240)
    signal = np.concatenate([silence, preamble, tone, chirp, prbs, end_marker, silence])
    return signal, preamble, tone, prbs


def _continuous_signal_chunk(
    signal: np.ndarray,
    source_index: int,
    count: int,
    active_start: int,
    active_end: int,
) -> np.ndarray:
    """Return a chunk with the active test body repeated without gaps.

    The normal probe appends a trailing half-second silence so that a short
    run has a clean tail.  A long-duration stress run must not turn that tail
    into an artificial underflow, so after the first active body it wraps back
    to the preamble instead.  The initial leading silence remains part of the
    normal startup/preamble alignment.
    """
    if count <= 0:
        return np.empty(0, dtype=signal.dtype)
    body = signal[active_start:active_end]
    if len(body) == 0:
        return np.empty(0, dtype=signal.dtype)
    parts = []
    cursor = int(source_index)
    remaining = int(count)
    while remaining:
        if cursor < active_end:
            take = min(remaining, active_end - cursor)
            parts.append(signal[cursor:cursor + take])
            cursor += take
        else:
            body_offset = (cursor - active_end) % len(body)
            take = min(remaining, len(body) - body_offset)
            parts.append(body[body_offset:body_offset + take])
            cursor += take
        remaining -= take
    return parts[0] if len(parts) == 1 else np.concatenate(parts)


def normalized_corr(left, right):
    n = min(len(left), len(right))
    if n == 0:
        return 0.0
    a = left[:n].astype(np.float64)
    b = right[:n].astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    denom = math.sqrt(float(np.dot(a, a) * np.dot(b, b)))
    return float(np.dot(a, b) / denom) if denom else 0.0


def _resampled_reference(reference, step, phase, count):
    """Render a reference at the receiver's sample clock.

    BP2's ASRC is a linear interpolator.  Comparing captured samples directly
    with the source grid therefore makes a valid high-frequency preamble look
    worse than it is.  ``step`` is source samples consumed per captured sample
    and ``phase`` is the fractional source position at the start of the window.
    """
    if count <= 0 or len(reference) == 0:
        return np.empty(0, dtype=np.float64)
    source = reference.astype(np.float64, copy=False)
    positions = phase + np.arange(count, dtype=np.float64) * step
    return np.interp(positions, np.arange(len(source), dtype=np.float64), source,
                     left=0.0, right=0.0)


def _resampled_corr(captured, reference, offset, step, phase, count=None):
    if offset < 0 or offset >= len(captured):
        return 0.0
    available = len(captured) - offset
    if count is None:
        count = min(available, int(math.ceil(max(1, len(reference) - phase) /
                                           max(step, 1.0e-9))))
    count = min(int(count), available)
    if count <= 0:
        return 0.0
    expected = _resampled_reference(reference, step, phase, count)
    return normalized_corr(captured[offset:offset + count], expected)


def find_offset(captured, reference):
    """Find the first preamble with ASRC phase/rate correction.

    The search is intentionally local to the first activity transition.  A
    later pseudo-random segment can produce a larger accidental correlation if
    the whole recording is searched at the nominal 48 kHz grid.
    """
    if len(captured) <= len(reference):
        return None, 0.0, 1.0, 0.0
    activity = np.flatnonzero(np.abs(captured.astype(np.int32)) > 1000)
    if len(activity) == 0:
        return None, 0.0, 1.0, 0.0
    first = int(activity[0])
    offsets = range(max(0, first - 16), min(len(captured), first + 17))
    # The ASRC nominal clamp is +/-2000 ppm.  A wider search also covers the
    # startup controller transient before the ring has converged.
    coarse_steps = np.linspace(0.996, 1.004, 33)
    coarse_phases = np.linspace(0.0, 0.9375, 16)
    best = (-1.0, first, 1.0, 0.0)
    for offset in offsets:
        for step in coarse_steps:
            for phase in coarse_phases:
                score = _resampled_corr(captured, reference, offset, step,
                                         float(phase), len(reference))
                if score > best[0]:
                    best = (score, offset, float(step), float(phase))
    # Refine the coarse maximum.  Keeping this small bounds the probe runtime
    # while resolving the fractional phase which matters for a PN sequence.
    _, offset0, step0, phase0 = best
    fine_steps = np.linspace(step0 - 0.00025, step0 + 0.00025, 21)
    fine_phases = np.linspace(max(0.0, phase0 - 0.06),
                              min(0.999999, phase0 + 0.06), 25)
    fine_offsets = range(max(0, offset0 - 2), offset0 + 3)
    for offset in fine_offsets:
        for step in fine_steps:
            for phase in fine_phases:
                score = _resampled_corr(captured, reference, offset, step,
                                         float(phase), len(reference))
                if score > best[0]:
                    best = (score, offset, float(step), float(phase))
    return best[1], best[0], best[2], best[3]


def _batched_rate_corr(captured, reference, offsets, starts, steps, count):
    """Return normalized correlations for a small offset/rate candidate set."""
    if count <= 0 or len(offsets) == 0 or len(starts) == 0 or len(steps) == 0:
        return np.empty((0, 0), dtype=np.float64)
    cap_windows = np.stack([
        captured[int(offset):int(offset) + count].astype(np.float64,
                                                           copy=False)
        for offset in offsets
    ])
    cap_windows -= cap_windows.mean(axis=1, keepdims=True)
    cap_norm = np.sqrt(np.sum(cap_windows * cap_windows, axis=1))
    positions = (
        np.asarray(starts, dtype=np.float64)[:, None, None] +
        np.asarray(steps, dtype=np.float64)[None, :, None] *
        np.arange(count, dtype=np.float64)[None, None, :]
    )
    lower = np.floor(positions).astype(np.int64)
    fraction = positions - lower
    valid = (lower >= 0) & (lower + 1 < len(reference))
    lower = np.clip(lower, 0, max(0, len(reference) - 2))
    expected = ((1.0 - fraction) * reference[lower] +
                fraction * reference[lower + 1])
    expected[~valid] = 0.0
    expected = expected.reshape(len(starts) * len(steps), count)
    expected -= expected.mean(axis=1, keepdims=True)
    expected_norm = np.sqrt(np.sum(expected * expected, axis=1))
    dot = cap_windows @ expected.T
    denominator = cap_norm[:, None] * expected_norm[None, :]
    scores = np.divide(dot, denominator, out=np.zeros_like(dot),
                       where=denominator > 0.0)
    return scores


def find_rate_corrected_blocks(captured, reference, expected_offset,
                               initial_step=1.0, block_size=384):
    """Track a deterministic PN section with piecewise-linear ASRC models.

    BP2 updates its PI controller every eight 48-sample USB packets.  A single
    affine rate fitted over the whole two-second PN section therefore mistakes
    an intended controller adjustment for a block error.  This tracker fits
    one source start/step per 384-sample controller interval while constraining
    the next interval to the previous monotonic path.  The returned block
    correlations, aggregate correlation, and alignment-jump count are the
    waveform continuity gate; no free-form time warping is used.
    """
    empty = {
        "offset": None,
        "aggregate_corr": 0.0,
        "min_corr": 0.0,
        "p05_corr": 0.0,
        "mean_corr": 0.0,
        "blocks": 0,
        "block_size": int(block_size),
        "source_per_capture_mean": float(initial_step),
        "source_per_capture_min": float(initial_step),
        "source_per_capture_max": float(initial_step),
        "capture_alignment_jumps": 0,
        "source_alignment_jumps": 0,
        "alignment_failed": True,
    }
    if len(reference) < block_size or len(captured) < block_size:
        return empty

    expected_capture = int(round(expected_offset))
    first_offsets = np.arange(max(0, expected_capture - 64),
                              min(len(captured) - block_size,
                                  expected_capture + 64) + 1,
                              dtype=np.int64)
    first_starts = np.linspace(0.0, 12.0, 25, dtype=np.float64)
    first_steps = np.linspace(initial_step - 0.003, initial_step + 0.003,
                              25, dtype=np.float64)
    first_scores = _batched_rate_corr(
        captured, reference, first_offsets, first_starts, first_steps,
        block_size)
    if first_scores.size == 0:
        return empty
    first_index = np.unravel_index(int(np.argmax(first_scores)),
                                   first_scores.shape)
    first_score = float(first_scores[first_index])
    if first_score < 0.8:
        result = dict(empty)
        result["first_score"] = first_score
        return result
    first_source_index = first_index[1]
    first_start = float(first_starts[first_source_index // len(first_steps)])
    first_step = float(first_steps[first_source_index % len(first_steps)])
    capture_position = float(first_offsets[first_index[0]])
    source_position = first_start
    step_hint = first_step

    rows = []
    captures = []
    expected_blocks = []
    capture_jumps = 0
    source_jumps = 0
    for source_index in range(0, len(reference) - block_size + 1,
                             block_size):
        offsets = np.arange(max(0, int(round(capture_position)) - 8),
                            min(len(captured) - block_size,
                                int(round(capture_position)) + 8) + 1,
                            dtype=np.int64)
        starts = source_position + np.linspace(-1.5, 1.5, 13,
                                               dtype=np.float64)
        steps = np.linspace(max(0.996, step_hint - 0.0015),
                            min(1.004, step_hint + 0.0015), 13,
                            dtype=np.float64)
        scores = _batched_rate_corr(captured, reference, offsets, starts,
                                    steps, block_size)
        if scores.size == 0:
            break
        best_index = np.unravel_index(int(np.argmax(scores)), scores.shape)
        best_score = float(scores[best_index])
        source_candidate = best_index[1]
        best_start = float(starts[source_candidate // len(steps)])
        best_step = float(steps[source_candidate % len(steps)])
        best_capture = int(offsets[best_index[0]])

        # A small refinement around the coarse candidate resolves interpolation
        # phase without allowing an interval to jump to an unrelated PN match.
        refine_offsets = np.arange(max(0, best_capture - 1),
                                   min(len(captured) - block_size,
                                       best_capture + 1) + 1,
                                   dtype=np.int64)
        refine_starts = best_start + np.linspace(-0.30, 0.30, 7,
                                                 dtype=np.float64)
        refine_steps = np.linspace(max(0.996, best_step - 0.0002),
                                   min(1.004, best_step + 0.0002), 9,
                                   dtype=np.float64)
        refine_scores = _batched_rate_corr(
            captured, reference, refine_offsets, refine_starts, refine_steps,
            block_size)
        if refine_scores.size:
            refine_index = np.unravel_index(int(np.argmax(refine_scores)),
                                             refine_scores.shape)
            if float(refine_scores[refine_index]) > best_score:
                best_score = float(refine_scores[refine_index])
                source_candidate = refine_index[1]
                best_start = float(
                    refine_starts[source_candidate // len(refine_steps)])
                best_step = float(
                    refine_steps[source_candidate % len(refine_steps)])
                best_capture = int(refine_offsets[refine_index[0]])

        capture_delta = best_capture - int(round(capture_position))
        source_delta = best_start - source_position
        if abs(capture_delta) > 1:
            capture_jumps += 1
        # Fractional phase is represented by the fitted source start.  A
        # one-sample residual is normal at an interval boundary; a larger
        # discontinuity indicates a duplicate/drop or a time-warp jump.
        if abs(source_delta) > 2.0:
            source_jumps += 1
        rows.append((source_index, best_score, best_capture, best_step,
                     best_start, capture_delta, source_delta))
        captures.append(captured[best_capture:best_capture + block_size])
        expected_blocks.append(
            _resampled_reference(reference, best_step, best_start,
                                 block_size))
        capture_position = float(best_capture + block_size)
        source_position = float(best_start + best_step * block_size)
        step_hint = best_step

    if not rows:
        return empty
    block_scores = np.asarray([row[1] for row in rows], dtype=np.float64)
    rates = np.asarray([row[3] for row in rows], dtype=np.float64)
    captured_joined = np.concatenate(captures)
    expected_joined = np.concatenate(expected_blocks)
    result = {
        "offset": int(rows[0][2]),
        "aggregate_corr": normalized_corr(captured_joined, expected_joined),
        "min_corr": float(np.min(block_scores)),
        "p05_corr": float(np.percentile(block_scores, 5)),
        "mean_corr": float(np.mean(block_scores)),
        "blocks": len(rows),
        "block_size": int(block_size),
        "source_per_capture_mean": float(np.mean(rates)),
        "source_per_capture_min": float(np.min(rates)),
        "source_per_capture_max": float(np.max(rates)),
        "capture_alignment_jumps": int(capture_jumps),
        "source_alignment_jumps": int(source_jumps),
        "alignment_failed": False,
        "first_score": float(rows[0][1]),
    }
    return result


def estimate_frequency(samples, rate=48000):
    if len(samples) < rate // 2:
        return 0.0
    x = samples.astype(np.float64)
    x -= x.mean()
    window = np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft(x * window))
    lo = max(1, int(900 * len(x) / rate))
    hi = min(len(spectrum), int(1100 * len(x) / rate) + 2)
    if hi <= lo:
        return 0.0
    return float(np.argmax(spectrum[lo:hi]) + lo) * rate / len(x)


def zero_run_count(samples, threshold=100, min_length=48):
    """Count unexpected zero runs in an active capture window."""
    if len(samples) == 0:
        return 0, 0
    quiet = np.abs(samples.astype(np.int32)) <= threshold
    edges = np.diff(np.concatenate(([False], quiet, [False])).astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    lengths = ends - starts
    long_runs = lengths[lengths > min_length]
    return int(len(long_runs)), int(np.max(lengths)) if len(lengths) else 0


def crc8(data):
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
    return c


def frame(kind, payload=b""):
    body = bytes([kind, len(payload)]) + payload
    return b"\xAA" + body + bytes([crc8(body)])


def main():
    identity = bp2_audio_pnp_preflight()
    print("BP2_AUDIO_PNP_PREFLIGHT", identity)
    if not identity["ok"]:
        raise RuntimeError(
            f"BP2 audio identity preflight failed: {identity['reason']}"
        )
    render_ids = [x for x, _ in get_devices(E_DATA_FLOW_RENDER)]
    capture_ids = [x for x, _ in get_devices(E_DATA_FLOW_CAPTURE)]
    render_id = next(x for x in render_ids if "081A7D3C" in x.upper())
    capture_id = next(x for x in capture_ids if "A627190E" in x.upper())
    print("BP1_RENDER", render_id)
    print("BP2_CAPTURE", capture_id)

    port = serial.Serial("COM11", 115200, timeout=0.001)
    port.reset_input_buffer()
    if len(sys.argv) > 1 and sys.argv[1] == "--capture-only":
        send_control(port, 0x26, b"\x01", drain=0.05)
        capture_id = next(x for x in capture_ids if "A627190E" in x.upper())
        capture_client = activate_client(capture_id)
        exclusive = os.environ.get("BP_E2E_EXCLUSIVE") == "1"
        capture_mix = (not exclusive and
                       os.environ.get("BP_E2E_CAPTURE_MIX", "1") != "0")
        fmt = (WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0) if exclusive else
               (get_mix_format(capture_client) if capture_mix else
                WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0)))
        capture_flags = 0 if exclusive else AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
        if not exclusive and os.environ.get("BP_E2E_RAW", "1") != "0":
            capture_flags |= AUDCLNT_STREAMFLAGS_RAW
        capture_client.Initialize(
            AUDCLNT_SHAREMODE_EXCLUSIVE if exclusive else AUDCLNT_SHAREMODE_SHARED,
            capture_flags, 1_000_000 if exclusive else 10_000_000,
            1_000_000 if exclusive else 0, byref(fmt), None)
        capture = get_service(capture_client, GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"), IAudioCaptureClient)
        capture_client.Start()
        captured = bytearray()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            while True:
                n = int(capture.GetNextPacketSize())
                if n <= 0:
                    break
                got = capture.GetBuffer()
                ptr, frames, flags_word = _ptr_value(got[0]), int(got[1]), int(got[2])
                if flags_word & 0x2:
                    captured.extend(b"\x00\x00" * frames)
                elif capture_mix:
                    channels = int(fmt.nChannels)
                    block_align = int(fmt.nBlockAlign)
                    raw = ctypes.string_at(ptr, frames * block_align)
                    if fmt.wFormatTag != 3 or channels not in (1, 2):
                        raise RuntimeError(
                            f"unsupported capture mix format: {format_desc(fmt)}")
                    stereo = np.frombuffer(raw, dtype="<f4").reshape(-1, channels)
                    mono = np.clip(np.rint(stereo.mean(axis=1) * 32768.0),
                                   -32768, 32767).astype("<i2")
                    captured.extend(mono.tobytes())
                else:
                    raw = ctypes.string_at(ptr, frames * 2)
                    if not captured or (len(captured) >= 48000 and len(captured) < 49000):
                        print("CAPTURE_PACKET", {"frames": frames,
                                                  "flags": flags_word,
                                                  "hex": raw[:64].hex()})
                    captured.extend(raw)
                capture.ReleaseBuffer(frames)
            time.sleep(0.001)
        capture_client.Stop()
        send_control(port, 0x26, b"\x00", drain=0.05)
        x = np.frombuffer(captured, dtype="<i2")
        print("CAPTURE_ONLY", {"frames": int(len(x)), "rms": float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0, "peak": int(np.max(np.abs(x))) if len(x) else 0, "nonzero": int(np.count_nonzero(x))})
        port.close()
        return
    caps = decode_responses(send_control(port, 0x20))
    print("CAPS", caps)
    status_before = decode_responses(send_control(port, 0x21, b"\x00"))
    print("STATUS_BEFORE", status_before)
    print("STATUS_PAGES_BEFORE", read_status_pages(port))

    signal, preamble, tone, prbs = make_signal()
    continuous_nonzero = os.environ.get("BP_E2E_CONTINUOUS_NONZERO") == "1"
    rate = 48000
    active_start = rate // 2
    active_end = max(active_start, len(signal) - rate // 2)
    render_client = activate_client(render_id)
    capture_client = activate_client(capture_id)
    # Windows shared-mode clients use the endpoint's mix format for the
    # application buffer.  Query that format instead of guessing a packed
    # PCM16 layout; this keeps the probe aligned with the host audio engine
    # while AUTOCONVERTPCM remains enabled for ordinary applications.
    exclusive = os.environ.get("BP_E2E_EXCLUSIVE") == "1"
    render_mix = (not exclusive and
                  os.environ.get("BP_E2E_RENDER_MIX", "1") != "0")
    capture_mix = (not exclusive and
                   os.environ.get("BP_E2E_CAPTURE_MIX", "1") != "0")
    render_fmt = (WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0) if exclusive else
                  (get_mix_format(render_client) if render_mix else
                   WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0)))
    capture_fmt = (WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0) if exclusive else
                   (get_mix_format(capture_client) if capture_mix else
                    WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0)))
    flags = 0 if exclusive else AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
    if not exclusive and os.environ.get("BP_E2E_RAW", "1") != "0":
        flags |= AUDCLNT_STREAMFLAGS_RAW
    share_mode = (AUDCLNT_SHAREMODE_EXCLUSIVE if exclusive
                  else AUDCLNT_SHAREMODE_SHARED)
    duration = 1_000_000 if exclusive else 10_000_000
    periodicity = 1_000_000 if exclusive else 0
    render_client.Initialize(share_mode, flags, duration, periodicity,
                             byref(render_fmt), None)
    capture_client.Initialize(share_mode, flags, duration, periodicity,
                              byref(capture_fmt), None)
    render_size = int(render_client.GetBufferSize())
    capture_size = int(capture_client.GetBufferSize())
    render = get_service(render_client, GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}"), IAudioRenderClient)
    capture = get_service(capture_client, GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"), IAudioCaptureClient)
    mode_label = ("WASAPI_EXCLUSIVE" if exclusive
                  else "WASAPI_SHARED_AUTOCONVERT")
    print(mode_label, {"render_buffer_frames": render_size,
                       "capture_buffer_frames": capture_size,
                       "render_format": format_desc(render_fmt),
                       "capture_format": format_desc(capture_fmt)})

    run_id = int(time.time() * 1000) & 0xFFFFFFFF
    # Fill the initial shared render buffer before Start.  BP1 emits its
    # SESSION_START when alt 1 is selected; prefill prevents the 3 ms BP2
    # source-timeout from firing before the first PCM packet arrives.
    source_index = 0
    initial_available = render_size - int(render_client.GetCurrentPadding())
    initial_take = min(initial_available, len(signal))
    initial_values = (signal[:initial_take].astype("<f4") / 32768.0
                      if render_mix else signal[:initial_take].astype("<i2", copy=False))
    initial_payload = initial_values.tobytes()
    frame_bytes = 4 if render_mix else 2
    if initial_take < initial_available:
        initial_payload += b"\x00" * frame_bytes * (initial_available - initial_take)
    initial_ptr = _ptr_value(render.GetBuffer(initial_available))
    memmove(initial_ptr, initial_payload, len(initial_payload))
    render.ReleaseBuffer(initial_available, 0)
    source_index = initial_take

    # Start capture first so BP2 selects capture alt 1 before source data arrives.
    capture_client.Start()
    if os.environ.get("BP_E2E_BP2_TONE") == "1":
        send_control(port, 0x26, b"\x01", drain=0.01)
    render_client.Start()
    time.sleep(0.05)
    start_packets = send_control(port, 0x23, struct.pack("<I", run_id), drain=0.03)
    print("RUN_START_SENT", run_id, "RESP", start_packets)

    captured = bytearray()
    capture_flags = {}
    start_time = time.monotonic()
    run_seconds = float(os.environ.get("BP_E2E_RUN_SECONDS", "8.5"))
    render_done_time = None
    last_report = start_time
    last_live_status = start_time
    # The signal is ~5.7 s; keep the endpoints running long enough to drain it.
    while time.monotonic() - start_time < run_seconds:
        available = render_size - int(render_client.GetCurrentPadding())
        if available > 0:
            if continuous_nonzero:
                take = available
            else:
                take = min(available, max(0, len(signal) - source_index))
            if take:
                if continuous_nonzero:
                    chunk = _continuous_signal_chunk(
                        signal, source_index, take, active_start, active_end
                    )
                else:
                    chunk = signal[source_index:source_index + take]
                values = (chunk.astype("<f4") / 32768.0
                          if render_mix else chunk.astype("<i2", copy=False))
                payload = values.tobytes()
                source_index += take
            else:
                payload = b"\x00" * frame_bytes * available
            if take < available:
                payload += b"\x00" * frame_bytes * (available - take)
            ptr = _ptr_value(render.GetBuffer(available))
            memmove(ptr, payload, len(payload))
            render.ReleaseBuffer(available, 0)
            if source_index >= len(signal) and render_done_time is None:
                render_done_time = time.monotonic()

        total = 0
        while True:
            next_size = int(capture.GetNextPacketSize())
            if next_size <= 0:
                break
            got = capture.GetBuffer()
            if not isinstance(got, tuple) or len(got) < 3:
                raise RuntimeError(f"unexpected capture GetBuffer result: {got!r}")
            ptr, frames, flags_word = _ptr_value(got[0]), int(got[1]), int(got[2])
            packet_start = len(captured) // 2
            if (not captured or packet_start % 48000 < frames):
                raw_bytes = ctypes.string_at(ptr, frames * (8 if capture_mix else 2))
                print("E2E_CAPTURE_PACKET", {
                    "frames": frames,
                    "flags": flags_word,
                    "format": "f32/stereo" if capture_mix else "i16/mono",
                    "hex": raw_bytes[:64].hex(),
                })
            if flags_word & 0x2:
                captured.extend(b"\x00\x00" * frames)
                capture_flags["silent_packets"] = capture_flags.get("silent_packets", 0) + 1
            elif capture_mix:
                channels = int(capture_fmt.nChannels)
                block_align = int(capture_fmt.nBlockAlign)
                raw = ctypes.string_at(ptr, frames * block_align)
                if capture_fmt.wFormatTag != 3 or channels not in (1, 2):
                    raise RuntimeError(
                        f"unsupported capture mix format: {format_desc(capture_fmt)}")
                stereo = np.frombuffer(raw, dtype="<f4").reshape(-1, channels)
                mono = np.clip(np.rint(stereo.mean(axis=1) * 32768.0),
                               -32768, 32767).astype("<i2")
                captured.extend(mono.tobytes())
            else:
                raw = ctypes.string_at(ptr, frames * 2)
                captured.extend(raw)
            capture.ReleaseBuffer(frames)
            total += frames
        now = time.monotonic()
        if now - last_report > 1.0:
            print("PROGRESS", {"source_frames": source_index, "capture_frames": len(captured) // 2, "capture_batch": total})
            last_report = now
        if now - last_live_status > 1.0:
            live = decode_responses(send_control(port, 0x21, b"\x00", drain=0.01))
            print("LIVE_STATUS", live)
            last_live_status = now
        time.sleep(0.001)

    end_packets = send_control(port, 0x24, struct.pack("<I", run_id), drain=0.05)
    time.sleep(0.15)
    render_client.Stop()
    capture_client.Stop()
    if os.environ.get("BP_E2E_BP2_TONE") == "1":
        send_control(port, 0x26, b"\x00", drain=0.01)
    status_after = decode_responses(send_control(port, 0x21, b"\x00"))
    status_pages_after = read_status_pages(port)
    start_snap = decode_responses(send_control(port, 0x22, struct.pack("<I B", run_id, 1)))
    end_snap = decode_responses(send_control(port, 0x22, struct.pack("<I B", run_id, 2)))
    print("RUN_END_SENT", run_id, "RESP", end_packets)
    print("STATUS_AFTER", status_after)
    print("STATUS_PAGES_AFTER", status_pages_after)
    print("RUN_START_SNAPSHOT", start_snap)
    print("RUN_END_SNAPSHOT", end_snap)

    captured_i16 = np.frombuffer(captured, dtype="<i2")
    capture_path = REPO_ROOT / ".pio" / "bp2_e2e_capture.raw"
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    captured_i16.tofile(str(capture_path))
    offset, preamble_corr, preamble_step, preamble_phase = find_offset(
        captured_i16, preamble)
    rate = 48000
    chirp_length = rate // 2
    end_marker_length = 480
    metrics = {
        "captured_frames": int(len(captured_i16)),
        "captured_rms": float(np.sqrt(np.mean(captured_i16.astype(np.float64) ** 2))) if len(captured_i16) else 0.0,
        "captured_peak": int(np.max(np.abs(captured_i16))) if len(captured_i16) else 0,
        "nonzero_frames": int(np.count_nonzero(captured_i16)),
        "preamble_offset": offset,
        "preamble_corr": preamble_corr,
        "preamble_step": preamble_step,
        "preamble_phase": preamble_phase,
        "silent_capture_packets": capture_flags.get("silent_packets", 0),
    }
    if offset is not None:
        # find_offset() returns the absolute capture index of the preamble,
        # not the beginning of the complete source signal (the leading
        # 500-ms silence is already reflected in that index).
        tone_start = offset + len(preamble)
        tone_slice = captured_i16[tone_start:tone_start + len(tone)]
        # Map the source PRBS boundary through the measured preamble clock.
        # The tracker then fits only one ASRC model per PI-controller interval.
        source_prbs_offset = rate // 2 + len(preamble) + len(tone) + chirp_length
        prbs_expected = int(round(
            offset + (source_prbs_offset - rate // 2 - preamble_phase) /
            max(preamble_step, 1.0e-9)))
        prbs_metrics = find_rate_corrected_blocks(
            captured_i16, prbs, prbs_expected, preamble_step)
        active_end = min(
            len(captured_i16),
            (prbs_metrics["offset"] + len(prbs) + end_marker_length)
            if prbs_metrics["offset"] is not None else len(captured_i16),
        )
        zero_runs, longest_zero_run = zero_run_count(
            captured_i16[max(0, int(offset)):active_end])
        tone_rms = (float(np.sqrt(np.mean(tone_slice.astype(np.float64) ** 2)))
                    if len(tone_slice) else 0.0)
        reference_tone_rms = float(
            np.sqrt(np.mean(tone.astype(np.float64) ** 2)))
        gain_db = (20.0 * math.log10(tone_rms / reference_tone_rms)
                   if tone_rms > 0.0 and reference_tone_rms > 0.0 else -math.inf)
        metrics["tone_frequency_hz"] = estimate_frequency(tone_slice)
        metrics["latency_ms"] = (float(offset - rate // 2) * 1000.0 / rate)
        metrics["tone_rms"] = tone_rms
        metrics["tone_reference_rms"] = reference_tone_rms
        metrics["tone_gain_db"] = gain_db
        metrics["tone_clipping_samples"] = int(
            np.count_nonzero(np.abs(tone_slice.astype(np.int32)) >= 32767))
        metrics["tone_dc_offset"] = (float(np.mean(tone_slice))
                                      if len(tone_slice) else 0.0)
        metrics["tone_corr"] = normalized_corr(tone_slice, tone)
        metrics["unexpected_zero_runs"] = zero_runs
        metrics["longest_zero_run"] = longest_zero_run
        metrics.update({f"prbs_{key}": value
                        for key, value in prbs_metrics.items()})
    print("AUDIO_E2E_METRICS", metrics)
    gate_failures = []
    if not exclusive:
        gate_failures.append("numeric_gate_requires_wasapi_exclusive")
    render_format_key = (int(render_fmt.nSamplesPerSec),
                         int(render_fmt.nChannels),
                         int(render_fmt.wFormatTag),
                         int(render_fmt.wBitsPerSample))
    capture_format_key = (int(capture_fmt.nSamplesPerSec),
                          int(capture_fmt.nChannels),
                          int(capture_fmt.wFormatTag),
                          int(capture_fmt.wBitsPerSample))
    if render_format_key != (48000, 1, 1, 16):
        gate_failures.append("render_format")
    if capture_format_key != (48000, 1, 1, 16):
        gate_failures.append("capture_format")
    if offset is None or preamble_corr < 0.995:
        gate_failures.append("preamble_correlation")
    if offset is not None:
        if not 996.0 <= metrics.get("tone_frequency_hz", 0.0) <= 998.0:
            gate_failures.append("tone_frequency")
        if abs(metrics.get("tone_gain_db", -math.inf)) > 0.25:
            gate_failures.append("tone_gain")
        if metrics.get("tone_clipping_samples", 1) != 0:
            gate_failures.append("tone_clipping")
        if metrics.get("unexpected_zero_runs", 1) != 0:
            gate_failures.append("unexpected_zero_run")
        if not 0.0 <= metrics.get("latency_ms", math.inf) < 250.0:
            gate_failures.append("exclusive_latency")
        if metrics.get("prbs_aggregate_corr", 0.0) < 0.995:
            gate_failures.append("prbs_correlation")
        if metrics.get("prbs_p05_corr", 0.0) < 0.995:
            gate_failures.append("prbs_block_correlation")
        if metrics.get("prbs_capture_alignment_jumps", 1) != 0:
            gate_failures.append("capture_alignment_jump")
        if metrics.get("prbs_source_alignment_jumps", 1) != 0:
            gate_failures.append("source_alignment_jump")
    if gate_failures:
        print("AUDIO_SINGLE_HOST_FAIL", {"reasons": gate_failures})
    else:
        print("AUDIO_SINGLE_HOST_PASS", {
            "profile": "exclusive_pcm16",
            "duration_s": run_seconds,
            "prbs_blocks": metrics.get("prbs_blocks", 0),
        })
    port.close()


if __name__ == "__main__":
    main()
