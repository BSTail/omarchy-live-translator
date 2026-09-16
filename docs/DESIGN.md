# Controller Process & Overlay State Machine

This describes the runtime design for `omatranslate`. The goal is a
clean, lightweight controller that glues already-proven local tools together and
drives a single floating overlay. Design principles:

1. **Small, boring, testable.** One controller process in Python, no framework.
2. **Stateless engines, stateful controller.** The sub-services (ASR, NMT, TTS)
   do one thing; the controller owns all workflow state.
3. **Ask-only, opt-in on outgoing.** Outgoing translation is push-to-talk and
   gates on an explicit "Speak" action so the user can correct text first.
4. **Always-on incoming.** Incoming translation runs continuously and never
   intercepts the mic.
5. **Keep Voxtype as-is.** Voxtype stays the multilingual dictation plugin
   (F9 / Shift+F9). This plugin is a separate concern and uses NeMo.

---

## 1. Process boundaries

Two coexisting, lightweight local speech stacks:

| Stack | Plugin | Engine | Job |
|---|---|---|---|
| Voxtype (unchanged) | `omarchy-bilingual-voxtype` | Whisper `small` (Vulkan) | Dictation into any app (F9) |
| NeMo (this plugin) | `omatranslate` | Nemotron 3.5 ASR 0.6B (Vulkan) | Live call translation (F10+) |

They do not share a daemon and do not overlap. Voxtype is not modified.

```
hyprland bindings
      │  (F10 / Shift+F10 / F11 / F12)
      ▼
┌────────────────────────────┐        ┌──────────────────────────────┐
│        controller          │  HTTP  │   nemo-speech serve           │
│   (python, asyncio;        │◀─────▶│   ASR only                     │
│    local HTTP control +    │   WS   │   nemotron-3.5 0.6B, Vulkan   │
│    overlay ownership)      │        │   /v1/audio/transcriptions/…  │
└───────────┬────────────────┘        └──────────────────────────────┘
            │ HTTP
            ├──▶ LibreTranslate  (127.0.0.1:5000, en↔es)
            ├──▶ Piper TTS       (per-utterance; stdin text → stdout WAV)
            └──▶ overlay         (own process; controller pokes it)
```

| Process | Starts | Communication | Notes |
|---|---|---|---|
| `nemo-speech serve` | controller | HTTP + WebSocket | ASR only; validated on Vulkan |
| `libretranslate` | user (systemd) | HTTP POST `/translate` | existing, `en_es` model |
| `piper` | controller, per utterance | stdin text → stdout WAV | short-lived, no daemon |
| `overlay` | controller | local IPC (JSON over stdin / dbus-free) | GTK4 layer-shell window |
| `controller` | user (systemd user unit) | — | owns everything |

### Why Python for the controller

- `gi` (PyGObject) is already present for the overlay; a single language keeps
  the plugin to one dependency story.
- The ASR already exposes a clean HTTP/WebSocket API, so the controller only
  does orchestration, not DSP.

### TTS: Piper primary, MagpieTTS rejected for now

We evaluated NeMo's MagpieTTS and decided against it for live outgoing speech.
Findings on this hardware (Intel Arc, Vulkan):

- **Sub-realtime.** Spanish and English synthesis both ran at ~0.79x realtime
  (6.5 s of audio took ~9.7 s to synthesize) — too slow for a live call.
- **No Vulkan benefit.** CPU and Vulkan were effectively identical (both
  ~0.78x), and both saturated CPU cores; the Arc GPU did not accelerate TTS.
- **Cannot co-reside with ASR.** `nemo-speech serve --asr-model … --tts-model
  magpie` crashed at warmup with `GGML_ASSERT(ne3 == ne13) failed` in
  `ggml-cpu.c`. ASR-only serve works; ASR+TTS in one server does not.

So TTS uses **Piper** (20–50x realtime on CPU), spawned per utterance, keeping
the plugin to three small tools. MagpieTTS is the fallback if Piper's Spanish
quality is unacceptable, and only as a separate short-lived process.

