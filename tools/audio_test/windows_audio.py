"""Small reusable WASAPI capture surface for the two-PC target agent."""

from __future__ import annotations

import math
import time
from ctypes import byref
from collections.abc import Callable

import numpy as np
from comtypes import GUID

import tools.audio_test._bp_e2e_probe as audio
from tools.audio_test.capture_buffer import read_capture_packet
from tools.audio_test.render_buffer import pcm_payload, writable_frames, write_render_packet
from tools.audio_test.waveform import _continuous_signal_chunk


def capture_inventory() -> list[tuple[str, str]]:
    return audio._audio_endpoint_inventory(audio.E_DATA_FLOW_CAPTURE)


def resolve_bp2_capture_endpoint(entries: list[tuple[str, str]]) -> str:
    return audio._select_endpoint(
        entries,
        audio.CAPTURE_ENDPOINT_ENV,
        "BP2 capture endpoint",
        token=audio.BP2_AUDIO_PRODUCT,
    )


def capture_pcm16(
    endpoint_id: str,
    duration_s: float,
    *,
    exclusive: bool = True,
    on_armed: Callable[[dict[str, object]], None] | None = None,
    wait_until: Callable[[], bool] | None = None,
    arm_timeout_s: float = 20.0,
    on_started: Callable[[dict[str, object]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[bytes, dict[str, object]]:
    """Capture BP2 as mono PCM16 and return bytes plus inspectable metadata."""

    client = audio.activate_client(endpoint_id)
    capture_mix = not exclusive
    fmt = (
        audio.WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0)
        if exclusive
        else audio.get_mix_format(client)
    )
    flags = 0 if exclusive else (
        audio.AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | audio.AUDCLNT_STREAMFLAGS_RAW
    )
    share_mode = (
        audio.AUDCLNT_SHAREMODE_EXCLUSIVE
        if exclusive
        else audio.AUDCLNT_SHAREMODE_SHARED
    )
    client.Initialize(
        share_mode,
        flags,
        1_000_000 if exclusive else 10_000_000,
        1_000_000 if exclusive else 0,
        byref(fmt),
        None,
    )
    capture = audio.get_service(
        client,
        GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"),
        audio.IAudioCaptureClient,
    )
    metadata: dict[str, object] = {
        "endpoint_id": endpoint_id,
        "exclusive": exclusive,
        "format": audio.format_desc(fmt),
        "silent_packets": 0,
        "packets": 0,
        "frames": 0,
    }
    captured = bytearray()
    if on_armed is not None:
        on_armed(dict(metadata))
    if wait_until is not None:
        arm_deadline = time.monotonic() + arm_timeout_s
        while not wait_until():
            if should_stop is not None and should_stop():
                raise RuntimeError("capture stopped while armed")
            if time.monotonic() >= arm_deadline:
                raise TimeoutError(f"capture start signal timed out after {arm_timeout_s:.1f}s")
            time.sleep(0.01)

    def drain_packets() -> int:
        drained_frames = 0
        while True:
            next_size = int(capture.GetNextPacketSize())
            if next_size <= 0:
                break
            got = capture.GetBuffer()
            if not isinstance(got, tuple) or len(got) < 3:
                raise RuntimeError(f"unexpected capture GetBuffer result: {got!r}")
            ptr = audio._ptr_value(got[0])
            frames = int(got[1])
            flags_word = int(got[2])
            raw = read_capture_packet(
                ptr,
                frames,
                int(fmt.nBlockAlign),
                silent=bool(flags_word & 0x2),
            )
            if flags_word & 0x2:
                captured.extend(b"\x00\x00" * frames)
                metadata["silent_packets"] = int(metadata["silent_packets"]) + 1
            elif capture_mix:
                channels = int(fmt.nChannels)
                if int(fmt.wFormatTag) != 3 or channels not in (1, 2):
                    raise RuntimeError(
                        f"unsupported capture mix format: {audio.format_desc(fmt)}"
                    )
                samples = np.frombuffer(raw, dtype="<f4").reshape(-1, channels)
                mono = np.clip(
                    np.rint(samples.mean(axis=1) * 32768.0), -32768, 32767
                ).astype("<i2")
                captured.extend(mono.tobytes())
            else:
                captured.extend(raw)
            capture.ReleaseBuffer(frames)
            drained_frames += frames
            metadata["packets"] = int(metadata["packets"]) + 1
        metadata["frames"] = len(captured) // 2
        return drained_frames

    client.Start()
    try:
        if on_started is not None:
            on_started(dict(metadata))
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            if should_stop is not None and should_stop():
                metadata["stopped_early"] = True
                break
            packet_frames = drain_packets()
            if packet_frames == 0:
                time.sleep(0.001)
    finally:
        client.Stop()
    # Stop freezes the endpoint at the requested deadline but does not discard
    # the final completed WASAPI period. Drain it after Stop so a boundary that
    # lands between GetNextPacketSize polls does not lose exactly one packet.
    metadata["post_stop_frames"] = drain_packets()
    samples = np.frombuffer(captured, dtype="<i2")
    metadata.update(
        {
            "frames": int(samples.size),
            "nonzero": int(np.count_nonzero(samples)),
            "peak": int(np.max(np.abs(samples.astype(np.int32)))) if samples.size else 0,
            "rms": (
                float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                if samples.size
                else 0.0
            ),
        }
    )
    return bytes(captured), metadata


def render_pcm16(
    endpoint_id: str,
    signal: np.ndarray,
    duration_s: float,
    *,
    before_start: Callable[[dict[str, object]], None] | None = None,
    on_started: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Render the continuous deterministic signal to BP1 in exclusive mode."""

    client = audio.activate_client(endpoint_id)
    fmt = audio.WAVEFORMATEX(1, 1, 48000, 96000, 2, 16, 0)
    period_100ns = 1_000_000
    client.Initialize(
        audio.AUDCLNT_SHAREMODE_EXCLUSIVE,
        0,
        period_100ns,
        period_100ns,
        byref(fmt),
        None,
    )
    buffer_frames = int(client.GetBufferSize())
    render = audio.get_service(
        client,
        GUID("{F294ACFC-3146-4483-A7BF-ADDCA7C260E2}"),
        audio.IAudioRenderClient,
    )
    rate = 48000
    active_start = rate // 2
    active_end = max(active_start, len(signal) - rate // 2)
    guard_frames = int(math.ceil(period_100ns * rate / 10_000_000))
    quantum_frames = rate // 1000
    source_index = 0

    available = writable_frames(
        buffer_frames,
        int(client.GetCurrentPadding()),
        guard_frames=guard_frames,
        quantum=quantum_frames,
    )
    if available <= 0:
        available = buffer_frames
    initial = _continuous_signal_chunk(
        signal, source_index, available, active_start, active_end
    )
    write_render_packet(
        render,
        pcm_payload(initial, available, float32=False, channels=1),
        available,
        2,
    )
    source_index += available
    metadata: dict[str, object] = {
        "endpoint_id": endpoint_id,
        "exclusive": True,
        "format": audio.format_desc(fmt),
        "buffer_frames": buffer_frames,
        "guard_frames": guard_frames,
        "quantum_frames": quantum_frames,
        "source_frames": source_index,
    }
    if before_start is not None:
        before_start(dict(metadata))
    client.Start()
    try:
        if on_started is not None:
            on_started(dict(metadata))
        deadline = time.monotonic() + duration_s
        while time.monotonic() < deadline:
            available = writable_frames(
                buffer_frames,
                int(client.GetCurrentPadding()),
                guard_frames=guard_frames,
                quantum=quantum_frames,
            )
            if available > 0:
                chunk = _continuous_signal_chunk(
                    signal, source_index, available, active_start, active_end
                )
                write_render_packet(
                    render,
                    pcm_payload(chunk, available, float32=False, channels=1),
                    available,
                    2,
                )
                source_index += available
                metadata["source_frames"] = source_index
            time.sleep(0.001)
    finally:
        client.Stop()
    metadata["elapsed_target_seconds"] = duration_s
    return metadata
