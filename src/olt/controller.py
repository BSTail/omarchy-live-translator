"""Controller: owns the engines, the overlay, and the two pipelines.

- Outgoing: push-to-talk mic capture → ASR → NMT → overlay (Draft/Ready) →
  Piper TTS → virtual mic, gated on an explicit Speak action.
- Incoming: monitor capture → ASR → NMT → overlay (Incoming).

Hotkeys and the overlay talk to the controller over a tiny local HTTP server.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import audio, engines, logging, nemo
from .config import Config

log = logging.get()


class Controller:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.asr = nemo.NemoASR(cfg.paths, cfg.asr)
        self.nmt = engines.LibreTranslate(cfg.paths)
        self.tts = engines.Piper(cfg.paths, cfg.tts)
        self.overlay_proc: asyncio.subprocess.Process | None = None
        self.incoming_task: asyncio.Task | None = None
        self.outgoing_task: asyncio.Task | None = None
        self._overlay_stdin = None
        self._card_seq = 0

    # -- overlay -----------------------------------------------------------

    async def start_overlay(self) -> None:
        env = os.environ.copy()
        # gtk4-layer-shell must be linked before libwayland-client; preloading
        # it is the supported workaround for Python (PyGObject) apps.
        env["LD_PRELOAD"] = "/usr/lib/libgtk4-layer-shell.so"
        self.overlay_proc = await asyncio.create_subprocess_exec(
            "python3",
            "-m",
            "olt.overlay",
            self.cfg.overlay.position,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._overlay_stdin = self.overlay_proc.stdin
        asyncio.create_task(self._watch_overlay_stderr())
        log.info("overlay started (pid %s)", self.overlay_proc.pid)

    async def _watch_overlay_stderr(self) -> None:
        assert self.overlay_proc is not None and self.overlay_proc.stderr is not None
        while True:
            line = await self.overlay_proc.stderr.readline()
            if not line:
                break
            log.info("overlay: %s", line.decode(errors="replace").rstrip())

    def overlay_send(self, msg: dict) -> None:
        if self._overlay_stdin is not None:
            try:
                self._overlay_stdin.write((json.dumps(msg) + "\n").encode())
            except Exception as exc:  # overlay died; don't crash the controller
                log.error("overlay write failed: %s", exc)

    # -- pipelines ---------------------------------------------------------

    def _next_card(self, direction: str) -> str:
        self._card_seq += 1
        return f"{direction}-{self._card_seq}"

    async def outgoing(self, source_lang: str, target: str) -> None:
        card_id = self._next_card("out")
        self.overlay_send(
            {"cmd": "card", "id": card_id, "direction": "out",
             "source": "", "target": "", "state": "draft"}
        )
        cap = audio.Capture("@DEFAULT_SOURCE@")
        stream = await self.asr.connect_stream(source_lang)
        await cap.start()
        log.info("outgoing started (%s→%s)", source_lang, target)
        try:
            partial = ""

            async def pump():
                while True:
                    chunk = await cap.read_chunk(160)
                    if not chunk:
                        break
                    await stream.send_audio(chunk)

            pump_task = asyncio.create_task(pump())
            async for ev in stream.events():
                t = ev.get("type")
                if t == "conversation.item.input_audio_transcription.delta":
                    partial = (partial + ev.get("delta", "")).strip()
                    self.overlay_send(
                        {"cmd": "card", "id": card_id, "direction": "out",
                         "source": partial, "target": "", "state": "draft"}
                    )
                elif t == "conversation.item.input_audio_transcription.completed":
                    final = ev.get("transcript", partial).strip()
                    await stream.commit()
                    pump_task.cancel()
                    await cap.stop()
                    await self._finalize_outgoing(card_id, final, source_lang, target)
                    return
        finally:
            await cap.stop()
            await stream.close()

    async def _finalize_outgoing(
        self, card_id: str, text: str, source_lang: str, target: str
    ) -> None:
        if not text:
            self.overlay_send({"cmd": "clear", "id": card_id})
            return
        try:
            translated = await self.nmt.translate(text, source_lang[:2], target)
        except Exception as exc:
            self.overlay_send(
                {"cmd": "card", "id": card_id, "direction": "out",
                 "source": text, "target": f"[translation failed: {exc}]",
                 "state": "ready"}
            )
            return
        self.overlay_send(
            {"cmd": "card", "id": card_id, "direction": "out",
             "source": text, "target": translated, "state": "ready"}
        )
        # Store the current card for the Speak action.
        self._ready_card = {"id": card_id, "source": text, "target": translated,
                            "target_lang": target}

    async def speak_ready(self) -> None:
        card = getattr(self, "_ready_card", None)
        if card is None:
            log.info("speak requested but no ready card")
            return
        self.overlay_send({"cmd": "card", "id": card["id"], "direction": "out",
                           "source": card["source"], "target": card["target"],
                           "state": "spoken"})
        try:
            wav = await self.tts.synthesize(card["target"], card["target_lang"])
        except Exception as exc:
            log.error("TTS failed: %s", exc)
            self.overlay_send({"cmd": "card", "id": card["id"], "direction": "out",
                               "source": card["source"], "target": card["target"],
                               "state": "ready"})
            return
        await self._play_to_virtual_mic(wav)
        self._ready_card = None

    async def _play_to_virtual_mic(self, wav: bytes) -> None:
        # Ensure the virtual mic (null sink + monitor) exists, then play into it.
        self._ensure_virtual_mic()
        proc = await asyncio.create_subprocess_exec(
            "paplay",
            "--raw",
            f"--rate={self.cfg.tts.sample_rate}",
            "--format=s16le",
            "--channels=1",
            "--device",
            self.cfg.outgoing.virtual_mic,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(input=wav)
        if proc.returncode != 0:
            log.error("paplay failed: %s", err.decode(errors="replace"))

    def _ensure_virtual_mic(self) -> None:
        name = self.cfg.outgoing.virtual_mic
        try:
            out = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except Exception:
            return
        if name not in out:
            subprocess.run(
                ["pactl", "load-module", "module-null-sink",
                 f"sink_name={name}", f"sink_properties=device.description=OLT-Virtual-Mic"],
                capture_output=True, timeout=5,
            )
            log.info("created virtual mic sink %s", name)

    async def incoming(self) -> None:
        if not self.cfg.incoming.enabled:
            return
        log.info("incoming started (monitor %s)", self.cfg.incoming.source_device)
        while True:
            try:
                await self._incoming_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("incoming loop error: %s", exc)
                await asyncio.sleep(2)

    async def _incoming_once(self) -> None:
        cap = audio.Capture(self.cfg.incoming.source_device)
        stream = await self.asr.connect_stream(
            self.cfg.incoming.source_language,
            endpointing_ms=self.cfg.incoming.endpointing_ms,
        )
        await cap.start()
        card_id = self._next_card("in")
        partial = ""
        try:
            async def pump():
                while True:
                    chunk = await cap.read_chunk(160)
                    if not chunk:
                        break
                    await stream.send_audio(chunk)

            pump_task = asyncio.create_task(pump())
            async for ev in stream.events():
                t = ev.get("type")
                if t == "conversation.item.input_audio_transcription.delta":
                    partial = (partial + ev.get("delta", "")).strip()
                    self.overlay_send(
                        {"cmd": "card", "id": card_id, "direction": "in",
                         "source": partial, "target": "", "state": "draft"}
                    )
                elif t == "conversation.item.input_audio_transcription.completed":
                    final = ev.get("transcript", partial).strip()
                    if final:
                        try:
                            translated = await self.nmt.translate(
                                final,
                                self.cfg.incoming.source_language[:2],
                                self.cfg.incoming.target,
                            )
                        except Exception as exc:
                            translated = f"[translation failed: {exc}]"
                        self.overlay_send(
                            {"cmd": "card", "id": card_id, "direction": "in",
                             "source": final, "target": translated,
                             "state": "incoming"}
                        )
                    pump_task.cancel()
                    break
        finally:
            await cap.stop()
            await stream.close()

    # -- control server ----------------------------------------------------

    def start_control_server(self) -> None:
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self._reply(HTTPStatus.OK, {"status": "ok", "name": "olt-controller"})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    msg = json.loads(body or b"{}")
                except json.JSONDecodeError:
                    self._reply(HTTPStatus.BAD_REQUEST, {"error": "bad json"})
                    return
                action = msg.get("action")
                try:
                    asyncio.run_coroutine_threadsafe(
                        controller.dispatch(action, msg), controller.loop
                    )
                except Exception as exc:
                    log.error("dispatch failed: %s", exc)
                self._reply(HTTPStatus.OK, {"ok": True})

            def _reply(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.cfg.control_port), Handler)
        log.info("control server on 127.0.0.1:%s", self.cfg.control_port)
        import threading

        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    async def dispatch(self, action: str, msg: dict) -> None:
        if action == "ptt_start":
            source = msg.get("source_lang", self.cfg.outgoing.language)
            target = msg.get("target", self.cfg.outgoing.target)
            if self.outgoing_task and not self.outgoing_task.done():
                self.outgoing_task.cancel()
            self.outgoing_task = asyncio.create_task(self.outgoing(source, target))
        elif action == "ptt_stop":
            if self.outgoing_task and not self.outgoing_task.done():
                self.outgoing_task.cancel()
        elif action == "speak":
            await self.speak_ready()
        elif action == "clear":
            self.overlay_send({"cmd": "clear_all"})
        elif action == "pause_incoming":
            if self.incoming_task and not self.incoming_task.done():
                self.incoming_task.cancel()
                self.incoming_task = None
                log.info("incoming paused")
            else:
                self.incoming_task = asyncio.create_task(self.incoming())
                log.info("incoming resumed")
        elif action == "set":
            self._apply_settings(msg.get("settings", {}))
        else:
            log.warning("unknown action: %s", action)

    def _apply_settings(self, settings: dict) -> None:
        if "incoming_enabled" in settings:
            want = bool(settings["incoming_enabled"])
            have = self.incoming_task is not None and not self.incoming_task.done()
            if want and not have:
                self.incoming_task = asyncio.create_task(self.incoming())
                log.info("incoming enabled via settings")
            elif not want and have:
                self.incoming_task.cancel()
                self.incoming_task = None
                log.info("incoming disabled via settings")
        if "direction" in settings:
            direction = settings["direction"]
            if direction == "en-es":
                self.cfg.outgoing.language = "en-US"
                self.cfg.outgoing.target = "es"
            elif direction == "es-en":
                self.cfg.outgoing.language = "es-ES"
                self.cfg.outgoing.target = "en"
            log.info("direction set to %s", direction)
        if "auto_speak" in settings:
            self.cfg.outgoing.auto_speak_after_ms = (
                0 if not settings["auto_speak"] else 3000
            )
            log.info("auto_speak set to %s", bool(settings["auto_speak"]))

    # -- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self.asr.start()
        await self.start_overlay()
        self.start_control_server()
        if self.cfg.incoming.enabled:
            self.incoming_task = asyncio.create_task(self.incoming())
        log.info("controller running; press Ctrl-C to stop")
        try:
            await asyncio.Event().wait()
        finally:
            await self.asr.stop()


def main() -> None:
    cfg = Config()
    logging.setup(cfg.log_dir, cfg.log_level)
    logging.install_hooks()
    controller = Controller(cfg)
    try:
        asyncio.run(controller.run())
    except KeyboardInterrupt:
        log.info("stopped by user")


if __name__ == "__main__":
    main()