We do **not** use NeMo's Riva Translate 4B for translation — it is a 4B model
that would have to load on Vulkan alongside ASR, and it is unproven on Arc.
LibreTranslate is already running, tiny, and proven, so it remains the NMT.

---

## 2. Controller responsibilities (single-threaded, `asyncio`)

1. Spawn `nemo-speech serve` with the ASR model, Vulkan backend, and the
   `LD_PRELOAD` workaround applied.
2. Run a tiny local HTTP control server (e.g. `127.0.0.1:8670`) for hotkeys and
   the overlay. Commands arrive as JSON POSTs.
3. Own the overlay process; send it state updates over a local socket.
4. Run two independent pipelines:

### 2a. Outgoing (push-to-talk, ask-first)

Triggered by `F10` (English→Spanish) or `Shift+F10` (Spanish→English).

```
[ mic capture ] → [ ASR (WS) ] → [ NMT ] → [ overlay: Draft ] → user reviews
                                                        │
                                        [ Speak ] ──────┤ (or edits first)
                                                        ▼
                                               [ NMT again if edited ]
                                                        ▼
                                             [ TTS (Piper) ] → [ virtual mic ]
                                                        ▼
                                               [ overlay: Spoken ]
```

1. Controller starts a live mic capture (16 kHz mono PCM16) fed to the ASR
   WebSocket.
2. ASR partials update the overlay as **Draft** in real time.
3. On endpoint (push-to-talk released, or silence), the finalized source text is
   sent to LibreTranslate.
4. The translation enters the overlay as **Draft**, editable.
5. User presses **Speak** (e.g. `F11`), or the controller auto-speaks after a
   short review window (configurable, default manual).
6. Edited text is re-translated only if the user changed the source, then sent
   to TTS. The resulting audio is routed to a **virtual microphone** (a PipeWire
   null/loopback source) that the user selects as the mic in the call app.
7. **Only at step 5 does anything reach the call.** Nothing is spoken
   automatically on outgoing unless "auto-speak" is enabled.

### 2b. Incoming (always-on, on-screen)

```
[ call audio (monitor source) ] → [ VAD/endpointing ] → [ ASR (WS) ]
        → [ NMT es→en ] → [ overlay: Incoming, auto-shown ]
```

1. A PipeWire **monitor source** captures the remote speaker's audio (the call
   app's output, never the mic).
2. VAD + endpointing split it into utterances; each fed to the ASR WebSocket.
3. Translation flows into the overlay as **Incoming** lines, marked **Draft**
   until punctuation/end-of-utterance finalizes them to **Ready**.
4. Incoming text is displayed only in this phase.

### 2c. Incoming speech-to-speech (Phase 2, after on-screen works)

Secondary goal, built only after 2a and 2b are solid:

```
[ call audio (monitor) ] → [ ASR ] → [ NMT es→en ] → [ TTS (English) ]
        → [ headphones / speakers ]
```

- Remote Spanish is transcribed, translated to English, and **spoken into the
  user's headphones/speakers**.
- This is opt-in and must not echo back into the call (see routing below).

### Concurrency model

Outgoing and incoming are two side-by-side `asyncio` tasks using **two ASR
WebSocket connections** — one per direction, to keep language prompts pinned
(`en-US` vs `es-ES`) and avoid re-configuring mid-stream:

| Direction | ASR language prompt |
|---|---|
| Outgoing en→es | `en-US` |
| Outgoing es→en | `es-ES` |
| Incoming (remote speaks es) | `es-ES` (configurable) |

---

## 3. Audio routing (PipeWire)

Two routes keep the streams separate and echo-free:

| Route | Source | Sink | Purpose |
|---|---|---|---|
| **Virtual mic (outgoing)** | TTS output | a null/loopback **source** | user selects it as the call app's microphone |
| **Monitor (incoming)** | call app output monitor | controller capture | hear only the remote speaker |
| **Headphones (Phase 2)** | TTS output | user's headphone/speaker sink | spoken English translation |

### Testing with earbuds

