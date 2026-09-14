"""Configuration loading for omarchy-live-translator.

Reads a small TOML file. Defaults live here so the shipped config only needs
to override what differs on the user's machine.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATHS = (
    Path.home() / ".config" / "omarchy-live-translator" / "config.toml",
)


@dataclass
class ASRConfig:
    model: str = "nemotron-3.5"
    device: str = "vulkan:0"
    preload_stdcxx: bool = True
    port: int = 8080
    host: str = "127.0.0.1"
    # Two-tier accuracy: a second, offline-only model (Parakeet TDT) that
    # re-transcribes each final utterance for a more accurate replacement.
    offline_model: str = "parakeet-tdt"
    offline_port: int = 8081
    offline_enabled: bool = False


@dataclass
class TTSConfig:
    engine: str = "piper"  # "piper" | "magpie"
    voice_en: str = "en_US-lessac-medium"
    voice_es: str = "es_ES-davefx-medium"
    voices_dir: str = str(Path.home() / ".local" / "share" / "piper" / "voices")
    sample_rate: int = 22050


@dataclass
class OutgoingConfig:
    language: str = "en-US"
    target: str = "es"
    auto_speak_after_ms: int = 0  # 0 = manual (Speak key) required
    output_destination: str = "virtual_mic"  # "virtual_mic" | "speakers"
    virtual_mic: str = "olt-virtual-mic"
    speakers_sink: str = "@DEFAULT_SINK@"


@dataclass
class IncomingConfig:
    enabled: bool = True
    source_language: str = "es-ES"
    target: str = "en"
    source_device: str = "@DEFAULT_MONITOR@"
    endpointing_ms: int = 800
    # Multimedia mode: media audio is continuous, so use a longer EOU window
    # to segment long unbroken speech into cards instead of waiting for a
    # long silence that never comes.
    multimedia: bool = True
    multimedia_endpointing_ms: int = 1600


@dataclass
class GlossaryConfig:
    enabled: bool = False
    phrases: list[str] = field(default_factory=list)
    boost: float = 3.0


@dataclass
class ActivationConfig:
    enabled: bool = False
    app_class: str = ""  # e.g. "zoom", "teams"; empty = any window
    app_title: str = ""  # optional title substring match


@dataclass
class OverlayConfig:
    position: str = "top-right"
    # History mode: "newest" keeps only the latest card visible; "history"
    # keeps every card and lets the panel scroll.
    history: bool = True


@dataclass
class PathsConfig:
    nemo_speech: str = str(Path.home() / ".local" / "bin" / "nemo-speech")
    piper: str = str(Path.home() / ".local" / "bin" / "piper")
    libretranslate_url: str = "http://127.0.0.1:5001"


@dataclass
class Config:
    paths: PathsConfig = field(default_factory=PathsConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    outgoing: OutgoingConfig = field(default_factory=OutgoingConfig)
    incoming: IncomingConfig = field(default_factory=IncomingConfig)
    glossary: GlossaryConfig = field(default_factory=GlossaryConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    control_port: int = 8670
    log_dir: str = str(Path.home() / ".local" / "state" / "omarchy-live-translator")
    log_level: str = "INFO"
    # Testing aid: when enabled, every capture is dumped to a timestamped WAV
    # file in debug_dir so waveforms can be inspected (level, bandwidth,
    # silence). debug_keep bounds how many capture files are retained.
    debug_capture: bool = True
    debug_dir: str = str(Path.home() / ".local" / "state" / "omarchy-live-translator" / "debug")
    debug_keep: int = 20
    # Roll the debug WAV after this many seconds. A monitor capture stays open
    # across idle stretches (the incoming loop only closes it when a
    # translation finalizes), so without a cap a single file grows without
    # bound with near-silence. At 16 kHz mono s16le, 600 s ≈ 19 MB.
    debug_roll_sec: int = 600
    # Maximum seconds of near-silent audio retained in a debug WAV. Silence is
    # useless for waveform analysis and is what makes idle captures balloon.
    # When a session ends (or rolls), leading+trailing low-level audio is
    # trimmed away; if nothing is left the file is deleted.
    debug_silence_sec: int = 60
    # Audio pre-processing before ASR: a DC-blocking high-pass and a fixed
    # gain. Helps quiet/muffled capture (phone calls, child speech).
    preprocess_enable: bool = True
    highpass_hz: float = 120.0
    preamp_db: float = 6.0
    # Audio chunk size sent to the ASR WebSocket per frame (ms). Larger chunks
    # reduce overhead; smaller chunks reduce latency.
    chunk_ms: int = 160
    # Keep the screen awake (suppress Omarchy screensaver/lock) while the
    # translator is running, so live calls aren't interrupted.
    keep_awake: bool = True


def _expand(path: str) -> str:
    return os.path.expanduser(path)


def load(path: str | None = None) -> Config:
    cfg = Config()
    candidates = [Path(p) for p in ([path] if path else DEFAULT_CONFIG_PATHS)]
    found = next((p for p in candidates if p.exists()), None)
    if found is None:
        return cfg

    with open(found, "rb") as fh:
        data = tomllib.load(fh)

    def section(name: str) -> dict:
        return data.get(name, {}) or {}

    paths = section("paths")
    cfg.paths.nemo_speech = _expand(paths.get("nemo_speech", cfg.paths.nemo_speech))
    cfg.paths.piper = _expand(paths.get("piper", cfg.paths.piper))
    cfg.paths.libretranslate_url = paths.get(
        "libretranslate_url", cfg.paths.libretranslate_url
    )

    asr = section("asr")
    cfg.asr.model = asr.get("model", cfg.asr.model)
    cfg.asr.device = asr.get("device", cfg.asr.device)
    cfg.asr.preload_stdcxx = asr.get("preload_stdcxx", cfg.asr.preload_stdcxx)
    cfg.asr.port = asr.get("port", cfg.asr.port)
    cfg.asr.host = asr.get("host", cfg.asr.host)
    cfg.asr.offline_model = asr.get("offline_model", cfg.asr.offline_model)
    cfg.asr.offline_port = asr.get("offline_port", cfg.asr.offline_port)
    cfg.asr.offline_enabled = asr.get("offline_enabled", cfg.asr.offline_enabled)

    tts = section("tts")
    cfg.tts.engine = tts.get("engine", cfg.tts.engine)
    cfg.tts.voice_en = tts.get("voice_en", cfg.tts.voice_en)
    cfg.tts.voice_es = tts.get("voice_es", cfg.tts.voice_es)
    cfg.tts.voices_dir = _expand(tts.get("voices_dir", cfg.tts.voices_dir))
    cfg.tts.sample_rate = tts.get("sample_rate", cfg.tts.sample_rate)

    out = section("outgoing")
    cfg.outgoing.language = out.get("language", cfg.outgoing.language)
    cfg.outgoing.target = out.get("target", cfg.outgoing.target)
    cfg.outgoing.auto_speak_after_ms = out.get(
        "auto_speak_after_ms", cfg.outgoing.auto_speak_after_ms
    )
    cfg.outgoing.output_destination = out.get(
        "output_destination", cfg.outgoing.output_destination
    )
    cfg.outgoing.virtual_mic = out.get("virtual_mic", cfg.outgoing.virtual_mic)
    cfg.outgoing.speakers_sink = out.get("speakers_sink", cfg.outgoing.speakers_sink)

    inc = section("incoming")
    cfg.incoming.enabled = inc.get("enabled", cfg.incoming.enabled)
    cfg.incoming.source_language = inc.get("source_language", cfg.incoming.source_language)
    cfg.incoming.target = inc.get("target", cfg.incoming.target)
    cfg.incoming.source_device = inc.get("source_device", cfg.incoming.source_device)
    cfg.incoming.endpointing_ms = inc.get("endpointing_ms", cfg.incoming.endpointing_ms)
    cfg.incoming.multimedia = inc.get("multimedia", cfg.incoming.multimedia)
    cfg.incoming.multimedia_endpointing_ms = inc.get(
        "multimedia_endpointing_ms", cfg.incoming.multimedia_endpointing_ms
    )

    gl = section("glossary")
    cfg.glossary.enabled = gl.get("enabled", cfg.glossary.enabled)
    cfg.glossary.phrases = list(gl.get("phrases", cfg.glossary.phrases))
    cfg.glossary.boost = gl.get("boost", cfg.glossary.boost)

    act = section("activation")
    cfg.activation.enabled = act.get("enabled", cfg.activation.enabled)
    cfg.activation.app_class = act.get("app_class", cfg.activation.app_class)
    cfg.activation.app_title = act.get("app_title", cfg.activation.app_title)

    ovl = section("overlay")
    cfg.overlay.position = ovl.get("position", cfg.overlay.position)
    cfg.overlay.history = ovl.get("history", cfg.overlay.history)

    cfg.control_port = data.get("control_port", cfg.control_port)
    cfg.log_dir = _expand(data.get("log_dir", cfg.log_dir))
    cfg.log_level = data.get("log_level", cfg.log_level)
    cfg.debug_capture = bool(data.get("debug_capture", cfg.debug_capture))
    cfg.debug_dir = _expand(data.get("debug_dir", cfg.debug_dir))
    cfg.debug_keep = int(data.get("debug_keep", cfg.debug_keep))
    cfg.debug_roll_sec = int(data.get("debug_roll_sec", cfg.debug_roll_sec))
    cfg.debug_silence_sec = int(data.get("debug_silence_sec", cfg.debug_silence_sec))
    cfg.preprocess_enable = bool(data.get("preprocess_enable", cfg.preprocess_enable))
    cfg.highpass_hz = float(data.get("highpass_hz", cfg.highpass_hz))
    cfg.preamp_db = float(data.get("preamp_db", cfg.preamp_db))
    cfg.chunk_ms = int(data.get("chunk_ms", cfg.chunk_ms))
    cfg.keep_awake = bool(data.get("keep_awake", cfg.keep_awake))

    return cfg
