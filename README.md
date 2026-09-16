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
│                        omatranslate                             │
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
      produces extra fluent-looking content on long continuous speech (cause
      unverified — see review notes below); pre-processing, `rnnt_right_context`,
      language prompt, punctuation, and batching do not improve it. Accuracy on
      real speech ≈ 6–7/10. Corrected jiwer WER figures live in the To-do list
      (the original difflib numbers were not valid WER).
- [x] **Fixed the incoming "missing-popup" idle-gap bug (upstream NeMo).**
      After a clip finalizes, a sustained run of *full 160 ms zero-PCM silence*
      (what the silence gate used to emit while closed) wedges the streaming RNNT
      server: the next clip decodes nothing (no deltas, no final). Reproduced in
      isolation on both Vulkan and CPU backends → upstream bug, filed as
      [NVIDIA/NeMo-Speech.cpp#48](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/48).
      Workaround shipped (a)+(b)-lite: the gate now goes **wire-silent** when
      closed (bounded trailing silence so EOU still fires, then no frames), and a
      stall watchdog recycles the session if speech flows with no delta. The
      Vulkan `GGML_ASSERT(ne3 == ne13)` abort is the same upstream path (9 cores
      on record). Also added `NemoASR.restart()` so the controller recovers a
      crashed streaming server instead of hot-looping reconnect errors.

### In progress

- [ ] Package as an Omarchy plugin (installer, config, docs).

### To do (prioritised)

- [ ] **Overlay window fixed-height clipping (next bug)** — the overlay
      translation window uses a too-short fixed height and clips the bottom of
      longer translated sentences. Make the window height track its content
      (dynamic/auto-size, capped at screen height with scroll), not a constant.
- [ ] **Fix incoming-loop audio loss (critical, found in review)** — in
      `_incoming_once`, when `.completed` arrives the controller awaits NMT while
      the pump keeps pushing newly-captured audio into a stream whose results are
      never read, then tears down capture and reopens it. Audio spoken during
      translation is silently dropped, and the reopen adds a capture gap. Fix:
      keep capture alive across finalization, give chunks monotonic sample
      offsets, queue finals to background workers, assign bounded audio ranges to
      utterance IDs. Do this before the model work.
- [ ] **Re-score ASR accuracy properly** — replace the `difflib`-based WER with
      jiwer (minimum edit distance), report S/D/I breakdowns + alignments, and
      document normalization (numbers, accent stripping). Keep the verbatim
      reference text authoritative; have a Spanish speaker arbitrate the
      disputed "extra content" passages rather than assuming hallucination.
- [x] **Re-scored with jiwer** (`tools/score_wer.py`, jiwer 4.0.0, default
      lowercase + punctuation-strip normalization, digits kept as-is). Corrected
      WER (the earlier difflib numbers were NOT valid WER):
      parakeet-tdt 76.3% / 47.0% (clip 1/2), nemotron-3.5 93.2% / 60.6%.
      Breakdowns (S/D/I): parakeet 18/0/27 and 12/0/19; nemotron 21/1/33 and
      21/1/18. Insertions dominate — both models add content relative to the
      verbatim reference. Parakeet is still clearly better, but the absolute
      numbers are worse than the difflib figures implied; the reference text
      remains authoritative and the disputed extra content needs a Spanish
      speaker to arbitrate.
- [ ] **Head-to-head architecture comparison** (replaces the "confirmed two-tier
      plan"): (a) buffered/chunked Parakeet-only vs (b) Nemotron draft →
      Parakeet refine. Measure draft latency, final latency, and text stability
      on short utterances and uninterrupted speech. NVIDIA's Parakeet model card
      documents buffered streaming via NeMo; the installed C++ `serve` runtime
      rejects Parakeet's native streaming path, but buffered chunking is a
      distinct path that has not been benchmarked. Decide on evidence, not on
      the earlier unverified "offline-only" conclusion.
- [x] **Head-to-head latency data collected** (2026-09-14, Vulkan q8_0):
      - Parakeet via a persistent `serve` process (`POST /v1/audio/transcriptions`)
        is fast: 2 s chunk ≈ 0.29 s, 3 s ≈ 0.12 s, 5 s ≈ 0.14 s, 8 s ≈ 0.18 s
        (steady-state; first request pays ~0.6 s warmup). Full 36 s clip 1
        transcribes in ~0.74 s, clip 2 (~30 s) in ~0.58 s.
      - The C++ runtime's `streaming_recognize` path is genuinely unavailable
        for Parakeet: `make_runner()` throws "this transducer encoder is
        offline-only" for any non-CTC head without `supports_cache_streaming()`
        (src/asr/recognizer.cpp:209-214). So buffered file transcription is the
        only Parakeet path in this runtime.
      - Implication: a two-tier design can keep Nemotron streaming for drafts
        and send each final utterance's audio to a persistent Parakeet server
        for an accurate re-transcription with ~0.1-0.3 s added latency. A
        Parakeet-only "streaming" path is not possible in this runtime; NeMo
        buffered chunking would require a separate Python/torch stack.
      - Remaining before implementation: measure end-to-end draft→final latency
        and text stability on a real utterance stream (not just file timing).
- [x] **Two-tier incoming translation implemented** (2026-09-14):
      - `ASRConfig.offline_model/offline_port/offline_enabled` + a second
        `nemo-speech serve` process managed by `NemoASR.start_offline()`.
      - Incoming capture keeps a ~20 s ring of raw PCM16; on each `.completed`
        the server's `audio_processed` (stream-global seconds) delta bounds the
        utterance, and that audio is POSTed to Parakeet via
        `NemoASR.transcribe_offline()` (multipart `/v1/audio/transcriptions`).
      - Refinement runs in a background task: if Parakeet returns different text,
        NMT re-translates it and the card is updated IN PLACE (same card id), so
        no scrolling duplicates. Generation counter drops stale refinements on
        clear/pause/restart. Streams and rapid toggles: `_snapshot_utterance_audio`
        skips sub-300ms utterances (a near-empty WAV makes Parakeet return 500).
      - Validated live (two real clip plays): cards refine in place; Parakeet
        transcripts are more complete than the streaming Nemotron draft and the
        replacement text re-translates correctly. **Default on** (panel toggle
        "Two-tier accuracy" turns it off). NOTE: the refine source for clip 2
        included a Parakeet misrecognition ("caballete"→"caballo"/"horse") —
        Parakeet is better but not perfect; the two-tier path is plumbing,
        accuracy is model-bound.
- [ ] **Clipboard translation** (planned): a button + hotkey that translates the
      current clipboard text in both directions (auto-detect en/es), ready to
      paste. Direction follows the configured language pair.
- [x] **Plugin naming**: renamed the plugin/widget to `OmaTranslate`
      (`bstail.omatranslate`). The GitHub repo, systemd service, and
      state/config/share dirs were also renamed to `omatranslate` (2026-09-16).
      The internal `olt` shorthand (olt-ctl, olt.log, olt-overlay) is unchanged.
- [ ] **Localized panel**: default panel language follows the OS locale (en /
      es-LatAm for now), user-overridable in settings.
- [ ] **Auto-detect input level (gating)** — user idea, agreed in principle: gate
      incoming translation on a minimum monitor signal level (rolling RMS below
      a slider threshold for a few seconds → don't send audio to ASR). Panel
      gets a "minimum signal level" slider, default low. Threshold should be
      DISABLED while an active call is happening (user confirmed). Design open:
      gate ASR vs. mute overlay vs. both. Gating must not starve ASR of trailing
      silence (or endpointing never completes); call detection needs explicit
      design (`media.role=Communication` is a hint, plus a manual override).
- [ ] **Two-tier incoming translation** (user idea): DONE — see the [x] item
      below (implemented + validated, default on). NOTE: current drafts show
      source-only (empty target) — translated provisional drafts are not yet
      implemented; re-run NMT is done when Parakeet revises the source.
- [x] **Evaluate a higher-accuracy ASR model** — `parakeet-tdt` (0.6B v3) pulled
      and timed against the two calibration clips (Vulkan, q8_0). Corrected
      jiwer WER: parakeet 76.3%/47.0% vs nemotron 93.2%/60.6% (see above); 15 s
      file transcription ~1.1 s vs ~4.3 s (both including subprocess startup).
      CAVEATS from review: the "offline-only" conclusion is too broad (NVIDIA
      documents buffered streaming for Parakeet via NeMo), and the two-model
      plan is not yet justified — needs the head-to-head above. Canary 1B Flash /
      v2 remain candidates for later.
- [ ] Analyze recorded daughter WAVs (level/bandwidth/silence) to guide child
      speech improvements.
- [ ] Translation-speed benchmark using recorded WAVs (sentence length and
      settings sweep) — user idea, future task.
- [ ] Word boosting is a no-op until the GGUF carries the embedded SentencePiece
      proto (`asr.tokenizer.spm_model`); reconvert model or find a GGUF that
      includes it. Feasibility verified (2.37 GB .nemo + torch venv).
- [ ] Endpointing / VAD tuning for continuous speech (long unbroken utterances
      delay `.completed` finals; consider shorter EOU threshold or VAD). Note:
      raising the EOU window to 1600 ms only waits longer for silence — it does
      not impose a maximum utterance length; continuous speech needs an explicit
      duration cap + context-preserving split.
- [ ] Latency tuning for live calls (chunk size, streaming config).
- [ ] Phase 2: incoming speech-to-speech into headphones (opt-in).
- [ ] Test on a real video/voice call.
- [ ] Model / voice management (upgrade models, pick languages) — deferred.

### Review findings (independent agent, 2026-09-14)

An external review identified the following. Items 1–4 are being addressed now.

1. **Incoming audio loss around finalization (bug).** See the fix above.
2. **WER methodology.** `difflib.SequenceMatcher` ≠ minimum edit distance;
   recalculate with jiwer and report S/D/I. Two clips are smoke tests, not proof.
3. **"Parakeet offline-only" too broad.** Buffered/chunked streaming exists in
   NeMo; benchmark it before committing to two resident models.
4. **Drafts are not translated drafts.** Partials render source-only; add
   translated snapshots with revision IDs, and re-run NMT when the source is
   revised.
5. **Overlay ordering/cancellation.** Separate creation order from revision
   order; preserve scroll during refinement; tag jobs with a generation ID so
   clear/pause/direction/stop invalidate stale results.
6. **Resource claims unverified.** File-transcription speed ≠ live latency; two
   resident models ≠ double GPU memory; test concurrency under real load.
7. **Gating/headphones nuances.** Gating can starve endpointing; headphones stop
   acoustic (not digital) feedback — TTS into the captured sink's monitor still
   loops.
8. **Misc.** Fixed +6 dB preamp can clip; debug WAVs are post-processing (keep
   raw for comparison); custom WS client lacks ping/pong/fragmentation; installed
   build 404s on the documented `/v1/audio/transcriptions/realtime` (version
   pinning).

## Privacy

No personal data is collected or transmitted. All speech, transcription, and
translation stay on the local machine.
