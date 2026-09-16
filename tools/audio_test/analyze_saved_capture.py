"""Recheck saved 48 kHz mono PCM16 without importing USB/serial/WASAPI code."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.audio_test.waveform import analyze_capture, make_signal, numeric_failures
from tools.verification_policy import preflight


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError('expected seconds must be finite and positive')
    return seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path, help='Raw little-endian signed PCM16 mono, 48000 Hz')
    parser.add_argument('--expected-seconds', type=positive_seconds, required=True)
    parser.add_argument('--continuous', action='store_true',
                        help='Also check the entire active recording for gaps; use only for repeated-body runs')
    args = parser.parse_args(argv)
    preflight('saved capture analysis')
    try:
        size = args.capture.stat().st_size
        if size == 0 or size % 2:
            raise ValueError('capture must contain a nonempty whole number of PCM16 samples')
        capture = np.memmap(args.capture, dtype='<i2', mode='r')
        _, preamble, tone, prbs = make_signal(use_environment=False)
        metrics = analyze_capture(capture, preamble, tone, prbs,
                                  expected_frames=math.ceil(args.expected_seconds * 48000),
                                  continuous_nonzero=args.continuous)
    except (OSError, ValueError) as exc:
        print('AUDIO_OFFLINE_FAIL', json.dumps({'error': str(exc)}))
        return 2
    # This marker explicitly does not certify hardware or recreate an E2E run.
    failures = numeric_failures(metrics)
    printable = {key: None if isinstance(value, float) and not math.isfinite(value) else value
                 for key, value in metrics.items()}
    print('AUDIO_OFFLINE_METRICS', json.dumps(printable, sort_keys=True, allow_nan=False))
    print('AUDIO_OFFLINE_FAIL' if failures else 'AUDIO_OFFLINE_PASS',
          json.dumps({'reasons': failures, 'source': 'saved_pcm_only'}))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
