"""NeMo-Speech.cpp ASR client.

Spawns `nemo-speech serve` as a subprocess and talks to it over HTTP and the
realtime transcription WebSocket. The WebSocket client is hand-rolled (RFC
6455, client frames only) so the plugin has no third-party Python dependency.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import time
from pathlib import Path

from . import logging
from .config import ASRConfig, PathsConfig

log = logging.get()


class NemoASR:
    def __init__(self, paths: PathsConfig, asr_cfg: ASRConfig):
        self.paths = paths
        self.cfg = asr_cfg
        self.proc: asyncio.subprocess.Process | None = None
        self._ready = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    def _command(self) -> list[str]:
        cmd = [
            self.paths.nemo_speech,
            "serve",
            "--asr-model",
            self.cfg.model,
            "--device",
            self.cfg.device,
            "--host",
            self.cfg.host,
            "--port",
            str(self.cfg.port),
            "--no-ui",
            "--no-warmup",
        ]
        return cmd

    async def start(self, attempts: int = 3) -> None:
        """Start the server, retrying on the known intermittent warmup crash.

        The NeMo Vulkan backend can abort during warmup with
        `GGML_ASSERT(ne3 == ne13) failed` (SIGABRT). It is nondeterministic,
        so we simply retry a few times.
        """
        env = os.environ.copy()
        if self.cfg.preload_stdcxx:
            env["LD_PRELOAD"] = "/usr/lib/libstdc++.so.6"
        for attempt in range(1, attempts + 1):
            self._ready.clear()
            self.proc = await asyncio.create_subprocess_exec(
                *self._command(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            log.info("started nemo-speech serve (pid %s, attempt %d/%d)",
                     self.proc.pid, attempt, attempts)
            watcher = asyncio.create_task(self._watch_stderr())
            try:
                await self._wait_ready()
                return
            except RuntimeError as exc:
                await watcher
                log.warning("nemo-speech failed to start (attempt %d/%d): %s",
                            attempt, attempts, exc)
                if attempt == attempts:
                    raise
                await asyncio.sleep(2)

    async def _watch_stderr(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            log.info("nemo: %s", text)

    async def _wait_ready(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc is None or self.proc.returncode is not None:
                raise RuntimeError(
                    f"nemo-speech exited early with code {self.proc.returncode if self.proc else '?'}"
                )
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.cfg.host, self.cfg.port), timeout=1.0
                )
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(0.5)
                continue
            writer.close()
            self._ready.set()
            log.info("nemo-speech is ready on %s:%s", self.cfg.host, self.cfg.port)
            return
        raise TimeoutError("nemo-speech did not become ready in time")

    async def stop(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            log.info("stopped nemo-speech serve")

    # -- WebSocket ---------------------------------------------------------

    async def connect_stream(
        self, language: str, sample_rate: int = 16000
    ) -> "ASRStream":
        reader, writer = await asyncio.open_connection(self.cfg.host, self.cfg.port)
        await _ws_handshake(writer, reader, self.cfg.host, self.cfg.port)
        stream = ASRStream(reader, writer)
        await stream.send_json(
            {
                "type": "session.update",
                "session": {"language": language, "sample_rate": sample_rate},
            }
        )
        return stream


class ASRStream:
    """One realtime transcription session over the WebSocket."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self._closed = False

    async def send_audio(self, pcm16: bytes) -> None:
        await self._send_frame(pcm16, opcode=2)

    async def send_json(self, obj) -> None:
        await self._send_frame(json.dumps(obj).encode(), opcode=1)

    async def commit(self) -> None:
        await self.send_json({"type": "input_audio_buffer.commit"})

    async def clear(self) -> None:
        await self.send_json({"type": "input_audio_buffer.clear"})

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._send_frame(b"", opcode=8)
        except OSError:
            pass
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except OSError:
            pass

    async def events(self):
        """Yield parsed JSON text events until the socket closes."""
        while True:
            frame = await self._recv_frame()
            if frame is None:
                return
            opcode, payload = frame
            if opcode == 1:  # text
                yield json.loads(payload.decode())
            elif opcode == 8:  # close
                return

    async def _send_frame(self, payload: bytes, opcode: int) -> None:
        mask = os.urandom(4)
        header = bytearray()
        header.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        self.writer.write(bytes(header) + masked)
        await self.writer.drain()

    async def _recv_frame(self):
        try:
            hdr = await self.reader.readexactly(2)
        except (asyncio.IncompleteReadError, OSError):
            return None
        b1, b2 = hdr[0], hdr[1]
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        ln = b2 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", await self.reader.readexactly(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", await self.reader.readexactly(8))[0]
        mask = await self.reader.readexactly(4) if masked else None
        data = await self.reader.readexactly(ln)
        if mask is not None:
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
        return opcode, data


async def _ws_handshake(
    writer: asyncio.StreamWriter, reader: asyncio.StreamReader, host: str, port: int
) -> None:
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET /v1/audio/transcriptions/realtime HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    writer.write(req.encode())
    await writer.drain()
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = await reader.read(4096)
        if not chunk:
            raise RuntimeError("WebSocket handshake failed: connection closed")
        buf += chunk
    status_line = buf.split(b"\r\n")[0].decode(errors="replace")
    if "101" not in status_line:
        raise RuntimeError(f"WebSocket handshake failed: {status_line}")