- With a headset, the mic picks up only the user's voice and TTS playback goes
  to the ears, not back into the call — isolating the two streams and avoiding
  echo/feedback.
- "Remote audio" is captured from the call app's output monitor, so the user's
  own voice does not leak into the incoming path.

---

## 4. Overlay

A small GTK4 `LayerShell` window (top-right, always on top but click-through
when idle). It renders **cards**, each with a header line and a source/target
text pair.

### Visual states (per card)

| State | Meaning | Color / affordance |
|---|---|---|
| **Draft** | Text may still change (ASR partial or awaiting review) | translucent, small spinner |
| **Ready** | Finalized text, user may edit | solid, editable, "Speak" hint |
| **Spoken** | Outgoing text that has been sent to TTS | checkmark, fades out |
| **Incoming** | Finalized remote utterance | distinct accent color |

### State machine (per card)

```
              ┌──────────────────────────────┐
              │                              │
    mic/ASR  ─┴─▶  DRAFT  ──(endpoint)──▶  READY ──(Speak)──▶ SPOKEN ──▶ fade
              │       ▲
              │       │(ASR revision)
              │       │(user edit → re-translate back to?)
              └───────┘

   incoming: DRAFT ──(endpoint/punct)──▶ INCOMING ──▶ auto-fade / scroll
```

Transitions the controller is allowed to request: `draft`, `ready`, `spoken`,
`incoming`, `clear`. The overlay never decides; it only renders.

### Overlay content model

- Each card has a **direction** (`out` or `in`), a **source** text, a **target**
  text, and a **state**.
- Outgoing cards show: source (what the user said) on top, target (translation)
  below, so the user can review the translation in context.
- Incoming cards show the translated target first (it is the useful part) with
  the original beneath in smaller text.

### Theming

The overlay follows the **active Omarchy theme** dynamically — no hardcoded
colors. See `docs/THEMING.md` for the exact mechanism (how the active theme is
resolved, how its colors and gradient border are turned into GTK CSS, and the
pitfalls to avoid).

---

## 5. Control surface (hotkeys)

Chosen to avoid the existing Voxtype F9 plugin entirely:

| Key | Action |
|---|---|
| `F10` | Start outgoing English→Spanish (push-to-talk) |
| `F10` release | Finalize recognition (endpoint) |
| `Shift+F10` | Start outgoing Spanish→English |
| `F11` | Speak the current Ready card (send to TTS) |
| `F12` | Dismiss/clear overlay |
| `Shift+F12` | Pause/resume incoming translation |

The controller is the single owner of hotkey handling (mapped in
`~/.config/hypr/bindings.lua`, same pattern as the existing plugin).

---

## 5b. Bar widget (settings + lifecycle)

A Quickshell bar widget gives per-call control without a terminal. It runs
inside `omarchy-shell`, so it stays visible even while the plugin is stopped.

| Element | Behaviour |
|---|---|
| **Icon pill** | status: green = running, gray = stopped |
| **Panel (click)** | Start/Stop, toggles, clear overlay |

### Start / Stop

- **Start** = `systemctl --user start omatranslate.service libretranslate-live.service`
- **Stop** = `systemctl --user stop omatranslate.service libretranslate-live.service`

Stopping halts **only this plugin's** services:

| Service | Stopped by widget | Notes |
|---|---|---|
| `omatranslate.service` | yes | controller + `nemo-speech serve` |
| `libretranslate-live.service` (port 5001) | yes | this plugin's translation service |
| `libretranslate.service` (port 5000) | **no** | belongs to the dictation plugin |
| `voxtype.service` | **no** | belongs to the dictation plugin |

### Toggles (via the controller's control server)

- incoming translation on/off
- outgoing direction (en→es / es→en)
- auto-speak on/off
- clear overlay

The widget never touches the dictation plugin's services.

---

## 6. Data flow contract (each hop)

