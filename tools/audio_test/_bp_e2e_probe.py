import ctypes
import math
import os
import struct
import sys
import time
from ctypes import POINTER, byref, c_int, c_longlong, c_uint, c_uint16
from ctypes import c_uint32, c_uint64, c_ubyte, c_void_p, c_wchar_p, cast
from pathlib import Path

import numpy as np
import serial
from serial.tools import list_ports
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
from tools.audio_test.render_buffer import (  # noqa: E402
    pcm_payload, writable_frames, write_render_packet,
)
from tools.audio_test.capture_buffer import read_capture_packet  # noqa: E402
from tools.verification_policy import (  # noqa: E402
    VerificationPolicyError,
    preflight,
)
BP1_AUDIO_VID = 0x0483
BP1_AUDIO_PID = 0xA1D0
BP2_AUDIO_PRODUCT = "USB Receiver"
BP1_RENDER_TOKENS = ("BP1 Audio Dev", "USB Audio Device")
BP1_PORT_ENV = "BP_E2E_PORT"
RENDER_ENDPOINT_ENV = "BP_E2E_RENDER_ID"
CAPTURE_ENDPOINT_ENV = "BP_E2E_CAPTURE_ID"
_VT_LPWSTR = 31
_PROPVARIANT_BYTES = c_ubyte * 24


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_uint)]


class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEF-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount",
                  (["out"], POINTER(c_uint), "cProps")),
        COMMETHOD([], HRESULT, "GetAt",
                  (["in"], c_uint, "iProp"),
                  (["out"], POINTER(PROPERTYKEY), "pkey")),
        COMMETHOD([], HRESULT, "GetValue",
                  (["in"], POINTER(PROPERTYKEY), "key"),
                  (["out"], POINTER(_PROPVARIANT_BYTES), "pv")),
    ]


_PKEY_DEVICE_FRIENDLY_NAME = PROPERTYKEY(
    GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14
)


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


def _friendly_name(device) -> str:
    """Read an active WASAPI endpoint's Windows friendly name."""
    raw_store = device.OpenPropertyStore(0)
    store = _obj(raw_store, IPropertyStore)
    raw_value = store.GetValue(byref(_PKEY_DEVICE_FRIENDLY_NAME))
    try:
        raw_bytes = bytes(raw_value)
        variant_type = int.from_bytes(raw_bytes[:2], "little")
        if variant_type != _VT_LPWSTR:
            return ""
        pointer = int.from_bytes(raw_bytes[8:16], "little")
        return ctypes.wstring_at(pointer) if pointer else ""
    finally:
        windll = getattr(ctypes, "windll", None)
        if windll is not None:
            clear = windll.ole32.PropVariantClear
            clear.argtypes = [POINTER(_PROPVARIANT_BYTES)]
            clear.restype = ctypes.c_long
            clear(byref(raw_value))


def _audio_endpoint_inventory(flow):
    return [
        (endpoint_id, _friendly_name(device))
        for endpoint_id, device in get_devices(flow)
    ]


def _format_endpoint_inventory(entries) -> str:
    return "; ".join(
        f"{endpoint_id} [{friendly or '<unknown>'}]"
        for endpoint_id, friendly in entries
    )


