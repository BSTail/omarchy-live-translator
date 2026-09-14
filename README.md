# Omarchy Live Translator

Offline, bidirectional English ↔ Spanish live speech translation for Omarchy Linux,
designed for video and voice calls (a Timekettle-style workflow). Everything runs
locally — no cloud inference, no data leaves the machine.

## Status

**Phase 1 (research + validation) is complete.** The core recognition engine has
been validated on the target hardware. The plugin itself is not yet written.

## Goal

Two-way spoken translation during live calls:

- **Outgoing:** push-to-talk, speak English, hear/read Spanish, optionally review
  and correct the text before it is spoken.
- **Incoming (Phase 1):** automatically transcribe and translate the remote
  speaker's audio, shown in a floating bilingual overlay.
- **Incoming (Phase 2):** speak the translated English into the user's
  headphones/speakers (opt-in, after on-screen translation works).

Priorities, in order: **accuracy first, speed second, resource efficiency third.**

## Architecture

Two lightweight local speech stacks that coexist without overlap:

- **Voxtype** (unchanged) — the multilingual dictation plugin (F9 / Shift+F9).
- **NeMo** (this plugin) — live call translation (F10+).

This plugin uses **three small engines**: NeMo for ASR, LibreTranslate for
translation, and Piper for TTS.

```
┌─────────────────────────────────────────────────────────────────┐
│                        omarchy-live-translator                   │
│                                                                 │
│  ┌──────────────────┐   ┌──────────────┐   ┌────────────┐       │
│  │  NeMo-Speech.cpp │──▶│ LibreTranslate│──▶│  Piper TTS │       │
│  │  (ASR)           │   │  (en↔es NMT) │   │  (es/en)   │       │
│  └──────────────────┘   └──────────────┘   └────────────┘       │
│        ▲                       │                  │              │
│        │ mic / monitor         │                  ▼              │
│        │                       │            virtual mic /        │
│        │                       ▼            headphones (Phase 2) │
│        │               ┌──────────────┐                          │
│        └───────────────│  Controller  │──▶ overlay               │
│                        └──────────────┘   (Draft/Ready/Spoken)   │
└─────────────────────────────────────────────────────────────────┘
```

| Component | Role | Choice | Status |
|---|---|---|---|
| ASR (speech → text) | Recognize English and Spanish | NeMo-Speech.cpp, `nemotron-3.5-asr-streaming-0.6b` (q8_0), Vulkan backend | Validated |
| NMT (text → text) | Translate en ↔ es | LibreTranslate (already running locally, `en_es`) | Existing |
| TTS (text → speech) | Speak the translated text | Piper (Spanish + English voices) | To integrate |
| Overlay | Bilingual live text review | Hyprland layer-shell / GTK4 window | To build |
| Hotkeys | Push-to-talk + mode toggle | Hyprland bindings (separate from F9) | To build |

### Why NeMo-Speech.cpp

- Runs as its own native C++ process — no conflict with the existing Voxtype daemon.
- Single multilingual model covers both English and Spanish (`es-ES`, `es-US`,
  `auto` detection), with punctuation and capitalization built in.
- Streaming (160 ms chunks) for live-call latency.
- Vulkan backend uses the Intel Arc GPU.
- Also provides TTS (MagpieTTS), so the plugin needs only two engines.

### Why LibreTranslate + Piper (and not Riva Translate 4B / MagpieTTS)

LibreTranslate is already running, tiny, and proven for en↔es. NeMo's Riva
Translate 4B would have to load on Vulkan alongside ASR and is unproven on Arc,
so it is not used.

MagpieTTS was evaluated and rejected for now: it runs sub-realtime (~0.79x) with
no Vulkan benefit on Arc, and crashes when served alongside ASR in the same
process. Piper (20–50x realtime on CPU) is the TTS engine instead.

## Hardware validation

Target machine: Intel Core Ultra 7 258V (AVX2 only), Intel Arc integrated GPU,
Mesa Vulkan driver.

| Backend | Engine | Result |
|---|---|---|
| CPU (AVX2) | Voxtype Whisper `small` | ~0.7× realtime — too slow for live calls |
| Vulkan (Arc) | Voxtype Whisper `small` | ~18× realtime |
| Vulkan (Arc) | NeMo Nemotron 3.5 ASR 0.6B | ~3.2 s for 11 s audio (streaming), accurate Spanish |
| Vulkan (Arc) | NeMo MagpieTTS 357M | ~0.79x realtime, no Vulkan benefit — rejected for live TTS |
| CPU | Piper (`es_ES-davefx-medium`, `en_US-lessac-medium`) | ~0.06x realtime (≈15× faster than realtime) |

