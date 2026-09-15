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

    async def _post(self, endpoint: str, payload: dict, timeout: float = 20.0) -> dict:
        """POST JSON to LibreTranslate with one retry on transient failure.

        A single slow request (large text, a briefly busy service) should not
        fail the whole translation, so we retry once after a short backoff.
        """
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base}/{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                resp = await asyncio.to_thread(
                    urllib.request.urlopen, req, timeout=timeout
                )
                return json.loads(resp.read().decode())
            except Exception as exc:
                last_exc = exc
                if attempt == 1:
                    log.warning("LibreTranslate %s failed (attempt 1): %s; retrying",
                                endpoint, exc)
                    await asyncio.sleep(0.5)
        log.error("LibreTranslate %s failed: %s", endpoint, last_exc)
        raise last_exc

    async def translate(self, text: str, source: str, target: str) -> str:
        data = await self._post(
            "translate", {"q": text, "source": source, "target": target}
        )
        return data["translatedText"]

    async def detect(self, text: str) -> str:
        """Return the detected language code (e.g. "en", "es"), or "" on failure."""
        try:
            data = await self._post("detect", {"q": text})
        except Exception:
            return ""
        if not data:
            return ""
        return data[0].get("language", "")


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