| Hop | In | Out | Transport |
|---|---|---|---|
| mic → ASR | PCM16 16 kHz mono | partials/final text | WebSocket `/v1/audio/transcriptions/realtime` |
| ASR → NMT | `{q, source, target}` | `{translatedText}` | HTTP POST LibreTranslate `/translate` |
| NMT → TTS | text | WAV/PCM | `piper --model … --output-raw` (stdin/stdout) |
| TTS → call | PCM16 | audio routed to virtual mic or speakers | PipeWire null/loopback source, or the chosen sink |
| controller → overlay | JSON state command | render | local socket / stdin pipe |
| hotkeys → controller | JSON command | action | HTTP POST to local control server |

---

## 7. Config (minimal)

```toml
[paths]
nemo_speech = "~/.local/bin/nemo-speech"
piper       = "/usr/bin/piper"

[asr]
model = "nemotron-3.5"          # indexed name, pulls q8_0
device = "vulkan:0"
preload_stdcxx = true           # apply LD_PRELOAD workaround

[tts]
engine = "piper"                # or "magpie" fallback
voice_en = "en_US-lessac-medium"
voice_es = "es_ES-davefx-medium"

[outgoing]
language = "en-US"
target   = "es"
auto_speak_after_ms = 0         # 0 = manual (Speak key) required
output_destination = "virtual_mic"  # "virtual_mic" | "speakers"
virtual_mic = "olt-virtual-mic" # PipeWire source selected in the call app
speakers_sink = "@DEFAULT_SINK@"    # used when output_destination = "speakers"

[incoming]
enabled           = true
source_language   = "es-ES"     # what the remote speaker uses
target            = "en"
source_device     = "…monitor"  # PipeWire monitor source id/name

[incoming_tts]                  # Phase 2
enabled = false
sink     = "…headphones"

[overlay]
position = "top-right"
```

---

## 8. Failure & lifecycle rules

- If `nemo-speech` dies, the controller restarts it and reconnects; the overlay
  shows a "reconnecting" hint, never a crash.
- A failed translation request leaves the card in **Ready** (re-editable), never
  silently drops text.
- TTS failures mark the card **Draft** again with an error hint.
- The overlay is disposable; killing it does not stop translation, and the
  controller re-spawns it.

---

## 9. What we deliberately avoid

- **No second Voxtype daemon.** NeMo is a separate process; Voxtype stays
  untouched as the dictation plugin.
- **No full-duplex echo.** Incoming is display-only in Phase 1; outgoing is
  ask-first. Incoming speech-to-speech (Phase 2) is opt-in and routed to
  headphones, never back into the call.
- **No framework in the overlay.** Plain GTK4 via PyGObject, no Quickshell/EGUI
  dependency for the first version (we can revisit if polish demands it).
- **No Riva Translate 4B.** LibreTranslate stays the NMT; NeMo is used only for
  ASR.
- **No MagpieTTS (for now).** Sub-realtime and no Vulkan benefit on Arc; Piper is
  the TTS engine. See "TTS" in section 1.

---

## 10. Phasing

| Phase | Scope |
|---|---|
| **1** | Outgoing PTT + on-screen incoming translation (2a + 2b) |
| **1b** | Bar widget: start/stop (own services only) + settings toggles |
| **2** | Incoming speech-to-speech into headphones (2c), opt-in |
| **3** | Polish: overlay editing UX, auto-speak tuning, packaging as an Omarchy plugin |

---

## 11. Known upstream issues to watch

Open GitHub issues on `NVIDIA/NeMo-Speech.cpp` that affect our plans:

| Issue | Relevance |
|---|---|
| [#22](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/22) — streaming ASR leaks previous-turn punctuation into the next final | affects incoming endpointing; watch before relying on auto-punctuation across turns |
| [#40](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/40) — token-silence EOU misfires mid-sentence and corrupts transcript | affects incoming segmentation; prefer VAD over token-silence endpointing |
| [#23](https://github.com/NVIDIA/NeMo-Speech.cpp/issues/23) — v0.1.0 `cpu` tarball SIGILLs on AVX2-only machines | does **not** affect us: we use the Vulkan variant |

The ASR-only `serve` + realtime WebSocket path we depend on is validated and
working; the issues above concern endpointing behaviour, which we control via
VAD configuration rather than the token-silence default.
