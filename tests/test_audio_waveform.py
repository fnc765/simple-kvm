"""Offline waveform gates and CLI regressions; no device modules are loaded."""
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tools.audio_test import analyze_saved_capture as cli
from tools.audio_test.waveform import (
    analyze_capture, capture_statistics, continuous_zero_run_count,
    find_rate_corrected_blocks, make_signal, numeric_failures, zero_run_count,
)


@pytest.fixture(scope='module')
def valid_metrics():
    signal, preamble, tone, prbs = make_signal(use_environment=False)
    # Same linear ASRC model as the receiver, with clock drift and phase offset.
    positions = np.arange(len(signal)) * .9998 + .37
    resampled = np.rint(np.interp(positions, np.arange(len(signal)), signal)).astype('<i2')
    captured = np.pad(resampled, (672, 0))
    return analyze_capture(captured, preamble, tone, prbs, expected_frames=len(captured))


def test_clean_asrc_capture_passes_unchanged_numeric_thresholds(valid_metrics):
    assert valid_metrics['silent_capture_packets'] is None  # raw PCM has no packet flags
    assert valid_metrics['preamble_corr'] >= .995
    assert valid_metrics['prbs_p05_corr'] >= .995
    assert valid_metrics['prbs_blocks'] == 250
    assert numeric_failures(valid_metrics) == []


@pytest.mark.parametrize('key', ['preamble_corr', 'tone_frequency_hz', 'tone_gain_db',
                                 'latency_ms', 'prbs_aggregate_corr', 'prbs_p05_corr'])
@pytest.mark.parametrize('bad', [math.nan, math.inf, None])
def test_numeric_gate_rejects_nonfinite_and_missing_values(valid_metrics, key, bad):
    metrics = dict(valid_metrics, **{key: bad})
    assert numeric_failures(metrics)
    del metrics[key]
    assert numeric_failures(metrics)


def test_numeric_gate_does_not_hide_saved_failure_or_incomplete_coverage(valid_metrics):
    assert 'prbs_block_correlation' in numeric_failures(dict(valid_metrics, prbs_p05_corr=.983128746))
    assert 'prbs_coverage' in numeric_failures(dict(valid_metrics, prbs_blocks=249))
    assert 'capture_duration' in numeric_failures(dict(valid_metrics, capture_duration_complete=False))
    assert 'continuous_unexpected_zero_run' in numeric_failures(dict(
        valid_metrics, continuous_nonzero=True, continuous_unexpected_zero_runs=1))
    assert numeric_failures({})


@pytest.mark.parametrize('step', [.999, 1.0, 1.001])
def test_prbs_tracker_handles_clean_clock_drift(step):
    rng = np.random.default_rng(27)
    reference = rng.integers(-12000, 12000, 384 * 24, dtype=np.int16)
    position = np.arange(math.ceil(len(reference) / step)) * step + .35
    signal = np.rint(np.interp(position, np.arange(len(reference)), reference,
                              left=0, right=0)).astype(np.int16)
    capture = np.pad(signal, (512, 512))
    metrics = find_rate_corrected_blocks(capture, reference, 512, step)
    assert metrics['blocks'] == 24
    assert metrics['p05_corr'] >= .995
    assert not metrics['capture_alignment_jumps']
    assert not metrics['source_alignment_jumps']


@pytest.mark.parametrize('fault', ['drop', 'duplicate', 'future_pcm', 'truncate'])
def test_prbs_tracker_rejects_corruption_without_relaxing_alignment(fault):
    rng = np.random.default_rng(27)
    reference = rng.integers(-12000, 12000, 384 * 24, dtype=np.int16)
    broken = reference.copy()
    if fault == 'drop':
        broken = np.delete(broken, np.s_[4500:4548])
    elif fault == 'duplicate':
        broken = np.insert(broken, 4500, broken[4452:4500])
    elif fault == 'future_pcm':
        for start in range(700, 4700, 144):
            broken[start:start + 6] = reference[start + 4096:start + 4102]
    else:
        broken = broken[:4608]
    capture = np.pad(broken, (512, 0))
    metrics = find_rate_corrected_blocks(capture, reference, 512)
    assert (metrics['blocks'] < 24 or metrics['p05_corr'] < .995
            or metrics['capture_alignment_jumps'] or metrics['source_alignment_jumps'])


