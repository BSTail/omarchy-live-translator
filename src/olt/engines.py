"""LibreTranslate and Piper clients.

LibreTranslate is a local HTTP service (already running). Piper is spawned per
utterance: text goes in on stdin, a WAV comes back on stdout.
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request

from . import logging
from .config import PathsConfig, TTSConfig

log = logging.get()


class LibreTranslate:
    def __init__(self, paths: PathsConfig):
        self.base = paths.libretranslate_url.rstrip("/")

    async def translate(self, text: str, source: str, target: str) -> str:
        payload = json.dumps({"q": text, "source": source, "target": target}).encode()
        req = urllib.request.Request(
            f"{self.base}/translate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=20)
        except Exception as exc:
            log.error("LibreTranslate request failed: %s", exc)
            raise
        data = json.loads(resp.read().decode())
        return data["translatedText"]


class Piper:
    def __init__(self, paths: PathsConfig, tts_cfg: TTSConfig):
        self.paths = paths
        self.cfg = tts_cfg

    def _voice_path(self, language: str) -> str:
        name = self.cfg.voice_es if language.startswith("es") else self.cfg.voice_en
        return f"{self.cfg.voices_dir}/{name}.onnx"

    async def synthesize(self, text: str, language: str) -> bytes:
        """Return a WAV (PCM16) for the given text."""
        voice = self._voice_path(language)
        cmd = [
            self.paths.piper,
            "--model",
            voice,
            "--output_raw",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(input=text.encode()), timeout=60
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError("Piper synthesis timed out")

        if proc.returncode != 0:
            log.error("piper failed (%s): %s", proc.returncode, err.decode(errors="replace"))
            raise RuntimeError(f"piper exited with {proc.returncode}")
        if not out:
            raise RuntimeError("piper produced no audio")
        return out