### Known issue (NeMo Vulkan)

The NeMo release bundles an older `libstdc++.so.6` that is too old for the Mesa
Vulkan driver, so Vulkan silently falls back to CPU. Workaround:

```bash
LD_PRELOAD=/usr/lib/libstdc++.so.6 nemo-speech transcribe ... --device vulkan:0
```

With the preload, `backend=Vulkan0` activates correctly.

## Design

The controller process and overlay state machine are specified in
[docs/DESIGN.md](docs/DESIGN.md).

## Roadmap

### Completed

- [x] Research: Omarchy plugin model, Timekettle/Palabra.ai/Meet translation, PipeWire loopback.
- [x] Research: local ASR/NMT/TTS options (Whisper.cpp, NeMo, Canary, Piper, Argos, SeamlessStreaming, etc.).
- [x] Validate Voxtype Vulkan variant on Intel Arc (~18× realtime).
- [x] Install NeMo-Speech.cpp (Vulkan) and validate Nemotron 3.5 ASR 0.6B:
  - [x] English transcription (JFK sample) — accurate.
  - [x] Spanish transcription (FLEURS sample) — accurate, with punctuation.
  - [x] Vulkan backend active on Intel Arc.
  - [x] Streaming mode (160 ms chunks) works.
- [x] Install Piper (GitHub release tarball, no AUR) + Spanish/English voices; validate realtime TTS.
- [x] Design the controller process and overlay state machine (`docs/DESIGN.md`).
- [x] Implement the controller (Python, asyncio): config, logging/error reporting,
      NeMo ASR client, LibreTranslate + Piper clients, audio capture, GTK4
      overlay, and control server.
- [x] Wire Hyprland hotkeys (F10/Shift+F10, F11, F12/Shift+F12).
- [x] Install as a systemd user service; outgoing PTT verified (mic → ASR →
      overlay Draft → NMT; F11 → TTS).
- [x] TTS output destination setting (`virtual_mic` vs `speakers`).
- [x] Theme the overlay from the active Omarchy theme (dynamic, no hardcoding;
      see `docs/THEMING.md`).
- [x] Hide overlay until first card / F10.
- [x] Bar icon widget (`bstail.live-translator`): green/muted status glyph,
      left-click start/stop (own services only).
- [x] Bar widget settings panel (left-click opens; Start/Stop moved inside):
  - [x] Outgoing direction toggle (EN→ES / ES→EN).
  - [x] Auto-speak after release (timer).
  - [x] Incoming listen toggle + incoming direction (ES→EN / EN→ES).
  - [x] Glossary / word-boost (NeMo `speech_contexts`) with add/remove chips.
  - [x] Per-app activation (only translate while the call app is focused).
  - [x] Diagnostics button (floating terminal: `olt-ctl diagnostics`).
- [x] Controller `/status` endpoint + `olt-ctl status` / `olt-ctl diagnostics`.
- [x] Incoming translation working end-to-end (monitor capture → ASR → NMT →
      overlay). Requires `--asr.endpointing.enable=true` so the server emits
      `.completed` finals on trailing silence for the continuous monitor stream.
- [x] Speakers/virtual-mic output toggle (speakers for testing, virtual mic for
      calls); auto-pause incoming during TTS playback to break the echo loop.
- [x] F12 `clear` also drops the current incoming card (no stale card lingering).
- [x] Validated multimedia translation: Spanish YouTube audio → English overlay
      (accurate; long unbroken speech delays finals — endpointing tuning pending).
- [x] Multimedia mode toggle (longer EOU window for continuous media speech).
- [x] Unified overlay: all cards in one scrollable panel, newest at top, capped
      to screen height.

### In progress

- [ ] Package as an Omarchy plugin (installer, config, docs).

### To do (prioritised)

- [ ] Package as an Omarchy plugin (installer, config, docs).
- [ ] Endpointing / VAD tuning for continuous speech (long unbroken utterances
      delay `.completed` finals; consider shorter EOU threshold or VAD).
- [ ] Latency tuning for live calls (chunk size, streaming config).
- [ ] Phase 2: incoming speech-to-speech into headphones (opt-in).
- [ ] Test on a real video/voice call.
- [ ] Model / voice management (upgrade models, pick languages) — deferred.

## Privacy

No personal data is collected or transmitted. All speech, transcription, and
translation stay on the local machine.
