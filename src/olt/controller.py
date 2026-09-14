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

    def _speech_contexts(self) -> list[dict] | None:
        if not self.cfg.glossary.enabled:
            return None
        phrases = [p.strip() for p in self.cfg.glossary.phrases if p.strip()]
        if not phrases:
            return None
        return [{"phrases": phrases, "boost": float(self.cfg.glossary.boost)}]

    def _activation_ok(self) -> bool:
        """True when incoming/outgoing translation may run for the focused window."""
        if not self.cfg.activation.enabled:
            return True
        want_class = self.cfg.activation.app_class.strip().lower()
        want_title = self.cfg.activation.app_title.strip().lower()
        if not want_class and not want_title:
            return True
        try:
            out = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True, text=True, timeout=2,
            ).stdout
            data = json.loads(out)
        except Exception:
            return True  # can't tell; don't block translation
        cls = (data.get("class") or "").lower()
        title = (data.get("title") or "").lower()
        if want_class and want_class not in cls:
            return False
        if want_title and want_title not in title:
            return False
        return True

    async def outgoing(self, source_lang: str, target: str, stop_event: asyncio.Event) -> None:
        if not self._activation_ok():
            log.info("outgoing blocked: focused window is not an allowed call app")
            return
        card_id = self._next_card("out")
        self.overlay_send(
            {"cmd": "card", "id": card_id, "direction": "out",
             "source": "", "target": "", "state": "draft"}
        )
        cap = audio.Capture("@DEFAULT_SOURCE@")
        stream = await self.asr.connect_stream(
            source_lang, speech_contexts=self._speech_contexts()
        )
        await cap.start()
        log.info("outgoing started (%s→%s)", source_lang, target)
        partial = ""
        pump_task: asyncio.Task | None = None
        finalized = False
        auto_speak_task: asyncio.Task | None = None
        try:
            async def pump():
                while True:
                    chunk = await cap.read_chunk(160)
                    if not chunk:
                        break
                    await stream.send_audio(chunk)

            pump_task = asyncio.create_task(pump())

            async def reader():
                nonlocal partial, finalized
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
                        finalized = True
                        await self._finalize_outgoing(card_id, final, source_lang, target)
                        return

            reader_task = asyncio.create_task(reader())

            # Wait for either the push-to-talk release or a natural endpoint.
            await stop_event.wait()
            log.info("outgoing stop requested; finalizing")
            await cap.stop()
            pump_task.cancel()
            await stream.commit()
            try:
                await asyncio.wait_for(reader_task, timeout=30)
            except asyncio.TimeoutError:
                log.warning("outgoing finalize timed out")
                if partial and not finalized:
                    await self._finalize_outgoing(card_id, partial, source_lang, target)

            if self.cfg.outgoing.auto_speak_after_ms > 0:
                auto_speak_task = asyncio.create_task(
                    self._auto_speak_after(self.cfg.outgoing.auto_speak_after_ms / 1000)
                )
        finally:
            if pump_task and not pump_task.done():
                pump_task.cancel()
            await cap.stop()
            await stream.close()
            if auto_speak_task and not auto_speak_task.done():
                auto_speak_task.cancel()

    async def _auto_speak_after(self, delay_s: float) -> None:
        await asyncio.sleep(delay_s)
        if getattr(self, "_ready_card", None) is not None:
            log.info("auto-speak after %.1fs", delay_s)
            await self.speak_ready()

    async def _finalize_outgoing(
        self, card_id: str, text: str, source_lang: str, target: str
    ) -> None:
        if not text:
            self.overlay_send({"cmd": "clear", "id": card_id})
            return
        try:
            translated = await self.nmt.translate(text, source_lang[:2], target)
        except Exception as exc:
            log.error("outgoing translation failed: %s", exc)
            self.overlay_send(
                {"cmd": "card", "id": card_id, "direction": "out",
                 "source": text, "target": f"[translation failed: {exc}]",
                 "state": "ready"}
            )
            return
        log.info("outgoing translated (%s→%s): %r → %r",
                 source_lang[:2], target, text, translated)
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
        await self._play(wav)
        self._ready_card = None

    async def _play(self, wav: bytes) -> None:
        dest = self.cfg.outgoing.output_destination
        if dest == "speakers":
            await self._play_to_device(wav, self.cfg.outgoing.speakers_sink)
        else:
            await self._play_to_virtual_mic(wav)

    async def _play_to_device(self, wav: bytes, device: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "paplay",
            "--raw",
            f"--rate={self.cfg.tts.sample_rate}",
            "--format=s16le",
            "--channels=1",
            "--device",
            device,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(input=wav)
        if proc.returncode != 0:
            log.error("paplay failed: %s", err.decode(errors="replace"))

    async def _play_to_virtual_mic(self, wav: bytes) -> None:
        # Ensure the virtual mic (null sink + monitor) exists, then play into it.
        self._ensure_virtual_mic()
        await self._play_to_device(wav, self.cfg.outgoing.virtual_mic)

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
        if not self._activation_ok():
            await asyncio.sleep(0.5)
            return
        cap = audio.Capture(self.cfg.incoming.source_device)
        stream = await self.asr.connect_stream(
            self.cfg.incoming.source_language,
            endpointing_ms=self.cfg.incoming.endpointing_ms,
            speech_contexts=self._speech_contexts(),
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
                if self.path.rstrip("/") == "/status":
                    self._reply(HTTPStatus.OK, controller.status())
                else:
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
            self._ptt_stop_event = asyncio.Event()
            self.outgoing_task = asyncio.create_task(
                self.outgoing(source, target, self._ptt_stop_event)
            )
        elif action == "ptt_stop":
            stop_ev = getattr(self, "_ptt_stop_event", None)
            if stop_ev is not None:
                stop_ev.set()
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
        if "incoming_direction" in settings:
            direction = settings["incoming_direction"]
            if direction == "es-en":
                self.cfg.incoming.source_language = "es-ES"
                self.cfg.incoming.target = "en"
            elif direction == "en-es":
                self.cfg.incoming.source_language = "en-US"
                self.cfg.incoming.target = "es"
            log.info("incoming direction set to %s", direction)
        if "glossary" in settings:
            gl = settings["glossary"]
            if isinstance(gl, dict):
                if "enabled" in gl:
                    self.cfg.glossary.enabled = bool(gl["enabled"])
                if "phrases" in gl:
                    self.cfg.glossary.phrases = list(gl["phrases"])
                if "boost" in gl:
                    self.cfg.glossary.boost = float(gl["boost"])
            log.info("glossary updated: enabled=%s phrases=%d",
                     self.cfg.glossary.enabled, len(self.cfg.glossary.phrases))
        if "activation" in settings:
            act = settings["activation"]
            if isinstance(act, dict):
                if "enabled" in act:
                    self.cfg.activation.enabled = bool(act["enabled"])
                if "app_class" in act:
                    self.cfg.activation.app_class = str(act["app_class"])
                if "app_title" in act:
                    self.cfg.activation.app_title = str(act["app_title"])
            log.info("activation updated: enabled=%s class=%r title=%r",
                     self.cfg.activation.enabled,
                     self.cfg.activation.app_class,
                     self.cfg.activation.app_title)
        if "output_destination" in settings:
            dest = settings["output_destination"]
            if dest in ("virtual_mic", "speakers"):
                self.cfg.outgoing.output_destination = dest
                log.info("output destination set to %s", dest)

    def status(self) -> dict:
        incoming_running = self.incoming_task is not None and not self.incoming_task.done()
        return {
            "status": "ok",
            "name": "olt-controller",
            "direction": "en-es" if self.cfg.outgoing.language.startswith("en") else "es-en",
            "auto_speak": self.cfg.outgoing.auto_speak_after_ms > 0,
            "output_destination": self.cfg.outgoing.output_destination,
            "incoming_enabled": incoming_running,
            "incoming_direction": "es-en" if self.cfg.incoming.source_language.startswith("es") else "en-es",
            "glossary": {
                "enabled": self.cfg.glossary.enabled,
                "phrases": self.cfg.glossary.phrases,
                "boost": self.cfg.glossary.boost,
            },
            "activation": {
                "enabled": self.cfg.activation.enabled,
                "app_class": self.cfg.activation.app_class,
                "app_title": self.cfg.activation.app_title,
            },
        }

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
