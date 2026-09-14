# Session Memory — omarchy-live-translator (plugin name: OmaTranslate)

Paste this into a fresh session to restore context.

## Project
Offline bilingual (en↔es) live speech-translation plugin for Omarchy Linux
(Timekettle-style). Coexists with the existing Voxtype dictation plugin
(untouched). Priorities: accuracy > speed > lightweight. Everything local.

## Stack
- ASR: NeMo-Speech.cpp (Vulkan, Intel Arc), model `nemotron-3.5-asr-streaming-0.6b`.
- NMT: LibreTranslate on port 5001 (`en,es`); existing dictation plugin uses 5000.
- TTS: Piper (es_ES-davefx-medium, en_US-lessac-medium).
- Controller: Python asyncio; overlay is GTK4 layer-shell; control server on 127.0.0.1:8670.

## Key workarounds (do NOT regress)
- NeMo: `LD_PRELOAD=/usr/lib/libstdc++.so.6` for Vulkan + `--no-warmup`
  (avoids intermittent `GGML_ASSERT(ne3 == ne13)` SIGABRT).
- NeMo serve MUST run with `--asr.endpointing.enable=true`, else the incoming
  monitor stream never emits `.completed` finals (no translation cards).
- Realtime WebSocket endpoint is `/v1/realtime` (NOT
  `/v1/audio/transcriptions/realtime`, which 404s). The WS handshake must use
  `reader.readuntil(b"\r\n\r\n")` — reading with `read(4096)` over-reads the
  first `session.created` frame and desyncs the frame parser ("malformed ASR
  frame" warnings, no finals).
- Overlay: gtk4-layer-shell needs `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`.
- Overlay cards must be UPDATED IN PLACE (mutate label text/CSS classes), never
  remove+re-add inside the ScrolledWindow viewport (causes Gtk-CRITICAL
  `gtk_widget_is_ancestor` assertions / SIGABRT).
- Incoming `pump()` must swallow ConnectionResetError/OSError on TTS pause.
- Audio capture MUST use `parec` with `--latency-msec 10`. The default fragsize
  (64000 B = 2 s) adds ~2 s buffered latency. Do NOT switch to `pw-cat`:
  on this PipeWire setup `pw-cat --target @DEFAULT_MONITOR@` / `<monitor-name>`
  silently connects to the MIC source (Source 60), not the monitor (Source 58);
  only the numeric serial works, which is not stable. `parec` resolves
  @DEFAULT_MONITOR@ / @DEFAULT_SOURCE@ correctly.
- Debug WAVs: a capture file only contains audio for the session it covers; a
  translation finalizes the session, closes that WAV, and opens a NEW one. So
  the newest WAV is often silent (post-audio). Look at the WAV whose timestamp
  brackets the event, not the newest one. Retention (`debug_keep=20`) prunes
  older captures.
- Debug captures now bounded: `debug_roll_sec` (600) rolls the WAV after N
  seconds and `debug_silence_sec` (60) trims leading/trailing silence on close
  (all-silent files are deleted). This stops idle monitor sessions ballooning
  into hundreds of MB of near-silence.
- Startup prune: `prune_debug_dir_startup` deletes all-silent debug WAVs
  before retention runs, so idle churn can't evict the few speech-bearing
  captures. (The daughter's 06:04–06:08 captures were lost to retention before
  this existed; re-record to analyze her speech.)

## Hotkeys (Hyprland)
- F10 / Shift+F10: outgoing PTT en→es / es→en.
- F11: speak translated text. F12: clear overlay (+ drops incoming card).
- Shift+F12: pause/resume incoming.

## Current state (all working)
- Outgoing PTT → overlay Draft/Ready → F11 TTS (speakers or virtual-mic toggle).
- Incoming translation (monitor capture, isolated from mic) → bilingual cards.
- Multimedia mode toggle (longer EOU 1600ms for continuous media speech).
- Unified overlay: single themed panel, newest-at-top, grows to screen height,
  scrollable; history toggle (all vs newest-only).
- Settings panel toggles: direction, auto-speak, incoming enable/direction,
  multimedia, history, glossary (word-boost), per-app activation, output,
  diagnostics, clear-logs, Record audio captures, Audio cleanup, Keep screen
  awake.
- Latency telemetry + JSONL event log (`events.jsonl` in state dir);
  `olt-ctl diagnostics` shows avg/min/max per stage.
- Panel toggles live under the DIAGNOSTICS section (bottom of panel). If the
  user can't see new toggles, run `omarchy-shell shell rescanPlugins` to force
  a full plugin reload (hot-reload sometimes misses additions).
- Known harmless warning: `Panel.qml:146 Parameter "exitCode" is not declared`
  (deprecation). User said to ignore it.

## Paths
- Deployed source: `~/.local/share/omarchy-live-translator/src/olt/`
- Config: `~/.config/omarchy-live-translator/config.toml`
- Widget: `~/.config/omarchy/plugins/bstail.omatranslate/` (manifest.json, BarWidget.qml, Panel.qml)
- systemd user units: `omarchy-live-translator.service`, `libretranslate-live.service`
- CLI: `~/.local/bin/olt-ctl` (ptt_start/ptt_stop/speak/clear/clear_logs/pause_incoming/status/diagnostics)
- Logs/events: `~/.local/state/omarchy-live-translator/` (olt.log, events.jsonl)
- Git repo (source of truth): `BSTail/omarchy-live-translator`, local clone `/tmp/opencode/olt`

## Last completed tasks
1. Capture latency fix: `parec --latency-msec 10` (was ~2 s buffered latency
   from the default 64000-byte fragsize). Verified: tone captured at full
   amplitude with no noise floor, starting at 0.0 s.
2. Debug-capture cleanup: `prune_debug_captures` also removes zero-byte WAVs
   left by crashed/upgraded captures.
3. Telemetry consistency: incoming `asr_ms` now measures capture-start →
   ASR-final (same definition as outgoing), not first-delta → final.
4. Multimedia toggle description clarified in Panel.qml.
5. Keep-screen-awake toggle (default ON): controller runs
   `omarchy-toggle-idle stay-awake`/`allow-idle` to suppress the Omarchy
   screensaver/lock while translating. Panel toggle "Keep screen awake".
6. Audio pre-processing before ASR: `preprocess.py` (DC-block high-pass
   120 Hz + 6 dB gain). Config `preprocess_enable`/`highpass_hz`/`preamp_db`;
   panel toggle "Audio cleanup".
7. `chunk_ms` config (default 160) for ASR WebSocket frame size.
8. Debug audio capture: timestamped WAVs (`in-*/out-*.wav`), retention
   `debug_keep` (20), empty captures pruned, panel toggle "Record audio
   captures" (default ON), `clear_logs` also deletes captures.
9. Fixed incoming state/race bugs: `incoming_enabled` updates config;
   `_restart_incoming` is async and awaits the old task; unexpected pump
   errors logged.
10. Glossary phrases: Matt/Mat/Mac/Max/amat/mc/mcway, Mattacito, Maxacito,
    Danna (cousin), Roblox/Robus/Roblo/robla.

## Next up (user's priority)
- **FIX FIRST — incoming audio loss around finalization (bug, found in review)**:
  in `_incoming_once`, when `.completed` arrives the controller awaits NMT while
  the pump keeps pushing fresh audio into a stream whose results are never read,
  then tears down capture and reopens it → audio spoken during translation is
  dropped + capture gap. FIXED (commit 6f783b8): capture + ASR stream stay open
  across consecutive finals; finals are translated in background workers with a
  generation counter (`_incoming_gen`) so stale results can't resurrect cleared
  cards. Deployed + service restarted + verified.
- **Re-score WER properly**: DONE with jiwer 4.0.0 (`tools/score_wer.py`).
  Corrected WER: parakeet-tdt 76.3%/47.0%, nemotron-3.5 93.2%/60.6% (clip 1/2).
  S/D/I: parakeet 18/0/27 + 12/0/19; nemotron 21/1/33 + 21/1/18. Insertions
  dominate (both models add content vs the verbatim reference). Prior difflib
  numbers were NOT valid WER. Reference text remains authoritative; disputed
  extra content still needs a Spanish speaker to arbitrate.
- **Head-to-head architecture comparison** (NOT a confirmed two-tier plan yet):
  (a) buffered/chunked Parakeet-only vs (b) Nemotron draft → Parakeet refine.
  Measure draft latency / final latency / text stability on short + continuous
  speech. DATA COLLECTED: Parakeet via persistent serve (POST
  /v1/audio/transcriptions) is fast — 2s chunk ~0.29s, 3s ~0.12s, 5s ~0.14s,
  8s ~0.18s; full 36s clip ~0.74s, 30s clip ~0.58s. C++ runtime
  `streaming_recognize` is genuinely unavailable for Parakeet
  (recognizer.cpp:209-214 throws "offline-only" for non-CTC heads without
  cache streaming). So two-tier = Nemotron streaming drafts + Parakeet server
  re-transcribing each final utterance (~0.1-0.3s added latency). Parakeet-only
  streaming is impossible in this runtime (NeMo buffered chunking = separate
  Python/torch stack). Remaining: measure end-to-end draft→final latency + text
  stability on a real utterance stream before implementing.
- **Two-tier incoming translation** (user idea): IMPLEMENTED + validated. `ASRConfig`
  gains `offline_model/offline_port/offline_enabled`; `NemoASR.start_offline()`
  runs a 2nd `serve` (Parakeet) on 8081; incoming captures a ~20s raw PCM ring
  and, on each `.completed`, uses the server's `audio_processed` delta to bound
  the utterance and POSTs it to Parakeet via `transcribe_offline()`
  (multipart); a background task re-transcribes + re-translates and updates the
  card IN PLACE (same id) if text differs. Generation counter drops stale
  refinements. `_snapshot_utterance_audio` skips sub-300ms utterances (empty
  WAV 500s Parakeet). Validated live: refine works, Parakeet more complete than
  Nemotron draft. Parakeet still misrecognizes ("caballete"→"caballo"/"horse").
  Off by default (`offline_enabled=false`); needs a panel toggle + control
  `set` action already wired (`two_tier`). Service restarted clean; verified
  toggle on/off (Parakeet process starts/stops correctly).
- **Auto-detect input level (gating)** — user idea, agreed in principle: gate
  incoming translation on a minimum monitor signal level. Panel slider, default
  low. DISABLED while an active call is happening (user confirmed). Gating must
  not starve ASR of trailing silence (or endpointing never completes); call
  detection needs explicit design (`media.role=Communication` + manual override).
- **Evaluate a higher-accuracy ASR model**: Parakeet TDT 0.6B v3 pulled + timed
  (Vulkan q8_0): preliminary difflib WER 64.4%/34.8% vs Nemotron 83.1%/45.5%;
  15 s file transcription ~1.1 s vs ~4.3 s (both incl. subprocess startup).
  CAVEAT: difflib ≠ minimum edit distance; re-score with jiwer. Canary 1B Flash /
  v2 remain candidates.
- Calibration clips: `~/Downloads/es-calibrate-{1,2}.{m4a,txt}` (verbatim
  reference). Streaming model produces extra fluent-looking content on long
  continuous speech (cause unverified). Accuracy ≈ 6–7/10. Pre-processing /
  right_context / language prompt / punctuation / batching don't help.
- Analyze the recorded daughter WAVs in `~/.local/state/omarchy-live-translator/debug/`
  (level/bandwidth/silence) to explain why child speech is still hard. NOTE:
  match each WAV to the event timestamp; the newest WAV is often post-audio
  silence (see workarounds).
- User idea (future): use recorded WAVs as a translation-speed benchmark
  across sentence lengths / settings.
- Word boosting is currently a no-op: the shipped GGUF has the tokenizer VOCAB
  (`asr.tokenizer.vocab`, 13087 pieces) but lacks `asr.tokenizer.spm_model`
  (the base64 SentencePiece proto the C++ runtime needs to tokenize arbitrary
  boost phrases). Feasibility verified: re-convert the .nemo checkpoint with
  `convert_model.py` (in `/tmp/opencode/nemo-speech-src/`) which embeds
  spm_model. Requires: 2.37 GB .nemo download + a venv with torch, numpy,
  gguf, sentencepiece, protobuf, safetensors, PyYAML, huggingface-hub
  (see `requirements.txt`). ~863 GB free disk. Ready to execute when user
  approves (heavy download + torch install).
- Then: package as an Omarchy plugin (installer, config, docs) — LAST step.
- Then: endpointing/VAD tuning; Phase 2 incoming speech-to-speech (opt-in).
  Model/voice management deferred.

## Review findings (independent agent, 2026-09-14) — being addressed now
1. Incoming audio loss around finalization (bug) — see FIX FIRST above.
2. WER methodology: `difflib.SequenceMatcher` ≠ minimum edit distance; use jiwer.
3. "Parakeet offline-only" too broad; buffered chunking exists in NeMo.
4. Drafts are source-only (not translated drafts).
5. Overlay: separate creation vs revision order; preserve scroll; generation IDs
   to invalidate stale results on clear/pause/direction/stop.
6. Resource claims unverified (file speed ≠ live latency; 2 models ≠ 2× VRAM).
7. Gating can starve endpointing; headphones stop acoustic (not digital) feedback
   — TTS into the captured sink's monitor still loops.
8. Misc: +6 dB preamp can clip; debug WAVs are post-processing; custom WS client
   lacks ping/pong/fragmentation; installed build 404s on documented
   `/v1/audio/transcriptions/realtime` (version pinning).

## Naming / branding
- Plugin renamed to **OmaTranslate** (`bstail.omatranslate`) — manifest,
  BarWidget, Panel header, tooltip, README. Bar layout in
  `~/.config/omarchy/shell.json` updated to `bstail.omatranslate`.
- Old plugin dir moved to `~/.config/omarchy/plugins.old/` (out of active
  plugins). Underlying services/subprocesses/state dirs STILL use
  `omarchy-live-translator` naming (rename deferred — user said keep it simple).
- User registered omatranslate.com — do NOT reference the dot-com anywhere yet.

## User preferences
- Native English speaker; main direction en→es outgoing, es→en incoming.
- Assume bi-directional works; assume Bluetooth/headphones need no echo pause.
- Wants clean, futuristic, dynamic UI following the active Omarchy theme.
- Prefers working plugin over model management for now.
