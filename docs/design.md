# lightweight-stt — redesign

Local, NPU-only push-to-talk dictation for GNOME Wayland. Hold a key, speak,
release, text lands at the cursor. No cloud, near-zero idle cost.

## Goals

- Text reliably injected at the cursor in **native Wayland** apps (not just Xwayland).
- Whisper runs on the Intel NPU; CPU essentially idle between utterances.
- Fast launch (NPU compile cached) and fast stop-talk-to-text.
- Runs as a `systemd --user` service from login.
- Small, readable modules; easy to extend later.

## Non-goals (explicitly cut for now)

- VAD / voice-activated / continuous streaming transcription. `audio.py` leaves a
  hook for endpointing; no `onnxruntime` / `webrtcvad` dependency is added.
- GUI. Status is `notify-send` + optional beeps.
- Model conversion in the runtime path — moved to `convert.sh`.

## Locked decisions

| Topic | Decision |
|---|---|
| Default mode | **HYBRID** — a keydown always starts recording; on keyup, a press longer than `tap_ms` (350 ms) is treated as a hold and stops now, a shorter press latches a toggle session that the next tap ends. `mode = "hybrid" \| "hold" \| "toggle" \| "streaming"`. `streaming` still behaves as `toggle` until endpointing lands. |
| Default hotkey | `KEY_F23` (code 193), held. This is what the Microsoft Copilot key emits, and it is otherwise unused on Linux. Configurable. |
| Mode switching | Config file only. No runtime modifier+hotkey cycle (the Copilot key has no spare modifier and its node can't be grabbed). Drops `on_cycle` from `hotkey.py`. |
| Copilot key chord | The Copilot key emits `LEFTMETA+LEFTSHIFT+F23` from a single keyboard node that also carries normal typing → **no `grab()`**. `hotkey.py` keys purely off `KEY_F23` down/up and ignores the META/SHIFT events. The chord leaks to the compositor; expected harmless (Super released last-with-others, `Super+Shift+F23` unbound). Fallback if it isn't: a `keyd` rule `meta+shift+f23 → f23` — documented, not built. |
| Injection | `ydotool type` default → auto-route strings > 50 chars (and non-ASCII-heavy) to `wl-copy` + `ydotool key ctrl+v` → `xdotool type` only if session is X11. Startup probe; refuse to start if none work. |
| Indicator | `notify-send -r 9942 -h int:transient:1` in place. Beeps via fire-and-forget `canberra-gtk-play -i <event>`. No Tkinter, no `sounddevice` output stream. `indicator = "notify" \| "beep" \| "both" \| "off"`. |
| Module split | Full split under `stt/` (below). |
| Keyboards | Multiplex **every** device exposing `EV_KEY`+`KEY_A` via `selectors`. Re-scan on device error/hotplug. |

## Target environment

- An Intel Core Ultra laptop with an NPU at `/dev/accel/accel0` via the
  `intel-npu-level-zero` driver; a recent Ubuntu with GNOME Wayland.
- User **must** be in `render` (NPU) and `input` (evdev) groups, or OpenVINO
  silently falls back to CPU.
- Some laptops route macro / Fn / vendor keys through a second virtual keyboard
  node, so multiplexing all `EV_KEY` nodes is mandatory, not optional.
- `/dev/uinput` needs a `uaccess` udev rule so `ydotoold` starts without sudo.
- OpenVINO GenAI 2026.2 (`WhisperPipeline`). See **Open items** for the API
  facts confirmed during implementation.

## Module layout

```
stt/
  __init__.py
  config.py      load ~/.config/lightweight-stt/config.toml over defaults
  inject.py      text injection + startup capability probe
  transcribe.py  OpenVINO Whisper wrapper
  audio.py       persistent input stream + ring buffer (+ endpointing hook)
  hotkey.py      multi-device evdev listener; hold / toggle state machine
  indicator.py   notify-send status + canberra beeps
  doctor.py      `python -m stt.doctor` — checks groups/NPU/ydotoold/uinput/model/mic
  meter.py       `python -m stt.meter` — live mic RMS bar for tuning vad_threshold
  status.py      `python -m stt.status` — config + environment snapshot (no NPU)
  textfmt.py     snake/camel/raw reshaping for hotkey_format
  init.py        `python -m stt.init` — write a commented starter config.toml
  stats.py       optional transcription-latency timing (latency_stats)
  power.py       read the active power profile (battery_saver)
  appwatch.py    read the focused window's app id (wlroots) for per-app profiles
  main.py        wiring, single-instance lock, logging, signal handling
convert.sh       one-off: optimum-cli export openvino (throwaway venv)
setup.sh         rewritten (runtime deps only + groups + udev + services)
stt_server.py    keep; import stt.transcribe instead of its own pipeline copy
systemd/lightweight-stt.service
udev/99-uinput.rules
```

### Module contracts

**config.py**
- `load() -> Config` (frozen dataclass). No file → all defaults. Partial file
  merges over defaults. Unknown keys warn, don't crash. `_validate()` then
  swaps any out-of-range enum (`mode`, `device`, `inject_method`, `indicator`,
  `battery_saver`), non-positive/non-numeric knob (`tap_ms`, `*_ms`,
  `num_beams`, `vad_threshold`), or bad `hotkey_format` mode back to its
  default, one warning each. No schema versioning — deliberately.
- Keys (see the README table for the full list with defaults): press/hotkey —
  `mode`, `tap_ms`, `hotkey` (name or list), `hotkey_language`,
  `hotkey_translate`, `hotkey_format`, `mute_hotkey`, `cough_hotkey`,
  `keyboard`. Audio — `audio_device`, `follow_default_mic`,
  `min_speech_ms`, `vad_silence_ms`, `vad_threshold`. Model — `device`,
  `language`, `num_beams`, `vocabulary`, `hallucinations`, `cache_dir`.
  Output — `inject_method`, `paste_threshold`, `paste_settle_ms`,
  `trailing_space`, `indicator`, `commands` (phrase → key/literal/`<undo>`),
  `profiles` / `apps` (focused-window → per-utterance overrides).
  Post-processing — `llm_cleanup`, `llm_endpoint`, `llm_model`.
  Logging — `history`, `privacy`, `latency_stats`. Power — `battery_saver`.
  Collection-valued keys default to empty.

**cleanup.py**
- `clean_text(text, endpoint, model)` — POSTs to `{endpoint}/chat/completions`
  on any OpenAI-compatible local server (Ollama, llama.cpp, LM Studio) with a
  "strip fillers, fix punctuation, don't rephrase" system prompt. Fails open:
  any error returns the input unchanged with a warning. `main.run()` builds a `cleaner` closure when
  `llm_cleanup` is set and `emit_segment` applies it after transcription but
  before typing — skipped for utterances that matched a `commands` entry, and
  not built at all when `privacy` is on (the transcript would otherwise be
  POSTed off-process); `emit_segment` also guards on `redact` as a backstop.

**init.py**
- `run()` writes a fully-commented `config.toml` (every line a default) to
  `DEFAULT_PATH`, refusing if it exists. Not the autodetecting first-run wizard
  — just the template half; a test asserts every `Config` field appears in it.

**appwatch.py**
- `active_app()` — focused window's `app_id` / class, lowercased, via
  `swaymsg -t get_tree` or `hyprctl activewindow -j`. `None` on GNOME (no IPC)
  so per-app profiles just don't fire. `main.pick_profile(profiles, apps, app)`
  is the pure matcher (case-insensitive substring of an `[apps]` key), and
  `on_press` resolves it once per utterance and stashes the effective
  `language` / `trailing_space` / `format` / `commands` / cleaner in `st`; both
  the streaming worker and `on_release` read from `st`. Model-level fields
  (`vocabulary`, `num_beams`, `device`) aren't overridable — they're fixed at
  `Transcriber` construction.

**status.py**
- `run()` prints a snapshot — daemon up (via `ss` for `@lightweight-stt`), mode,
  hotkey, device, language, model exported?, groups, ydotoold socket, power
  profile, `battery_saver`, `llm_cleanup` target, `latency_stats`, history
  size/last entry. Config + environment only; never imports the transcriber or
  opens the mic, so it's safe while the daemon is running.

**stats.py**
- `Timings` — `add(seconds)` per transcription; `summary()` / `log_summary()`
  give `count / mean / min / max / p95` in ms. `main.run()` creates one when
  `latency_stats` is set, `emit_segment` feeds it (even on an empty transcript,
  so the timing reflects the model call), and the summary is logged on exit.

**power.py**
- `active_profile()` / `on_power_saver()` — shell out to `powerprofilesctl get`,
  return None (treated as "no change") when it's absent. When
  `battery_saver = "pause"`, `main.run()` checks once at startup and then polls
  every 30 s on a daemon thread, calling `Listener.set_muted()` on each
  transition so dictation stops in `power-saver` and resumes afterwards.

**inject.py**
- `probe(cfg) -> Injector` — picks a method, logs the choice, raises
  `NoInjectorError` if nothing viable.
- `Injector.send(text)` — strips, no-ops on empty, routes long/non-ASCII to the
  paste path, restores prior clipboard after paste, remembers the length.
- `Injector.send_key(name, repeat=1)` / `Injector.undo()` — for command mode:
  press a named key, or backspace over the last `send()`.
- Every `ydotool`/`xdotool`/`wl-copy` call goes through `_run()`, which turns a
  missing binary or a failed subprocess into `InjectionFailed` — with an
  "ydotoold isn't running" hint when that's specifically why `ydotool` failed.
  `main.run()` catches it around each utterance and logs one clean line
  instead of a traceback; each call still retries fresh next time (nothing is
  cached), so a `ydotoold` restart recovers on its own.
- `main.run_command(action, injector)` maps a `commands` value:
  `<undo>` → `undo()`, `<key:NAME>` → `send_key(NAME)`, anything else → typed
  literally. Checked in `emit_segment` against the normalised whole utterance
  before the normal type path; a matched command is never recorded to history.

**transcribe.py**
- `Transcriber(model_dir, device, language, cache_dir, min_speech_ms,
  extra_hallucinations=None)` — constructs `WhisperPipeline` with `CACHE_DIR`
  set.
- `.transcribe(pcm, language=None) -> str` — float32 mono 16 kHz in. `language`
  overrides the constructor default for that call (`<|xx|>` token, no NPU
  recompile). Enforces `min` length, feeds the numpy array directly, pins
  `language`/`task`, filters a hallucination blocklist, returns stripped text.
- Blocklist: the built-in normalised set of known silence artifacts (`"you"`,
  `"thank you"`, `"thanks for watching"`, …) **merged with the normalised
  `cfg.hallucinations`** entries. Case-insensitive, trailing punctuation
  stripped, only matched as a whole result.

**audio.py**
- `Recorder(samplerate=16000, device=None, vad=None)` — `.start()` opens a
  **fresh** `sd.InputStream` and `.stop()` tears it down. A single long-lived
  stream does not survive suspend/resume or a PipeWire restart (the callback
  goes silent); a per-utterance stream does. `device` (from `cfg.audio_device`)
  pins a specific mic so a reconnecting Bluetooth headset can't steal the default.
- `.stop() -> np.ndarray` returns the buffered utterance (capped at
  `max_seconds`) and closes the stream. `.take()` returns the buffer and clears
  it **without** closing — used between endpoints in streaming mode.
- `.rebind()` reopens the stream (no-op if not started). `main.run()` runs a 5 s
  poller in streaming mode — when `follow_default_mic` is set and no mic is
  pinned — that calls it if `sounddevice`'s default input name changes.
- `EndpointDetector` — plain RMS-energy VAD (no model). `feed(chunk)` returns
  True once speech has been heard then followed by `silence_ms` of quiet. When a
  `vad` is passed, `_callback` feeds it and fires `on_endpoint` on each segment.
- `set_paused(bool)` — the "cough key". While paused, `_callback` drops every
  chunk; pausing also clears the buffer and resuming resets the endpointer so
  the gap isn't read as a pause.

**hotkey.py**
- `Listener(cfg, on_press, on_release)` — opens all devices whose caps include
  `EV_KEY` **and** `KEY_A` (excludes mouse/touchpad BTN-only nodes and our own
  `ydotoold`/virtual uinput devices by name), `selectors` loop in its own
  thread. `cfg.hotkey` may be one name or a list, resolved to a set of
  keycodes; every other keycode is ignored, including the `LEFTMETA`/`LEFTSHIFT`
  that arrive alongside F23 from the Copilot key. The keyboard set is re-synced
  every ~2 s, so plug/unplug is picked up without a restart.
- HOLD: `on_press(lang)` at value==1, `on_release(lang)` at value==0, ignore
  value==2 repeat.
- TOGGLE: each value==1 on the owning key starts/stops; value==0/2 ignored.
- HYBRID: keydown starts; keyup after `< tap_ms` latches, else stops.
- STREAMING: like toggle for start/stop, but the `Recorder`'s `EndpointDetector`
  fires `on_endpoint` on each pause; `main.py`'s worker drains a queue and
  transcribes each segment. `mute_hotkey` pauses the whole listener.
- A session is **locked** to `_active_code`; events from any other hotkey are
  dropped until it ends. Each key's language (`hotkey_language` or `language`),
  translate flag (`hotkey_translate`) and output format (`hotkey_format` —
  `snake`/`camel`/`raw`, else `None`) are stashed on start and handed to
  `on_press`/`on_release`, which pass them through `emit_segment`; `textfmt.apply_format`
  reshapes the text after the cleaner, before typing.
- `mute_hotkey` toggles `_muted` (blocks all dictation keys); `cough_hotkey`
  fires `on_cough(True/False)` on its down/up so `main.py` can call
  `Recorder.set_paused()` — both are checked before the session lock, so they
  work mid-dictation.
- No modifier handling, no `on_cycle`.

**indicator.py**
- `set(state)` where state ∈ `ready|listening|processing|error|off`.
- notify path: one notification, fixed id 9942, `transient` hint.
- beep path: `subprocess.Popen(["canberra-gtk-play","-i",event])`, never waits.

**main.py**
- Acquire abstract-namespace socket lock (`\0lightweight-stt`); exit if taken.
- Build config → probe injector → build transcriber (blocks on NPU compile,
  shows `processing`/loading) → open recorder → start listener.
- `on_release`: `pcm = recorder.stop(); text = transcriber.transcribe(pcm);
  if text: injector.send(text + (" " if trailing_space else ""))`.
- `logging` to stderr (journald picks it up). Real `try/except` around
  transcribe/inject with `indicator.set("error")` + logged traceback — never a
  bare `except: pass`.
- `SIGINT`/`SIGTERM` → clean stream close.

## setup.sh (rewritten)

1. `apt-get install -y libportaudio2 ydotool libnotify-bin wl-clipboard libcanberra-gtk3-module xdotool`
2. Add `$USER` to `input` and `render` groups if missing (warn: re-login needed).
3. Install `udev/99-uinput.rules` → `/etc/udev/rules.d/`, `udevadm control
   --reload && udevadm trigger`.
4. venv + `pip install openvino-genai sounddevice numpy evdev`.
   **No** torch / optimum / nncf (`tomllib` is stdlib on Python 3.11+).
5. `systemctl --user enable --now ydotool` (or install a `ydotoold` unit if the
   package doesn't ship one).
6. Install + `systemctl --user enable --now lightweight-stt.service`.
7. Print post-install notes (re-login for groups, how to read logs, how to edit
   config).

`udev/99-uinput.rules`:
```
KERNEL=="uinput", SUBSYSTEM=="misc", MODE="0660", TAG+="uaccess", OPTIONS+="static_node=uinput"
```

`systemd/lightweight-stt.service`: `Type=simple`,
`ExecStart=%h/<install-dir>/venv/bin/python -m stt.main`, `Restart=on-failure`,
`WantedBy=default.target`. (Install dir templated by setup.sh.)

## Implementation order

Each phase independently checkable.

1. **Scaffold + config.py** — package skeleton, `Config`, tests for
   default/partial load. Verify: `pytest tests/test_config.py`.
2. **transcribe.py** — wrapper + blocklist. Verify: 0.3 s silence → `""`;
   `CACHE_DIR` populated after first run; runs on the NPU.
3. **inject.py** — probe + send + paste routing, `shutil.which`/`subprocess`
   mocked in tests. Verify: `python -m stt.inject "hello ☃ world"` lands text in
   a focused editor window; long string uses paste path (observe clipboard
   restore).
4. **audio.py** — recorder + ring buffer. Verify: 2 s spoken capture →
   `ndarray` ~32000 samples, dtype float32; buffer cleared after `stop()`.
5. **indicator.py** — notify + beep. Verify: state changes update one
   notification in place; beeps don't block (timed).
6. **hotkey.py** — multi-device listener + HOLD/TOGGLE state machine, mocked
   `InputDevice` event sequences. Verify: synthetic keydown/keyup → correct
   callbacks; unplug mid-run → rescan, no crash.
7. **main.py** — wire, lock, logging, signals. Verify end-to-end manual
   checklist below.
8. **setup.sh / systemd / udev / convert.sh** + README. Verify: fresh `setup.sh`
   on a clean machine brings the service up; `journalctl --user -u
   lightweight-stt` shows "Ready".
9. **stt_server.py** — swap its inline pipeline for `stt.transcribe.Transcriber`.
   Verify: `POST /transcribe` with a WAV still returns text; `/health` ok.

## Testing

- Unit: `config`, `inject` (mocked), `transcribe` (real model, small fixtures),
  `hotkey` (mocked evdev).
- Manual end-to-end checklist (README):
  - Hold the Copilot key (F23), say "testing one two three", release → text
    appears in a native Wayland editor. Confirm no Activities overview / no
    stray Super+Shift side effect from the leaked chord.
  - Same into a browser address bar.
  - Same into a terminal.
  - Long dictation (> 50 chars) → arrives via paste, clipboard afterwards
    unchanged.
  - `mode = "toggle"` in config → press/press works.
  - Kill service, external keyboard only → still triggers.
  - `systemctl --user restart lightweight-stt` → "Ready" within ~2 s (cache hit).

## Open items

Resolved against `openvino-genai` 2026.2 during implementation:

- **`ASRPipeline` does not exist** — use `WhisperPipeline`. No alias handling.
- **`generate()` input**: pass the **numpy float32 array directly**. Python
  `list` also works; `ov.Tensor` raises `TypeError`. No `.tolist()` needed.
- **`language` must be `"<|en|>"` form**; plain `"en"` raises
  `lang_to_id.count` RuntimeError. `transcribe.py` maps `cfg.language` →
  `f"<|{cfg.language}|>"`. `task="transcribe"`, `return_timestamps=False` OK.
- **`CACHE_DIR`**: `WhisperPipeline(model_dir, "NPU", CACHE_DIR=...)` works;
  cold load ~11 s → warm load ~2 s. Two `.blob` files (encoder+decoder).
- **Silence → `" you"`** — hallucination gate + min-length gate are mandatory;
  blocklist must include `"you"`.
- `openvino-genai` alone drives the NPU (no extra runtime pkg needed).

Resolved during the on-box trial:

- **`ydotool` systemd unit** — on this Ubuntu the package *does* ship
  `/usr/lib/systemd/user/ydotool.service` and `setup.sh` enables it. Older /
  non-Ubuntu setups may not, so `setup.sh` checks for it and writes its own
  `systemd/ydotoold.service` (socket at `%t/.ydotool_socket`) as a fallback.
- **`canberra-gtk-play`** — *not* shipped by `libcanberra-gtk3-module`; on GNOME
  it comes from `gnome-session-canberra`, which `setup.sh` now installs
  explicitly. The beep path already degrades to a no-op if the binary is
  missing, so no hard dependency.
