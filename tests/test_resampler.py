import struct
import pytest
from mac_smusic.resampler import AdaptiveResampler


def test_resampler_identity():
    resampler = AdaptiveResampler(sample_rate=44100, channels=2)
    # 100 frames of dummy PCM
    pcm_in = struct.pack("<200h", *([1000, -1000] * 100))
    pcm_out = resampler.resample_chunk(pcm_in, 1.0)
    assert pcm_out == pcm_in


def test_resampler_speedup():
    resampler = AdaptiveResampler(sample_rate=44100, channels=2)
    # Positive error -> buffer growing -> speed up
    ratio = resampler.update_drift_correction(20.0)
    assert ratio > 1.0

    # Resample with 1.05 ratio
    pcm_in = struct.pack("<200h", *([1000, -1000] * 100))
    pcm_out = resampler.resample_chunk(pcm_in, 1.05)
    # Output should have more frames than input
    assert len(pcm_out) > len(pcm_in)


def test_resampler_slowdown():
    resampler = AdaptiveResampler(sample_rate=44100, channels=2)
    # Negative error -> buffer starving -> slow down
    ratio = resampler.update_drift_correction(-20.0)
    assert ratio < 1.0

    pcm_in = struct.pack("<200h", *([1000, -1000] * 100))
    pcm_out = resampler.resample_chunk(pcm_in, 0.95)
    assert len(pcm_out) < len(pcm_in)
