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
- **Incoming:** automatically transcribe and translate the remote speaker's audio,
  shown in a floating bilingual overlay.

Priorities, in order: **accuracy first, speed second, resource efficiency third.**

## Architecture

Three small local processes, orchestrated by a thin controller. No second Voxtype
daemon (Voxtype cannot run two daemons side by side; the existing F9 dictation
plugin keeps its own daemon untouched).

```
┌─────────────────────────────────────────────────────────────────┐
│                        omarchy-live-translator                   │
│                                                                 │
│  ┌────────────┐   ┌──────────────┐   ┌────────────┐             │
│  │ NeMo-Speech │──▶│ LibreTranslate│──▶│  Piper TTS │             │
│  │  (ASR)     │   │  (en↔es NMT) │   │  (es/en)   │             │
│  └────────────┘   └──────────────┘   └────────────┘             │
│        ▲                 │                  │                    │
│        │ mic/loopback    │                  ▼                    │
│        │                 │            audio output              │
│        │                 ▼                                       │
│        │         ┌──────────────┐                                │
│        └─────────│  Controller  │──▶ floating bilingual overlay │
│                  └──────────────┘   (Draft / Ready / Spoken)    │
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

### Why LibreTranslate + Piper

Both are lightweight, proven, and already local. This keeps the new plugin to
three small tools rather than forcing one monolithic runtime. Riva Translate 4B
and MagpieTTS are fallback candidates only if LibreTranslate or Piper fall short
in practice.

## Hardware validation

Target machine: Intel Core Ultra 7 258V (AVX2 only), Intel Arc integrated GPU,
Mesa Vulkan driver.

| Backend | Engine | Result |
|---|---|---|
| CPU (AVX2) | Voxtype Whisper `small` | ~0.7× realtime — too slow for live calls |
| Vulkan (Arc) | Voxtype Whisper `small` | ~18× realtime |
| Vulkan (Arc) | NeMo Nemotron 3.5 ASR 0.6B | ~3.2 s for 11 s audio (streaming), accurate Spanish |

### Known issue (NeMo Vulkan)

The NeMo release bundles an older `libstdc++.so.6` that is too old for the Mesa
Vulkan driver, so Vulkan silently falls back to CPU. Workaround:

```bash
LD_PRELOAD=/usr/lib/libstdc++.so.6 nemo-speech transcribe ... --device vulkan:0
```

With the preload, `backend=Vulkan0` activates correctly.

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

### In progress

- [ ] Design the controller process and overlay state machine.

### To do

- [ ] Capture incoming audio via PipeWire loopback (call audio → ASR).
- [ ] Wire outgoing push-to-talk (mic → ASR → NMT → overlay → TTS).
- [ ] Build the floating bilingual overlay with Draft / Ready / Spoken states.
- [ ] Integrate Piper TTS (Spanish + English voices) for outgoing speech.
- [ ] Add Hyprland hotkeys (separate from the F9 dictation plugin).
- [ ] Endpointing / VAD for automatic incoming segmentation.
- [ ] Latency tuning for live calls (chunk size, streaming config).
- [ ] Package as an Omarchy plugin (installer, config, docs).
- [ ] Test on a real video/voice call.

## Privacy

No personal data is collected or transmitted. All speech, transcription, and
translation stay on the local machine.