def _select_endpoint(entries, env_name, role, token=None, allow_single=False):
    override = os.environ.get(env_name, "").strip()
    endpoint_ids = {endpoint_id for endpoint_id, _ in entries}
    if override:
        if override not in endpoint_ids:
            raise RuntimeError(
                f"{role} override {env_name}={override!r} is not active; "
                f"inventory={_format_endpoint_inventory(entries)}"
            )
        return override

    tokens = (token,) if isinstance(token, str) else tuple(token or ())
    candidates = [
        endpoint_id
        for endpoint_id, friendly in entries
        if any(candidate.casefold() in friendly.casefold() for candidate in tokens)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates and allow_single and len(entries) == 1:
        return entries[0][0]
    raise RuntimeError(
        f"could not uniquely resolve {role}; set {env_name}; "
        f"inventory={_format_endpoint_inventory(entries)}"
    )


def resolve_bp1_serial_port() -> str:
    """Resolve BP1's CDC port by VID/PID, with a validated override."""
    ports = list(list_ports.comports())
    override = os.environ.get(BP1_PORT_ENV, "").strip()
    candidates = [
        port for port in ports
        if port.vid == BP1_AUDIO_VID and port.pid == BP1_AUDIO_PID
    ]
    if override:
        selected = next(
            (port for port in ports
             if port.device.casefold() == override.casefold()),
            None,
        )
        if selected is None:
            raise RuntimeError(
                f"{BP1_PORT_ENV}={override!r} is not present; "
                f"ports={[port.device for port in ports]}"
            )
        if selected.vid != BP1_AUDIO_VID or selected.pid != BP1_AUDIO_PID:
            raise RuntimeError(
                f"{BP1_PORT_ENV}={override!r} is not BP1 audio "
                f"VID:PID={BP1_AUDIO_VID:04X}:{BP1_AUDIO_PID:04X}"
            )
        return selected.device
    if len(candidates) != 1:
        inventory = [
            f"{port.device} VID:PID={port.vid!s}:{port.pid!s}"
            for port in ports
        ]
        raise RuntimeError(
            "BP1 audio CDC port is not uniquely present; "
            f"set {BP1_PORT_ENV}; inventory={inventory}"
        )
    return candidates[0].device
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


from tools.audio_test.waveform import (  # noqa: E402
    make_signal, _continuous_signal_chunk, normalized_corr, _resampled_reference,
    _resampled_corr, find_offset, _batched_rate_corr, find_rate_corrected_blocks,
    estimate_frequency, zero_run_count, analyze_capture, numeric_failures,
)


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
    capture_only = len(sys.argv) > 1 and sys.argv[1] == "--capture-only"
    try:
        planned_seconds = (
            3.0
            if capture_only
            else float(os.environ.get("BP_E2E_RUN_SECONDS", "8.5"))
        )
        verification_plan = preflight(
            "BP1/BP2 live audio probe", planned_seconds
        )
    except (ValueError, VerificationPolicyError) as exc:
        print(
            "AUDIO_SINGLE_HOST_FAIL",
            {"reasons": ["verification_policy", str(exc)]},
            flush=True,
        )
        return 2

    identity = bp2_audio_pnp_preflight()
    print("BP2_AUDIO_PNP_PREFLIGHT", identity)
    if not identity["ok"]:
        raise RuntimeError(
            f"BP2 audio identity preflight failed: {identity['reason']}"
        )
    render_entries = _audio_endpoint_inventory(E_DATA_FLOW_RENDER)
    capture_entries = _audio_endpoint_inventory(E_DATA_FLOW_CAPTURE)
    render_id = _select_endpoint(
        render_entries, RENDER_ENDPOINT_ENV, "BP1 render endpoint",
        token=BP1_RENDER_TOKENS, allow_single=True,
    )
    capture_id = _select_endpoint(
        capture_entries, CAPTURE_ENDPOINT_ENV, "BP2 capture endpoint",
        token=BP2_AUDIO_PRODUCT,
    )
    port_name = resolve_bp1_serial_port()
    print("BP1_SERIAL_PORT", port_name)
    print("BP1_RENDER", render_id)
    print("BP2_CAPTURE", capture_id)

    port = serial.Serial(port_name, 115200, timeout=0.001)
    port.reset_input_buffer()
    if capture_only:
        send_control(port, 0x26, b"\x01", drain=0.05)

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
                raw = read_capture_packet(ptr, frames, int(fmt.nBlockAlign),
                                          silent=bool(flags_word & 0x2))
                if flags_word & 0x2:
                    captured.extend(b"\x00\x00" * frames)
                elif capture_mix:
                    channels = int(fmt.nChannels)
                    if fmt.wFormatTag != 3 or channels not in (1, 2):
                        raise RuntimeError(
                            f"unsupported capture mix format: {format_desc(fmt)}")
                    stereo = np.frombuffer(raw, dtype="<f4").reshape(-1, channels)
                    mono = np.clip(np.rint(stereo.mean(axis=1) * 32768.0),
                                   -32768, 32767).astype("<i2")
                    captured.extend(mono.tobytes())
                else:
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
    render_channels = int(render_fmt.nChannels)
    frame_bytes = int(render_fmt.nBlockAlign)
    if (int(render_fmt.wFormatTag), int(render_fmt.wBitsPerSample)) != (
        (3, 32) if render_mix else (1, 16)
    ) or frame_bytes != render_channels * (4 if render_mix else 2):
        raise RuntimeError(f"unsupported render format: {format_desc(render_fmt)}")
    # Preserve a complete scheduling period in timer-driven exclusive mode.
    # Refilling up to an interpolated USB read cursor can overwrite samples
    # still in flight with PCM from the next lap of the endpoint buffer.
    render_guard = (int(math.ceil(periodicity * rate / 10_000_000))
                    if exclusive else 0)
    render_quantum = rate // 1000 if exclusive else 1
    writable_frames(render_size, render_size, guard_frames=render_guard,
                    quantum=render_quantum)  # validate before Start
    print("RENDER_BUFFER_POLICY", {"guard_frames": render_guard,
                                   "quantum_frames": render_quantum})
    initial_payload = pcm_payload(signal[:initial_take], initial_available,
                                  float32=render_mix, channels=render_channels)
    write_render_packet(render, initial_payload, initial_available, frame_bytes)
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
    run_seconds = float(verification_plan.planned_seconds or 0.0)
    render_done_time = None
    last_report = start_time
    last_live_status = start_time
    # The signal is ~5.7 s; keep the endpoints running long enough to drain it.
    while time.monotonic() - start_time < run_seconds:
        available = writable_frames(
            render_size, int(render_client.GetCurrentPadding()),
            guard_frames=render_guard, quantum=render_quantum)
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
                source_index += take
            else:
                chunk = signal[:0]
            payload = pcm_payload(chunk, available, float32=render_mix,
                                  channels=render_channels)
            write_render_packet(render, payload, available, frame_bytes)
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
            raw = read_capture_packet(ptr, frames, int(capture_fmt.nBlockAlign),
                                      silent=bool(flags_word & 0x2))
            packet_start = len(captured) // 2
            if (not captured or packet_start % 48000 < frames):
                print("E2E_CAPTURE_PACKET", {
                    "frames": frames,
                    "flags": flags_word,
                    "format": format_desc(capture_fmt),
                    "hex": raw[:64].hex(),
                })
            if flags_word & 0x2:
                captured.extend(b"\x00\x00" * frames)
                capture_flags["silent_packets"] = capture_flags.get("silent_packets", 0) + 1
            elif capture_mix:
                channels = int(capture_fmt.nChannels)
                if capture_fmt.wFormatTag != 3 or channels not in (1, 2):
                    raise RuntimeError(
                        f"unsupported capture mix format: {format_desc(capture_fmt)}")
                stereo = np.frombuffer(raw, dtype="<f4").reshape(-1, channels)
                mono = np.clip(np.rint(stereo.mean(axis=1) * 32768.0),
                               -32768, 32767).astype("<i2")
                captured.extend(mono.tobytes())
            else:
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
    metrics = analyze_capture(
        captured_i16, preamble, tone, prbs,
        silent_capture_packets=capture_flags.get("silent_packets", 0),
        expected_frames=int(math.ceil(run_seconds * rate)),
        continuous_nonzero=continuous_nonzero)
    print("AUDIO_E2E_METRICS", metrics)
    gate_failures = numeric_failures(metrics)
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
    if gate_failures:
        print("AUDIO_SINGLE_HOST_FAIL", {"reasons": gate_failures})
    else:
        print("AUDIO_SINGLE_HOST_PASS", {
            "profile": "exclusive_pcm16",
            "duration_s": run_seconds,
            "prbs_blocks": metrics.get("prbs_blocks", 0),
        })
    port.close()
    return 1 if gate_failures else 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Live BP1/BP2 audio probe")
    parser.add_argument('--capture-only', action='store_true')
    parser.parse_args()  # --help and invalid options must never start devices
    raise SystemExit(main())
