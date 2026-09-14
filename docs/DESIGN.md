# Controller Process & Overlay State Machine

This describes the runtime design for `omarchy-live-translator`. The goal is a
clean, lightweight controller that glues three already-proven local tools
together and drives a single floating overlay. Design principles:

1. **Small, boring, testable.** One controller process in Python, no framework.
2. **Stateless engines, stateful controller.** The sub-services (ASR, NMT, TTS)
   do one thing; the controller owns all workflow state.
3. **Ask-only, opt-in on outgoing.** Outgoing translation is push-to-talk and
   gates on an explicit "Speak" action so the user can correct text first.
4. **Always-on incoming.** Incoming translation runs continuously and never
   intercepts the mic.

---

## 1. Processes

```
hyprland bindings
      │  (F10 / Shift+F10 / F11)
      ▼
┌────────────────────────────┐        ┌──────────────────────────────┐
│        controller          │  HTTP  │   nemo-speech serve (ASR)     │
│   (python, socket over     │◀─────▶│   nemotron-3.5 0.6B, Vulkan    │
│    a small local HTTP +    │   WS   │   /v1/audio/transcriptions/…  │
│    overlay ownership)      │        │   realtime WebSocket          │
└───────────┬────────────────┘        └──────────────────────────────┘
            │ HTTP
            ├──▶ LibreTranslate  (127.0.0.1:5000, en↔es)
            ├──▶ Piper TTS       (pipe via stdin, write WAV to stdout)
            └──▶ overlay         (own process; controller pokes it)
```

| Process | Starts | Communication | Notes |
|---|---|---|---|
| `nemo-speech serve` | controller | HTTP + WebSocket | ASR only; already validated on Vulkan |
| `libretranslate` | user (systemd) | HTTP POST `/translate` | existing, `en_es` model |
| `piper` | controller, per utterance | stdin text → stdout WAV | short-lived, no daemon |
| `overlay` | controller | local IPC (JSON over stdin / dbus-free) | GTK4 layer-shell window |
| `controller` | user (systemd user unit) | — | owns everything |

### Why Python for the controller

- `gi` (PyGObject) is already present for the overlay; a single language keeps
  the plugin to one dependency story.
- The ASR already exposes a clean HTTP/WebSocket API, so the controller only
  does orchestration, not DSP.

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
                                             [ Piper TTS ] → [ call audio ]
                                                        ▼
                                              [ overlay: Spoken ]
```

1. Controller starts a live mic capture (16 kHz mono PCM16) fed to the ASR
   WebSocket.
2. ASR partials update the overlay as **Draft** in real time.
3. On endpoint (push-to-talk released, or silence), the finalized English text
   is sent to LibreTranslate.
4. The Spanish translation enters the overlay as **Draft**, editable.
5. User presses **Speak** (e.g. `F11`), or the controller auto-speaks after a
   short review window (configurable, default manual).
6. Edited text is re-translated only if the user changed the source, then sent
   to Piper; audio routed to the call output (not the mic).
7. **Only at step 5 does anything reach the speaker's ears.** Nothing is spoken
   automatically on outgoing unless "auto-speak" is enabled.

### 2b. Incoming (always-on)

```
[ call audio (loopback/monitor source) ] → [ VAD/endpointing ] → [ ASR (WS) ]
        → [ NMT en→es ] → [ overlay: Incoming, auto-shown ]
```

1. A PipeWire loopback/monitor captures the remote speaker's audio (never the
   mic).
2. VAD + endpointing split it into utterances; each fed to the ASR WebSocket.
3. Translation flows into the overlay as **Incoming** lines, marked **Draft**
   until punctuation/end-of-utterance finalizes them to **Ready**.
4. Incoming text is never spoken back (bidirectional but not full-duplex echo);
   it is only displayed. Optional TTS-on-incoming can be enabled later.

### Concurrency model

Outgoing and incoming are two side-by-side `asyncio` tasks sharing one ASR
WebSocket connection (or two connections — one per direction, to keep language
prompts pinned `en-US` vs `es-ES` and avoid re-configuring mid-stream). Two
connections is simpler and avoids prompt thrash:

| Direction | ASR language prompt |
|---|---|
| Outgoing en→es | `en-US` |
| Outgoing es→en | `es-ES` |
| Incoming (remote speaks es) | `es-ES` (configurable) |

---

## 3. Overlay

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

---

## 4. Control surface (hotkeys)

Chosen to avoid the existing Voxtype F9 plugin entirely:

| Key | Action |
|---|---|
| `F10` | Start outgoing English→Spanish (push-to-talk) |
| `F10` release | Finalize recognition (endpoint) |
| `Shift+F10` | Start outgoing Spanish→English |
| `F11` | Speak the current Ready card (send to Piper) |
| `F12` | Dismiss/clear overlay |
| `Shift+F12` | Pause/resume incoming translation |

The controller is the single owner of hotkey handling (mapped in
`~/.config/hypr/bindings.lua`, same pattern as the existing plugin).

---

## 5. Data flow contract (each hop)

| Hop | In | Out | Transport |
|---|---|---|---|
| mic → ASR | PCM16 16 kHz mono | partials/final text | WebSocket `/v1/audio/transcriptions/realtime` |
| ASR → NMT | `{q, source, target}` | `{translatedText}` | HTTP POST LibreTranslate `/translate` |
| NMT → TTS | text | WAV | `piper --model … --output-raw` (stdin/stdout) |
| TTS → call | PCM16 24/22k | audio routed to speaker | PipeWire (not mic) |
| controller → overlay | JSON state command | render | local socket / stdin pipe |
| hotkeys → controller | JSON command | action | HTTP POST to local control server |

---

## 6. Config (minimal)

```toml
[paths]
nemo_speech = "~/.local/bin/nemo-speech"
piper = "/usr/bin/piper"

[asr]
model = "nemotron-3.5"          # indexed name, pulls q8_0
device = "vulkan:0"
preload_stdcxx = true           # apply LD_PRELOAD workaround

[outgoing]
language = "en-US"
target   = "es"
auto_speak_after_ms = 0         # 0 = manual (Speak key) required

[incoming]
enabled           = true
source_language   = "es-ES"     # what the remote speaker uses
target            = "en"
source_device     = "…monitor"  # PipeWire monitor source id/name

[tts]
voice_en = "en_US-lessac-medium"
voice_es = "es_ES-davefx-medium"

[overlay]
position = "top-right"
```

---

## 7. Failure & lifecycle rules

- If `nemo-speech` dies, the controller restarts it and reconnects; the overlay
  shows a "reconnecting" hint, never a crash.
- A failed translation request leaves the card in **Ready** (re-editable), never
  silently drops text.
- Piper is spawned per utterance and reaped; a TTS failure marks the card
  **Draft** again with an error hint.
- The overlay is disposable; killing it does not stop translation, and the
  controller re-spawns it.

---

## 8. What we deliberately avoid

- **No second Voxtype daemon.** NeMo is a separate process.
- **No full-duplex echo.** Incoming is display-only by default; outgoing is
  ask-first. Auto-speak on incoming TTS is a later, opt-in feature.
- **No framework in the overlay.** Plain GTK4 via PyGObject, no Quickshell/EGUI
  dependency for the first version (we can revisit if polish demands it).
- **No monolithic runtime.** Three tools, one controller.
