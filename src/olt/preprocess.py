"""Lightweight PCM16 pre-processing applied before ASR.

A one-pole high-pass (DC blocker) removes low-frequency rumble and a fixed
gain lifts quiet capture. State is kept across chunks so the filter is
continuous over a stream. No third-party dependency: pure Python on raw
PCM16 frames.

The pipeline is: high-pass -> gain -> clamp to int16.
"""

from __future__ import annotations

import math
import struct

from . import logging

log = logging.get()

MAX16 = 32767
MIN16 = -32768


class Preprocessor:
    def __init__(self, enabled: bool = True, highpass_hz: float = 120.0, gain_db: float = 6.0):
        self.enabled = enabled
        self.highpass_hz = highpass_hz
        self.gain_db = gain_db
        self._gain = 10.0 ** (gain_db / 20.0) if enabled else 1.0
        # One-pole high-pass coefficient.
        self._alpha = self._highpass_alpha(highpass_hz) if enabled else 0.0
        self._prev_in = 0.0
        self._prev_out = 0.0

    def _highpass_alpha(self, cutoff_hz: float) -> float:
        # alpha = RC / (RC + dt), RC = 1/(2*pi*fc), dt = 1/RATE.
        dt = 1.0 / 16000.0
        rc = 1.0 / (2.0 * math.pi * max(cutoff_hz, 1.0))
        return rc / (rc + dt)

    def process(self, chunk: bytes) -> bytes:
        if not self.enabled or not chunk:
            return chunk
        n = len(chunk) // 2
        samples = struct.unpack(f"<{n}h", chunk)
        out = bytearray(len(chunk))
        for i, s in enumerate(samples):
            x = float(s)
            y = self._alpha * (self._prev_out + x - self._prev_in)
            self._prev_in = x
            self._prev_out = y
            v = y * self._gain
            if v > MAX16:
                v = MAX16
            elif v < MIN16:
                v = MIN16
            out[i * 2:i * 2 + 2] = struct.pack("<h", int(v))
        return bytes(out)
