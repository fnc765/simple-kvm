"""Pure offline signal generation and analysis for the audio bridge probes."""
import math
import os

import numpy as np


def make_signal(*, use_environment=True):
    rate = 48000
    if use_environment and os.environ.get("BP_E2E_SIMPLE_TONE") == "1":
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

    The search stays local to the first sustained activity transition.  A
    Windows USB audio stream can expose a few stale non-zero samples while the
    endpoint changes alternate settings; treating such a short glitch as the
    preamble would make the rest of the waveform look lost.  A later
    pseudo-random segment can still produce a larger accidental correlation if
    the whole recording is searched at the nominal 48 kHz grid.
    """
    if len(captured) <= len(reference):
        return None, 0.0, 1.0, 0.0
    # Only inspect the startup window: a 60-minute capture can contain hundreds
    # of megabytes, and the preamble is emitted within the first few seconds.
    search_limit = min(len(captured), 131072)
    head = captured[:search_limit].astype(np.int32, copy=False)
    active = np.abs(head) > 1000
    edges = np.diff(np.concatenate(([False], active, [False])).astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    sustained = starts[(ends - starts) >= max(64, min(len(reference) // 4, 128))]
    if len(sustained):
        first = int(sustained[0])
    else:
        activity = np.flatnonzero(active)
        if len(activity) == 0:
            return None, 0.0, 1.0, 0.0
        first = int(activity[0])
    # The first sustained run can begin after an ASRC startup ramp; include
    # the preceding half-millisecond so the true preamble edge is searchable.
    offsets = range(max(0, first - 512), min(len(captured), first + 17))
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


def capture_statistics(samples, chunk_size=48000):
    """Bound temporary memory even for an hour-long memory-mapped capture."""
    squares = 0.0
    peak = nonzero = 0
    for begin in range(0, len(samples), chunk_size):
        chunk = samples[begin:begin + chunk_size].astype(np.float64)
        squares += float(np.dot(chunk, chunk))
        peak = max(peak, int(np.max(np.abs(chunk))))
        nonzero += int(np.count_nonzero(chunk))
    return {
        'captured_frames': int(len(samples)),
        'captured_rms': math.sqrt(squares / len(samples)) if len(samples) else 0.0,
        'captured_peak': peak,
        'nonzero_frames': nonzero,
    }


def continuous_zero_run_count(samples, threshold=100, min_length=48, chunk_size=48000):
    """Like zero_run_count, including runs spanning streaming chunk edges."""
    count = longest = carry = 0
    for begin in range(0, len(samples), chunk_size):
        quiet = np.abs(samples[begin:begin + chunk_size].astype(np.int32)) <= threshold
        edges = np.diff(np.concatenate(([False], quiet, [False])).astype(np.int8))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        if len(starts) and starts[0] == 0:
            starts[0] -= carry
        elif carry:
            count += int(carry > min_length)
            longest = max(longest, carry)
        carry = 0
        lengths = ends - starts
        if len(ends) and ends[-1] == len(quiet):
            carry = int(lengths[-1])
            lengths = lengths[:-1]
        count += int(np.count_nonzero(lengths > min_length))
        if len(lengths):
            longest = max(longest, int(np.max(lengths)))
    return count + int(carry > min_length), max(longest, carry)


def analyze_capture(captured_i16, preamble, tone, prbs, *, silent_capture_packets=None,
                    expected_frames=None, continuous_nonzero=False):
    offset, preamble_corr, preamble_step, preamble_phase = find_offset(
        captured_i16, preamble)
    rate = 48000
    chirp_length = rate // 2
    end_marker_length = 480
    metrics = {
        **capture_statistics(captured_i16),
        "preamble_offset": offset,
        "preamble_corr": preamble_corr,
        "preamble_step": preamble_step,
        "preamble_phase": preamble_phase,
        "silent_capture_packets": silent_capture_packets,
        "continuous_nonzero": bool(continuous_nonzero),
    }
    if expected_frames is not None:
        if expected_frames <= 0:
            raise ValueError('expected_frames must be positive')
        metrics['expected_capture_frames'] = int(expected_frames)
        metrics['capture_duration_complete'] = len(captured_i16) >= expected_frames
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
        if continuous_nonzero:
            runs, longest = continuous_zero_run_count(captured_i16[int(offset):])
            metrics['continuous_unexpected_zero_runs'] = runs
            metrics['continuous_longest_zero_run'] = longest
    return metrics


def numeric_failures(metrics):
    """Keep the existing numeric thresholds; missing/NaN values fail closed."""
    def in_range(key, low, high):
        value = metrics.get(key, math.nan)
        return value is not None and math.isfinite(value) and low <= value <= high

    failures = []
    if metrics.get('preamble_offset') is None or not in_range('preamble_corr', .995, 1.000001):
        failures.append('preamble_correlation')
    if not in_range('tone_frequency_hz', 996.0, 998.0):
        failures.append('tone_frequency')
    if not in_range('tone_gain_db', -.25, .25):
        failures.append('tone_gain')
    for key, reason in [('tone_clipping_samples', 'tone_clipping'),
                        ('unexpected_zero_runs', 'unexpected_zero_run'),
                        ('prbs_capture_alignment_jumps', 'capture_alignment_jump'),
                        ('prbs_source_alignment_jumps', 'source_alignment_jump')]:
        if metrics.get(key) != 0:
            failures.append(reason)
    if not in_range('latency_ms', 0.0, 249.999999):
        failures.append('exclusive_latency')
    if not in_range('prbs_aggregate_corr', .995, 1.000001):
        failures.append('prbs_correlation')
    if not in_range('prbs_p05_corr', .995, 1.000001):
        failures.append('prbs_block_correlation')
    if metrics.get('prbs_alignment_failed', True) or metrics.get('prbs_blocks', 0) != 250:
        failures.append('prbs_coverage')
    if 'expected_capture_frames' in metrics and not metrics.get('capture_duration_complete', False):
        failures.append('capture_duration')
    if metrics.get('continuous_nonzero') and metrics.get('continuous_unexpected_zero_runs') != 0:
        failures.append('continuous_unexpected_zero_run')
    return failures
