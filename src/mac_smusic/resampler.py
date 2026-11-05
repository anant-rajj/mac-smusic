"""
Adaptive Clock Drift Resampler & Playout Rate Regulator (mac-smusic)
===================================================================
Maintains phase-lock between independent hardware DAC crystals by
micro-adjusting PCM sample rates using linear interpolation.
"""

from __future__ import annotations
import math
import struct
from typing import Tuple


class AdaptiveResampler:
    """
    Sub-millisecond drift regulator.
    Monitors playout queue timing error and modulates the PCM sample stream
    to prevent buffer overflow (accumulating latency) or underflow (clicks).
    """

    def __init__(self, sample_rate: int = 44100, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.kp = 0.000002   # Proportional gain for queue error
        self.ki = 0.0000001  # Integral gain
        self._integral_error = 0.0
        self.current_ratio = 1.0  # 1.0 means exact nominal sample rate

    def update_drift_correction(self, queue_time_error_ms: float) -> float:
        """
        Calculates new resampling ratio based on queue error (in milliseconds).
        Positive error -> buffer growing -> speed up slightly (ratio > 1.0).
        Negative error -> buffer shrinking -> slow down slightly (ratio < 1.0).
        """
        # Clamp error to prevent violent runaway on network drops
        clamped_error = max(-100.0, min(100.0, queue_time_error_ms))

        self._integral_error = max(-500.0, min(500.0, self._integral_error + clamped_error))

        # Output adjustment in PPM (clamped to +/- 500 PPM = 0.05%)
        adjustment = (self.kp * clamped_error) + (self.ki * self._integral_error)
        adjustment = max(-0.0005, min(0.0005, adjustment))

        self.current_ratio = 1.0 + adjustment
        return self.current_ratio

    def resample_chunk(self, pcm_bytes: bytes, ratio: float) -> bytes:
        """
        Linearly resamples 16-bit signed stereo PCM data by ratio.
        If ratio == 1.0, returns identical data with zero CPU overhead.
        """
        if abs(ratio - 1.0) < 1e-6:
            return pcm_bytes

        bytes_per_frame = self.channels * 2  # 16-bit = 2 bytes
        num_frames = len(pcm_bytes) // bytes_per_frame
        if num_frames < 2:
            return pcm_bytes

        # Fast unpack
        fmt = f"<{num_frames * self.channels}h"
        samples = struct.unpack(fmt, pcm_bytes[:num_frames * bytes_per_frame])

        new_num_frames = int(num_frames * ratio)
        if new_num_frames < 2:
            return pcm_bytes

        out_samples = []
        for i in range(new_num_frames):
            orig_pos = i / ratio
            idx0 = int(orig_pos)
            idx1 = min(idx0 + 1, num_frames - 1)
            frac = orig_pos - idx0

            for ch in range(self.channels):
                s0 = samples[idx0 * self.channels + ch]
                s1 = samples[idx1 * self.channels + ch]
                val = int(s0 + frac * (s1 - s0))
                val = max(-32768, min(32767, val))
                out_samples.append(val)

        out_fmt = f"<{len(out_samples)}h"
        return struct.pack(out_fmt, *out_samples)