@pytest.mark.parametrize('chunk_size', [1, 7, 48, 97, 48000])
def test_streaming_zero_runs_match_batch_at_chunk_edges(chunk_size):
    samples = np.full(530, 8200, dtype=np.int16)
    samples[:56] = 0
    samples[82:160] = -100
    samples[253:302] = 100
    samples[397:] = 0
    assert continuous_zero_run_count(samples, chunk_size=chunk_size) == zero_run_count(samples)
    assert continuous_zero_run_count(np.array([], dtype=np.int16), chunk_size=chunk_size) == (0, 0)


def test_continuous_gate_checks_silence_after_first_test_body():
    capture = np.full(48000 * 12, 8200, dtype=np.int16)
    capture[48000 * 10 - 12:48000 * 10 + 80] = 0
    assert zero_run_count(capture[:48000 * 6])[0] == 0  # former analysis extent
    assert continuous_zero_run_count(capture) == (1, 92)


def test_capture_statistics_handles_int16_min_and_streaming_memory():
    samples = np.array([-32768, 0, 100, -100], dtype=np.int16)
    stats = capture_statistics(samples, chunk_size=1)
    assert stats['captured_peak'] == 32768
    assert stats['nonzero_frames'] == 3
    assert stats['captured_rms'] == pytest.approx(np.sqrt(np.mean(samples.astype(float) ** 2)))
    assert capture_statistics(samples[:0])['captured_frames'] == 0


def test_offline_reference_ignores_live_debug_environment(monkeypatch):
    original = make_signal(use_environment=False)[0]
    monkeypatch.setenv('BP_E2E_SIMPLE_TONE', '1')
    monkeypatch.setenv('BP_E2E_TONE_SECONDS', '1')
    np.testing.assert_array_equal(make_signal(use_environment=False)[0], original)


@pytest.mark.parametrize('passed', [False, True])
def test_offline_cli_exit_status_and_distinct_marker(tmp_path, monkeypatch, capsys, valid_metrics, passed):
    capture_path = tmp_path / 'capture.raw'
    capture_path.write_bytes(b'\x00\x00')
    metrics = dict(valid_metrics)
    if not passed:
        metrics['prbs_p05_corr'] = .983128746
    monkeypatch.setattr(cli, 'analyze_capture', lambda *args, **kwargs: metrics)
    assert cli.main([str(capture_path), '--expected-seconds', '10']) == (0 if passed else 1)
    output = capsys.readouterr().out
    assert ('AUDIO_OFFLINE_PASS' if passed else 'AUDIO_OFFLINE_FAIL') in output
    assert 'AUDIO_SINGLE_HOST_PASS' not in output
    assert 'AUDIO_E2E_PASS' not in output


@pytest.mark.parametrize('data', [b'', b'\x00'])
def test_offline_cli_rejects_invalid_raw_without_analysis(tmp_path, data, capsys):
    path = tmp_path / 'invalid.raw'
    path.write_bytes(data)
    assert cli.main([str(path), '--expected-seconds', '10']) == 2
    assert 'AUDIO_OFFLINE_FAIL' in capsys.readouterr().out


@pytest.mark.parametrize('seconds', ['0', '-1', 'nan', 'inf'])
def test_offline_cli_rejects_invalid_duration(seconds):
    with pytest.raises(SystemExit) as error:
        cli.main(['unused.raw', '--expected-seconds', seconds])
    assert error.value.code == 2


def test_importing_offline_analyzer_does_not_import_device_modules():
    result = subprocess.run([
        sys.executable, '-c',
        "import sys; import tools.audio_test.analyze_saved_capture; "
        "assert not any(x in sys.modules for x in ('serial', 'comtypes', 'hid', "
        "'tools.audio_test._bp_e2e_probe'))",
    ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
