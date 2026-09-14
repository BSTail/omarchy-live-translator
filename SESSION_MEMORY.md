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
- Settings panel: direction, auto-speak, incoming enable/direction, multimedia,
  history, glossary (word-boost), per-app activation, output toggle,
  diagnostics, clear-logs.
- Latency telemetry + JSONL event log (`events.jsonl` in state dir);
  `olt-ctl diagnostics` shows avg/min/max per stage.

## Paths
- Deployed source: `~/.local/share/omarchy-live-translator/src/olt/`
- Config: `~/.config/omarchy-live-translator/config.toml`
- Widget: `~/.config/omarchy/plugins/bstail.live-translator/` (manifest.json, BarWidget.qml, Panel.qml)
- systemd user units: `omarchy-live-translator.service`, `libretranslate-live.service`
- CLI: `~/.local/bin/olt-ctl` (ptt_start/ptt_stop/speak/clear/clear_logs/pause_incoming/status/diagnostics)
- Logs/events: `~/.local/state/omarchy-live-translator/` (olt.log, events.jsonl)
- Git repo (source of truth): `BSTail/omarchy-live-translator`, local clone `/tmp/opencode/olt`

## Last completed tasks
1. Added "Clear logs & history" button (deletes olt.log*, events.jsonl, clears overlay; service keeps running).
2. Fixed Gtk-CRITICAL overlay assertions by updating entries in place.
3. Before that: latency telemetry + JSONL event log + diagnostics latency summary.
4. Before that: history toggle, multimedia mode, unified scrollable overlay.

## Next up (user's priority)
- Package as an Omarchy plugin (installer, config, docs).
- Then: real video/voice call test; endpointing/VAD tuning; Phase 2 incoming
  speech-to-speech (opt-in). Model/voice management deferred.

## User preferences
- Native English speaker; main direction en→es outgoing, es→en incoming.
- Assume bi-directional works; assume Bluetooth/headphones need no echo pause.
- Wants clean, futuristic, dynamic UI following the active Omarchy theme.
- Prefers working plugin over model management for now.
