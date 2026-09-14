"""Audio capture via PipeWire/PulseAudio using `parec`.

`parec` is used instead of a Python audio library so the plugin has no native
Python audio dependency. We spawn it and read raw PCM16 from stdout.

- outgoing: capture the default microphone while push-to-talk is held.
- incoming: capture a monitor source (the call app's output).
"""

from __future__ import annotations

import asyncio

from . import logging
from .config import Config

log = logging.get()

RATE = 16000
FORMAT = "s16le"
CHANNELS = 1


class Capture:
    def __init__(self, device: str):
        self.device = device
        self.proc: asyncio.subprocess.Process | None = None

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
        log.info("capture started on %s", self.device)

    async def stop(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            log.info("capture stopped on %s", self.device)

    async def read_chunk(self, ms: int = 160) -> bytes:
        """Read `ms` milliseconds of PCM16 (mono 16 kHz)."""
        assert self.proc is not None and self.proc.stdout is not None
        nbytes = int(RATE * 2 * ms / 1000)
        try:
            return await self.proc.stdout.readexactly(nbytes)
        except asyncio.IncompleteReadError as exc:
            return exc.partial


def mic_capture(cfg: Config) -> Capture:
    return Capture("@DEFAULT_SOURCE@")


def monitor_capture(cfg: Config) -> Capture:
    return Capture(cfg.incoming.source_device)
