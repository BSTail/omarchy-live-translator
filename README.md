# OmaTranslate

Offline, bidirectional English ↔ Spanish live speech translation for Omarchy Linux,
designed for video and voice calls (a Timekettle-style workflow). Everything runs
locally — no cloud inference, no data leaves the machine.

## Status

**Working end-to-end on the target hardware.** Outgoing push-to-talk translation
(mic → ASR → NMT → overlay → TTS), incoming monitor translation (call audio →
ASR → NMT → overlay), a themed floating overlay, a bar widget with a full
settings panel, and a control CLI are all implemented and validated. Remaining
work is polish, packaging, and optional features (see Roadmap).

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
| ASR (speech → text) | Recognize English and Spanish | NeMo-Speech.cpp, `nemotron-3.5-asr-streaming-0.6b` (q8_0), Vulkan backend | Working |
| NMT (text → text) | Translate en ↔ es | LibreTranslate (already running locally, `en_es`) | Working |
| TTS (text → speech) | Speak the translated text | Piper (Spanish + English voices) | Working |
| Overlay | Bilingual live text review | Hyprland layer-shell / GTK4 window | Working |
| Hotkeys | Push-to-talk + mode toggle | Hyprland bindings (separate from F9) | Working |

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
- [x] Bar icon widget (`bstail.omatranslate`): green/muted status glyph,
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
- [x] Translation history toggle (all cards scrollable vs newest-only).
- [x] Latency telemetry: per-stage timings (ASR/NMT/TTS/playback) logged with
      every translation event.
- [x] Structured JSONL event log (`events.jsonl` in the state dir).
- [x] `olt-ctl diagnostics` latency summary (avg/min/max per stage).
- [x] Clear logs & history button (deletes olt.log*, events.jsonl, clears overlay).
- [x] Fixed incoming pump crash on TTS pause (ConnectionResetError).
- [x] Fixed Gtk-CRITICAL overlay assertions (update entries in place, never
      reparent inside the ScrolledWindow viewport).
- [x] Debug audio capture: timestamped WAVs (`in-*/out-*.wav`) in the state
      debug dir, retention via `debug_keep`, empty captures pruned, panel
      toggle "Record audio captures" (default ON), `clear_logs` also deletes
      captures.
- [x] Fixed incoming state/race bugs: `incoming_enabled` now updates config;
      `_restart_incoming` awaits the old task; unexpected pump errors logged.
- [x] Glossary phrases for child speech: Matt variants, Mattacito/Maxacito,
      Danna, Roblox variants.
- [x] Audio pre-processing before ASR: DC-block high-pass (120 Hz) + gain
      (6 dB); panel toggle "Audio cleanup".
- [x] Configurable ASR chunk size (`chunk_ms`, default 160 ms).
- [x] Keep-screen-awake toggle (suppresses Omarchy screensaver/lock while
      translating; `omarchy-toggle-idle stay-awake`).
- [x] Capture latency fix: `parec --latency-msec 10` (was ~2 s buffered latency).
- [x] Consistent incoming `asr_ms` telemetry (capture-start → ASR-final).
- [x] Bounded debug captures: WAV roll (`debug_roll_sec`) + silence trim
      (`debug_silence_sec`); all-silent captures deleted.
- [x] Fixed incoming realtime WebSocket: correct endpoint (`/v1/realtime`) and
      handshake `readuntil` (was over-reading the first `session.created` frame
      and desyncing the parser — "malformed ASR frame" warnings, no finals).
- [x] ASR accuracy calibration against two verbatim Spanish reference clips
      (`~/Downloads/es-calibrate-{1,2}.{m4a,txt}`). Findings: audio levels are
      healthy (peak −0.5/−3.2 dBFS, RMS ~−25 dBFS); the streaming RNNT model
      hallucinates extra fluent content on long continuous speech (confirmed by
      speech-duration math: 26 s of speech vs ~80 output words ≈ 3.1 wps);
      pre-processing, `rnnt_right_context`, language prompt, punctuation, and
      batching do not improve it. Accuracy on real speech ≈ 6–7/10.

### In progress

- [ ] Package as an Omarchy plugin (installer, config, docs).

### To do (prioritised)

- [ ] **Clipboard translation** (planned): a button + hotkey that translates the
      current clipboard text in both directions (auto-detect en/es), ready to
      paste. Direction follows the configured language pair.
- [x] **Plugin naming**: renamed the plugin/widget to `OmaTranslate`
      (`bstail.omatranslate`). Underlying services/subprocesses/state dirs keep
      the `omarchy-live-translator` naming for now (rename is a later task).
- [ ] **Localized panel**: default panel language follows the OS locale (en /
      es-LatAm for now), user-overridable in settings.
- [ ] **Auto-detect input level (gating)** — user idea, agreed in principle: gate
      incoming translation on a minimum monitor signal level (rolling RMS below
      a slider threshold for a few seconds → don't send audio to ASR). Panel
      gets a "minimum signal level" slider, default low. Threshold should be
      DISABLED while an active call is happening (user confirmed). Design open:
      gate ASR vs. mute overlay vs. both.
- [ ] **Two-tier incoming translation** (user idea, under discussion): a fast
      streaming model renders short (2–3 s) provisional chunks in a lighter
      "draft" style, while a more accurate offline model (e.g. Canary/Parakeet
      TDT) re-translates longer utterance-level chunks and replaces the draft
      text in place (no scrolling duplicates).
- [ ] **Evaluate a higher-accuracy ASR model** to replace/augment Nemotron 3.5:
      candidates researched — Parakeet TDT 0.6B v3 (es WER 3.45% FLEURS,
      official GGUF, offline/buffered), Canary 1B Flash (883M, es WER 2.69%
      MLS), Canary 1B v2 (978M, 25 langs, direct speech translation). None are
      streaming; all need a buffered-chunking path. Next: pull `parakeet-tdt`
      and benchmark against the calibration clips.
- [ ] Analyze recorded daughter WAVs (level/bandwidth/silence) to guide child
      speech improvements.
- [ ] Translation-speed benchmark using recorded WAVs (sentence length and
      settings sweep) — user idea, future task.
- [ ] Word boosting is a no-op until the GGUF carries the embedded SentencePiece
      proto (`asr.tokenizer.spm_model`); reconvert model or find a GGUF that
      includes it. Feasibility verified (2.37 GB .nemo + torch venv).
- [ ] Endpointing / VAD tuning for continuous speech (long unbroken utterances
      delay `.completed` finals; consider shorter EOU threshold or VAD).
- [ ] Latency tuning for live calls (chunk size, streaming config).
- [ ] Phase 2: incoming speech-to-speech into headphones (opt-in).
- [ ] Test on a real video/voice call.
- [ ] Model / voice management (upgrade models, pick languages) — deferred.

## Privacy

No personal data is collected or transmitted. All speech, transcription, and
translation stay on the local machine.
