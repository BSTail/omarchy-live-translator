# Session Memory — omarchy-live-translator

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
- Widget: `~/.config/omarchy/plugins/bstail.live-translator/` (manifest.json, BarWidget.qml, Panel.qml)
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

## User preferences
- Native English speaker; main direction en→es outgoing, es→en incoming.
- Assume bi-directional works; assume Bluetooth/headphones need no echo pause.
- Wants clean, futuristic, dynamic UI following the active Omarchy theme.
- Prefers working plugin over model management for now.
