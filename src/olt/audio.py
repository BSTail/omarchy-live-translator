"""Audio capture via PipeWire/PulseAudio using `parec`.

`parec` is used instead of a Python audio library so the plugin has no native
Python audio dependency. We spawn it and read raw PCM16 from stdout.

- outgoing: capture the default microphone while push-to-talk is held.
- incoming: capture a monitor source (the call app's output).

Debug capture (testing aid): when enabled, each capture session is written to
a timestamped WAV file under `debug_dir`. Files are closed on stop and pruned
to `debug_keep` newest files. The `wave` module only supports read/write modes,
so we never append; every session gets its own file.
"""

from __future__ import annotations

import asyncio
import math
import struct
import time
import wave
from pathlib import Path

from . import logging
from .config import Config
from .preprocess import Preprocessor

log = logging.get()

RATE = 16000
FORMAT = "s16le"
CHANNELS = 1


def _prune_debug_dir(debug_dir: Path, keep: int) -> None:
    """Keep only the newest `keep` capture files in the debug directory."""
    if keep <= 0:
        return
    try:
        files = sorted(
            (p for p in debug_dir.glob("*.wav") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


class Capture:
    def __init__(
        self,
        device: str,
        debug_dir: Path | None = None,
        tag: str = "capture",
        preprocess: Preprocessor | None = None,
    ):
        self.device = device
        self.debug_dir = debug_dir
        self.tag = tag
        self.preprocess = preprocess
        self.proc: asyncio.subprocess.Process | None = None
        self._wav: wave.Wave_write | None = None
        self._wav_path: Path | None = None
        self._wav_frames: int = 0

    async def start(self) -> None:
        cmd = [
            "parec",
            "--device",
            self.device,
            "--rate",
            str(RATE),
            "--format",
            FORMAT,
            "--channels",
            str(CHANNELS),
            "--raw",
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if self.debug_dir is not None:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self._wav_path = self.debug_dir / f"{self.tag}-{stamp}.wav"
            self._wav = wave.open(str(self._wav_path), "wb")
            self._wav.setnchannels(CHANNELS)
            self._wav.setsampwidth(2)
            self._wav.setframerate(RATE)
            self._wav_frames = 0
            log.info("capture dump enabled: %s", self._wav_path)
        log.info("capture started on %s", self.device)

    async def stop(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        if self._wav is not None:
            self._wav.close()
            self._wav = None
            # A capture with no audio is useless for analysis; drop it.
            if self._wav_path is not None and self._wav_frames == 0:
                try:
                    self._wav_path.unlink()
                except OSError:
                    pass
        log.info("capture stopped on %s", self.device)

    async def read_chunk(self, ms: int = 160) -> bytes:
        """Read `ms` milliseconds of PCM16 (mono 16 kHz)."""
        assert self.proc is not None and self.proc.stdout is not None
        nbytes = int(RATE * 2 * ms / 1000)
        try:
            chunk = await self.proc.stdout.readexactly(nbytes)
        except asyncio.IncompleteReadError as exc:
            chunk = exc.partial
        if self.preprocess is not None:
            chunk = self.preprocess.process(chunk)
        if self._wav is not None and chunk:
            self._wav.writeframes(chunk)
            self._wav_frames += len(chunk) // 2
        return chunk


def mic_capture(cfg: Config) -> Capture:
    debug_dir = Path(cfg.debug_dir) if cfg.debug_capture else None
    pp = Preprocessor(cfg.preprocess_enable, cfg.highpass_hz, cfg.preamp_db)
    return Capture("@DEFAULT_SOURCE@", debug_dir, tag="out", preprocess=pp)


def monitor_capture(cfg: Config) -> Capture:
    debug_dir = Path(cfg.debug_dir) if cfg.debug_capture else None
    pp = Preprocessor(cfg.preprocess_enable, cfg.highpass_hz, cfg.preamp_db)
    return Capture(cfg.incoming.source_device, debug_dir, tag="in", preprocess=pp)


def prune_debug_dir(cfg: Config) -> None:
    if cfg.debug_capture:
        _prune_debug_dir(Path(cfg.debug_dir), cfg.debug_keep)
